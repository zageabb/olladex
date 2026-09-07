import os
import shutil
import subprocess

from ..config import settings
from .workspace import project_root


BLOCKED_EXACT = {"reboot", "shutdown", "poweroff", "halt"}
BLOCKED_PARTS = ("rm -rf /", "mkfs", "> /dev/", "dd if=", ":(){:|:&};:")



def shell_command(command: str) -> list[str]:
    """Return the closest local interactive shell for the host platform."""
    if os.name != "nt":
        return ["/bin/bash", "-lc", command]
    bash = shutil.which("bash.exe")
    if bash:
        return [bash, "-lc", command]
    powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if powershell:
        return [powershell, "-NoLogo", "-NoProfile", "-Command", command]
    return ["cmd.exe", "/d", "/s", "/c", command]


def blocked(command: str) -> bool:
    normalized = command.strip().lower()
    return normalized in BLOCKED_EXACT or any(part in normalized for part in BLOCKED_PARTS)


def requires_approval(project: dict, command: str) -> bool:
    mode = project.get("approval_mode", "assisted")
    return mode != "autonomous"


def run(project: dict, command: str, timeout: int | None = None) -> dict:
    """Bounded output and cancellation of the entire process group."""
    import threading
    import time
    from . import task_queue
    from .processes import terminate
    if blocked(command):
        return {"command": command, "output": "Command blocked by Olladex safety policy.", "exit_code": 126}
    process = subprocess.Popen(shell_command(command), cwd=project_root(project),
        env={**os.environ, "TERM": "xterm-256color"}, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
    chunks = bytearray()
    from . import conversation_runtime
    run_id = conversation_runtime.current_id()
    def collect():
        emitted = 0
        while data := process.stdout.read1(8192):
            chunks.extend(data)
            if run_id and emitted < 200_000:
                text = data[:200_000-emitted].decode("utf-8", errors="replace")
                conversation_runtime.emit("command_output", {"text": text}, run_id)
                emitted += len(data)
                if emitted >= 200_000:
                    conversation_runtime.emit("command_output", {"text": "\n[Live output limit reached; final output retains the last 200 KB.]"}, run_id)
            if len(chunks) > 200_000:
                del chunks[:-200_000]
    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    deadline = time.monotonic() + (timeout or settings.command_timeout_seconds)
    code = None
    try:
        while process.poll() is None:
            from . import conversation_runtime
            if task_queue.cancel_requested() or conversation_runtime.cancelled():
                code = 130
                break
            if time.monotonic() >= deadline:
                code = 124
                break
            time.sleep(.05)
    finally:
        # Reap descendants even when their parent shell has already exited.
        terminate(process)
        process.wait()
        reader.join(timeout=2)
    output = bytes(chunks).decode("utf-8", errors="replace")
    if code == 124:
        output += "\nCommand timed out."
    return {"command": command, "output": output, "exit_code": code if code is not None else process.returncode}
