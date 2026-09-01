import os
import subprocess

from ..config import settings
from .workspace import project_root


BLOCKED_EXACT = {"reboot", "shutdown", "poweroff", "halt"}
BLOCKED_PARTS = ("rm -rf /", "mkfs", "> /dev/", "dd if=", ":(){:|:&};:")
ASSISTED_PREFIXES = (
    "git status", "git diff", "git log", "git branch --show-current",
    "pytest", "python -m pytest", "npm test", "npm run test", "npm run build",
    "npm run lint", "pnpm test", "pnpm build", "yarn test", "yarn build",
    "ls", "find ", "rg ", "grep ", "pwd", "cat ", "sed ", "head ", "tail ",
)


def blocked(command: str) -> bool:
    normalized = command.strip().lower()
    return normalized in BLOCKED_EXACT or any(part in normalized for part in BLOCKED_PARTS)


def requires_approval(project: dict, command: str) -> bool:
    mode = project.get("approval_mode", "assisted")
    normalized = command.strip().lower()
    if mode == "autonomous":
        return False
    if mode == "review":
        return True
    return not any(normalized == prefix or normalized.startswith(prefix) for prefix in ASSISTED_PREFIXES)


def run(project: dict, command: str, timeout: int | None = None) -> dict:
    if blocked(command):
        return {"command": command, "output": "Command blocked by Olladex safety policy.", "exit_code": 126}
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    try:
        completed = subprocess.run(
            ["/bin/bash", "-lc", command],
            cwd=project_root(project),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout or settings.command_timeout_seconds,
            check=False,
        )
        return {"command": command, "output": completed.stdout[-200_000:], "exit_code": completed.returncode}
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        return {"command": command, "output": output + "\nCommand timed out.", "exit_code": 124}
