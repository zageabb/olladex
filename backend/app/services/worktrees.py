from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..config import settings
from .workspace import project_root


def _git(root: Path, *args: str, timeout: int = 60) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    return completed.returncode, completed.stdout


def create_for_task(project: dict, task_id: int) -> dict:
    root = project_root(project)
    code, inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if code or inside.strip() != "true":
        raise ValueError("Parallel task isolation requires a Git repository")

    base = settings.data_root.expanduser().resolve() / "worktrees" / str(project["id"])
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"task-{task_id}"
    branch = f"olladex/task-{task_id}"

    if path.exists():
        code, head = _git(path, "branch", "--show-current")
        if code == 0:
            return {"path": str(path), "branch": head.strip() or branch, "reused": True}
        shutil.rmtree(path, ignore_errors=True)

    code, output = _git(root, "worktree", "add", "-b", branch, str(path), "HEAD", timeout=120)
    if code:
        raise ValueError(output.strip() or "Could not create isolated Git worktree")
    return {"path": str(path), "branch": branch, "reused": False}


def remove(project: dict, path: str, branch: str = "", force: bool = False) -> dict:
    root = project_root(project)
    target = Path(path).expanduser().resolve()
    managed_root = (settings.data_root.expanduser().resolve() / "worktrees" / str(project["id"])).resolve()
    try:
        target.relative_to(managed_root)
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
        delete_args = ["branch", "-D" if force else "-d", branch]
        _git(root, *delete_args)
    _git(root, "worktree", "prune")
    return {"path": str(target), "branch": branch, "removed": True}
