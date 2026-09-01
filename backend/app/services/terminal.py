import os
import subprocess

from ..config import settings
from .workspace import project_root


BLOCKED_EXACT = {"reboot", "shutdown", "poweroff", "halt"}
BLOCKED_PARTS = ("rm -rf /", "mkfs", "> /dev/", "dd if=", ":(){:|:&};:")


def run(project: dict, command: str, timeout: int | None = None) -> dict:
    normalized = command.strip().lower()
    if normalized in BLOCKED_EXACT or any(part in normalized for part in BLOCKED_PARTS):
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

