from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..config import settings
from .workspace import project_root


def _git(root: Path, *args: str, timeout: int = 60) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", *args], cwd=root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=timeout, check=False,
    )
    return completed.returncode, completed.stdout


def managed_root(project: dict) -> Path:
    return (settings.data_root.expanduser().resolve() / "worktrees" / str(project["id"])).resolve()


def task_project(project: dict, path: str) -> dict:
    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(managed_root(project))
    except ValueError as exc:
        raise ValueError("Task worktree is outside Olladex's managed directory") from exc
    if not target.is_dir():
        raise ValueError("Task worktree is no longer available")
    return {**project, "path": str(target)}


def create_for_task(project: dict, task_id: int, start_ref: str = "HEAD") -> dict:
    root = project_root(project)
    code, inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if code or inside.strip() != "true":
        raise ValueError("Parallel task isolation requires a Git repository")
    base = managed_root(project)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"task-{task_id}"
    branch = f"olladex/task-{task_id}"
    if path.exists():
        code, head = _git(path, "branch", "--show-current")
        if code == 0:
            return {"path": str(path), "branch": head.strip() or branch, "reused": True}
        shutil.rmtree(path, ignore_errors=True)
    branch_exists, _ = _git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    if branch_exists == 0:
        code, output = _git(root, "worktree", "add", str(path), branch, timeout=120)
    else:
        code, output = _git(root, "worktree", "add", "-b", branch, str(path), start_ref, timeout=120)
    if code:
        raise ValueError(output.strip() or "Could not create isolated Git worktree")
    return {"path": str(path), "branch": branch, "reused": branch_exists == 0}


def inherit_branches(project: dict, path: str, branches: list[str]) -> dict:
    task = task_project(project, path)
    root = project_root(task)
    unique: list[str] = []
    for branch in branches:
        branch = str(branch or "").strip()
        if not branch:
            continue
        if not branch.startswith("olladex/task-"):
            raise ValueError(f"Refusing non-task dependency branch: {branch}")
        if branch not in unique:
            unique.append(branch)
    for branch in unique:
        ancestor_code, _ = _git(root, "merge-base", "--is-ancestor", branch, "HEAD")
        if ancestor_code == 0:
            continue
        code, output = _git(
            root,
            "-c", f"user.name={project.get('git_author_name') or 'Olladex User'}",
            "-c", f"user.email={project.get('git_author_email') or 'olladex@local'}",
            "merge", "--no-edit", branch,
            timeout=180,
        )
        if code:
            _git(root, "merge", "--abort")
            raise ValueError(f"Dependency branch {branch} could not be inherited: {output.strip()}")
    return summary(project, path)


def summary(project: dict, path: str, base: str = "main") -> dict:
    task = task_project(project, path)
    root = project_root(task)
    _, branch = _git(root, "branch", "--show-current")
    _, status = _git(root, "status", "--short")
    _, head = _git(root, "rev-parse", "HEAD")
    base_code, base_sha = _git(root, "rev-parse", base)
    diff_code, diff = _git(root, "diff", f"{base}...HEAD", "--", ".")
    _, working = _git(root, "diff", "--", ".")
    return {
        "path": str(root), "branch": branch.strip(), "head": head.strip(),
        "base": base, "base_sha": base_sha.strip() if base_code == 0 else "",
        "changes": [line for line in status.splitlines() if line],
        "branch_diff": diff[-500_000:] if diff_code == 0 else "",
        "working_diff": working[-500_000:],
    }


def commit_all(project: dict, path: str, message: str) -> dict:
    if not message.strip():
        raise ValueError("Commit message is required")
    task = task_project(project, path)
    root = project_root(task)
    code, output = _git(root, "add", "--all")
    if code:
        raise ValueError(output.strip() or "Could not stage task changes")
    quiet, _ = _git(root, "diff", "--cached", "--quiet")
    if quiet == 0:
        raise ValueError("There are no task changes to commit")
    code, output = _git(
        root,
        "-c", f"user.name={project.get('git_author_name') or 'Olladex User'}",
        "-c", f"user.email={project.get('git_author_email') or 'olladex@local'}",
        "commit", "-m", message,
        timeout=120,
    )
    if code:
        raise ValueError(output.strip() or "Task commit failed")
    _, sha = _git(root, "rev-parse", "HEAD")
    return {"sha": sha.strip(), "output": output.strip(), **summary(project, path)}


def push(project: dict, path: str, remote: str = "origin") -> dict:
    task = task_project(project, path)
    root = project_root(task)
    _, branch = _git(root, "branch", "--show-current")
    branch = branch.strip()
    if not branch.startswith("olladex/task-"):
        raise ValueError("Refusing to push a non-task branch through the task workflow")
    code, output = _git(root, "push", "-u", remote, branch, timeout=180)
    if code:
        raise ValueError(output.strip() or "Task branch push failed")
    return {"branch": branch, "remote": remote, "output": output.strip()}


def remove(project: dict, path: str, branch: str = "", force: bool = False) -> dict:
    root = project_root(project)
    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(managed_root(project))
    except ValueError as exc:
        raise ValueError("Refusing to remove a worktree outside Olladex's managed worktree directory") from exc
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(target))
    code, output = _git(root, *args, timeout=120)
    if code:
        raise ValueError(output.strip() or "Could not remove worktree")
    if branch:
        _git(root, "branch", "-D" if force else "-d", branch)
    _git(root, "worktree", "prune")
    return {"path": str(target), "branch": branch, "removed": True}
