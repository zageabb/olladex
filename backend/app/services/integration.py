from __future__ import annotations

import shutil
from pathlib import Path

from ..config import settings
from . import worktrees
from .workspace import project_root


def _integration_root(project: dict) -> Path:
    return (settings.data_root.expanduser().resolve() / "integrations" / str(project["id"])).resolve()


def _validate_branch(branch: str) -> str:
    branch = branch.strip()
    if not branch.startswith("olladex/task-"):
        raise ValueError(f"Refusing non-task branch: {branch}")
    return branch


def changed_files(project: dict, branch: str, base: str = "main") -> list[str]:
    branch = _validate_branch(branch)
    root = project_root(project)
    code, output = worktrees._git(root, "diff", "--name-only", f"{base}...{branch}", "--", ".")
    if code:
        raise ValueError(output.strip() or f"Could not compare {branch} with {base}")
    return [line.strip() for line in output.splitlines() if line.strip()]


def preflight(project: dict, branches: list[str], base: str = "main") -> dict:
    unique = []
    for branch in branches:
        branch = _validate_branch(branch)
        if branch not in unique:
            unique.append(branch)
    if not unique:
        raise ValueError("Select at least one specialist branch")
    files_by_branch = {branch: changed_files(project, branch, base) for branch in unique}
    owners: dict[str, list[str]] = {}
    for branch, files in files_by_branch.items():
        for path in files:
            owners.setdefault(path, []).append(branch)
    overlaps = [{"path": path, "branches": branch_names} for path, branch_names in owners.items() if len(branch_names) > 1]
    return {"base": base, "branches": unique, "files_by_branch": files_by_branch, "overlaps": overlaps}


def create(project: dict, lead_task_id: int, branches: list[str], base: str = "main") -> dict:
    plan = preflight(project, branches, base)
    root = project_root(project)
    managed = _integration_root(project)
    managed.mkdir(parents=True, exist_ok=True)
    path = managed / f"lead-{lead_task_id}"
    branch = f"olladex/integration-{lead_task_id}"
    if path.exists():
        code, current = worktrees._git(path, "branch", "--show-current")
        if code == 0 and current.strip() == branch:
            return {"path": str(path), "branch": branch, "reused": True, **plan}
        shutil.rmtree(path, ignore_errors=True)
    worktrees._git(root, "branch", "-D", branch)
    code, output = worktrees._git(root, "worktree", "add", "-b", branch, str(path), base, timeout=120)
    if code:
        raise ValueError(output.strip() or "Could not create integration worktree")
    applied: list[dict] = []
    try:
        for source_branch in plan["branches"]:
            code, commits = worktrees._git(path, "rev-list", "--reverse", f"{base}..{source_branch}")
            if code:
                raise ValueError(commits.strip() or f"Could not enumerate commits for {source_branch}")
            shas = [line.strip() for line in commits.splitlines() if line.strip()]
            if not shas:
                raise ValueError(f"{source_branch} has no committed changes relative to {base}")
            for sha in shas:
                code, output = worktrees._git(path, "cherry-pick", sha, timeout=180)
                if code:
                    worktrees._git(path, "cherry-pick", "--abort")
                    raise ValueError(f"Integration conflict while applying {source_branch} ({sha[:12]}): {output.strip()}")
                applied.append({"branch": source_branch, "sha": sha})
    except Exception:
        # Preserve the integration worktree for inspection after safe cherry-pick abort.
        raise
    return {"path": str(path), "branch": branch, "reused": False, "applied": applied, **plan, **summary(project, str(path), base)}


def integration_project(project: dict, path: str) -> dict:
    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(_integration_root(project))
    except ValueError as exc:
        raise ValueError("Integration worktree is outside Olladex's managed directory") from exc
    if not target.is_dir():
        raise ValueError("Integration worktree is no longer available")
    return {**project, "path": str(target)}


def summary(project: dict, path: str, base: str = "main") -> dict:
    target_project = integration_project(project, path)
    root = project_root(target_project)
    _, branch = worktrees._git(root, "branch", "--show-current")
    _, head = worktrees._git(root, "rev-parse", "HEAD")
    _, status = worktrees._git(root, "status", "--short")
    diff_code, diff = worktrees._git(root, "diff", f"{base}...HEAD", "--", ".")
    return {
        "path": str(root), "branch": branch.strip(), "head": head.strip(), "base": base,
        "changes": [line for line in status.splitlines() if line],
        "diff": diff[-750_000:] if diff_code == 0 else "",
    }


def run_checks(project: dict, path: str, command: str) -> dict:
    command = command.strip()
    if not command:
        raise ValueError("A check command is required")
    target_project = integration_project(project, path)
    root = project_root(target_project)
    import subprocess
    completed = subprocess.run(command, cwd=root, text=True, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900, check=False)
    return {"command": command, "exit_code": completed.returncode, "output": completed.stdout[-300_000:], "passed": completed.returncode == 0}


def push(project: dict, path: str, remote: str = "origin") -> dict:
    target_project = integration_project(project, path)
    root = project_root(target_project)
    _, branch = worktrees._git(root, "branch", "--show-current")
    branch = branch.strip()
    if not branch.startswith("olladex/integration-"):
        raise ValueError("Refusing to push a non-integration branch")
    code, output = worktrees._git(root, "push", "-u", remote, branch, timeout=180)
    if code:
        raise ValueError(output.strip() or "Integration branch push failed")
    return {"branch": branch, "remote": remote, "output": output.strip()}


def remove(project: dict, path: str, branch: str, force: bool = False) -> dict:
    root = project_root(project)
    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(_integration_root(project))
    except ValueError as exc:
        raise ValueError("Refusing to remove an integration worktree outside Olladex's managed directory") from exc
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(target))
    code, output = worktrees._git(root, *args, timeout=120)
    if code:
        raise ValueError(output.strip() or "Could not remove integration worktree")
    if branch:
        worktrees._git(root, "branch", "-D" if force else "-d", branch)
    worktrees._git(root, "worktree", "prune")
    return {"path": str(target), "branch": branch, "removed": True}
