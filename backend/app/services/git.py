import subprocess

from .workspace import project_root


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
        return {"repository": False, "branch": "", "changes": [], "recent": []}
    _, branch = _git(project, "branch", "--show-current")
    _, porcelain = _git(project, "status", "--short")
    _, log = _git(project, "log", "-5", "--pretty=format:%h%x09%s%x09%cr")
    changes = []
    for line in porcelain.splitlines():
        if len(line) >= 4:
            changes.append({"status": line[:2].strip() or "?", "path": line[3:]})
    recent = []
    for line in log.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            recent.append({"sha": parts[0], "subject": parts[1], "age": parts[2]})
    return {"repository": True, "branch": branch.strip() or "detached", "changes": changes, "recent": recent}


def diff(project: dict) -> str:
    _, output = _git(project, "diff", "--", ".")
    _, staged = _git(project, "diff", "--cached", "--", ".")
    return (output + ("\n# Staged changes\n" + staged if staged else ""))[-500_000:]

