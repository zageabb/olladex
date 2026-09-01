import subprocess

from .workspace import project_root
from .workspace import safe_path


def _git(project: dict, *args: str) -> tuple[int, str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=project_root(project),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )
    return completed.returncode, completed.stdout


def summary(project: dict) -> dict:
    code, inside = _git(project, "rev-parse", "--is-inside-work-tree")
    if code != 0:
        return {"repository": False, "branch": "", "branches": [], "changes": [], "recent": []}
    _, branch = _git(project, "branch", "--show-current")
    _, porcelain = _git(project, "status", "--short")
    _, log = _git(project, "log", "-5", "--pretty=format:%h%x09%s%x09%cr")
    _, branch_output = _git(project, "branch", "--format=%(refname:short)")
    changes = []
    for line in porcelain.splitlines():
        if len(line) >= 4:
            code = line[:2]
            changes.append({"status": code.strip() or "?", "path": line[3:], "staged": code[0] not in {" ", "?"}, "unstaged": code[1] not in {" ", "?"}})
    recent = []
    for line in log.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            recent.append({"sha": parts[0], "subject": parts[1], "age": parts[2]})
    return {"repository": True, "branch": branch.strip() or "detached", "branches": [item for item in branch_output.splitlines() if item], "changes": changes, "recent": recent}


def diff(project: dict) -> str:
    _, output = _git(project, "diff", "--", ".")
    _, staged = _git(project, "diff", "--cached", "--", ".")
    return (output + ("\n# Staged changes\n" + staged if staged else ""))[-500_000:]


def _relative_paths(project: dict, paths: list[str]) -> list[str]:
    root = project_root(project)
    result = []
    for value in paths:
        resolved = safe_path(project, value)
        result.append(resolved.relative_to(root).as_posix() or ".")
    return result


def stage(project: dict, paths: list[str]) -> dict:
    normalized = _relative_paths(project, paths)
    code, output = _git(project, "add", "--", *normalized)
    if code:
        raise ValueError(output.strip() or "Git stage failed")
    return summary(project)


def unstage(project: dict, paths: list[str]) -> dict:
    normalized = _relative_paths(project, paths)
    code, output = _git(project, "restore", "--staged", "--", *normalized)
    if code:
        code, output = _git(project, "reset", "HEAD", "--", *normalized)
    if code:
        code, output = _git(project, "rm", "--cached", "--", *normalized)
    if code:
        raise ValueError(output.strip() or "Git unstage failed")
    return summary(project)


def validate_branch(project: dict, name: str) -> None:
    code, output = _git(project, "check-ref-format", "--branch", name)
    if code:
        raise ValueError(output.strip() or "Invalid branch name")


def create_branch(project: dict, name: str, checkout: bool = True) -> dict:
    validate_branch(project, name)
    args = ("switch", "-c", name) if checkout else ("branch", name)
    code, output = _git(project, *args)
    if code:
        raise ValueError(output.strip() or "Could not create branch")
    return summary(project)


def checkout(project: dict, name: str) -> dict:
    validate_branch(project, name)
    code, output = _git(project, "switch", name)
    if code:
        raise ValueError(output.strip() or "Could not switch branch")
    return summary(project)


def commit(project: dict, message: str) -> dict:
    staged_code, _ = _git(project, "diff", "--cached", "--quiet")
    if staged_code == 0:
        raise ValueError("There are no staged changes to commit")
    code, output = _git(
        project,
        "-c", f"user.name={project.get('git_author_name') or 'Olladex User'}",
        "-c", f"user.email={project.get('git_author_email') or 'olladex@local'}",
        "commit", "-m", message,
    )
    if code:
        raise ValueError(output.strip() or "Git commit failed")
    _, sha = _git(project, "rev-parse", "HEAD")
    return {"sha": sha.strip(), "output": output, "summary": summary(project)}
