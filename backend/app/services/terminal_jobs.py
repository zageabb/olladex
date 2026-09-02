from __future__ import annotations

import os
import select
import signal
import subprocess
import threading
import time

if os.name != "nt":
    import fcntl
    import pty
    import struct
    import termios

from ..database import connect, now
from .terminal import blocked, shell_command
from . import windows_pty
from .workspace import project_root


_jobs: dict[int, dict] = {}
_lock = threading.Lock()


def start(project: dict, run_id: int, command: str, timeout_seconds: int = 600, columns: int = 120, rows: int = 32) -> dict:
    if blocked(command):
        with connect() as conn:
            conn.execute("UPDATE command_runs SET output=?,exit_code=?,status=?,updated_at=? WHERE id=?", ("Command blocked by Olladex safety policy.", 126, "blocked", now(), run_id))
        return status(run_id)
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    if os.name == "nt":
        if windows_pty.available():
            process = windows_pty.spawn(shell_command(command), str(project_root(project)), env, rows, columns)
            backend = "conpty"
        else:
            process = subprocess.Popen(
                shell_command(command), cwd=project_root(project), env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            backend = "windows-pipes"
        master = None
    else:
        master, slave = pty.openpty()
        process = subprocess.Popen(
            shell_command(command), cwd=project_root(project), env=env,
            stdin=slave, stdout=slave, stderr=slave,
            start_new_session=True, close_fds=True,
        )
        os.close(slave)
        backend = "posix-pty"
    job = {"process": process, "master": master, "backend": backend, "output": "", "status": "running", "exit_code": -1, "started": time.monotonic(), "timeout": timeout_seconds}
    with _lock:
        _jobs[run_id] = job
    with connect() as conn:
        conn.execute("UPDATE command_runs SET status='running',updated_at=? WHERE id=?", (now(), run_id))
    threading.Thread(target=_collect, args=(run_id,), daemon=True).start()
    return status(run_id)


def _collect(run_id: int) -> None:
    with _lock:
        job = _jobs[run_id]
    process = job["process"]
    timed_out = False
    if os.name == "nt":
        reader = _collect_windows_output(job)
        while _process_alive(job):
            if time.monotonic() - job["started"] > job["timeout"]:
                timed_out = True
                _terminate(job)
                break
            time.sleep(0.05)
        if job["backend"] == "windows-pipes":
            process.wait()
        reader.join(timeout=1)
        _finish(run_id, job, timed_out)
        return

    master = job["master"]
    eof = False
    while True:
        if time.monotonic() - job["started"] > job["timeout"] and process.poll() is None:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        ready, _, _ = select.select([master], [], [], 0.1)
        if ready:
            try:
                chunk = os.read(master, 65536)
                if chunk:
                    with _lock:
                        job["output"] = (job["output"] + chunk.decode("utf-8", errors="replace"))[-500_000:]
                else:
                    eof = True
            except OSError:
                eof = True
        if process.poll() is not None:
            # A child may exit before its final PTY bytes become readable.
            # Wait briefly and drain them instead of truncating fast commands.
            trailing, _, _ = select.select([master], [], [], 0.05)
            if eof or not trailing:
                break
    try:
        os.close(master)
    except OSError:
        pass
    _finish(run_id, job, timed_out)


def _collect_windows_output(job: dict) -> threading.Thread:
    def read_pipe() -> None:
        if job["backend"] == "conpty":
            while True:
                try:
                    chunk = job["process"].read(65536)
                except (EOFError, OSError):
                    return
                if not chunk:
                    return
                with _lock:
                    job["output"] = (job["output"] + chunk)[-500_000:]
            return
        stream = job["process"].stdout
        if stream is None:
            return
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            with _lock:
                job["output"] = (job["output"] + chunk.decode("utf-8", errors="replace"))[-500_000:]

    reader = threading.Thread(target=read_pipe, daemon=True)
    reader.start()
    return reader


def _finish(run_id: int, job: dict, timed_out: bool) -> None:
    process = job["process"]
    exit_code = getattr(process, "exitstatus", None) if job.get("backend") == "conpty" else process.returncode
    exit_code = exit_code if exit_code is not None else 1
    final_status = "timed_out" if timed_out else ("cancelled" if job.get("cancelled") else "completed")
    with _lock:
        job["exit_code"] = 124 if timed_out else exit_code
        job["status"] = final_status
        output = job["output"] + ("\nCommand timed out." if timed_out else "")
    with connect() as conn:
        conn.execute("UPDATE command_runs SET output=?,exit_code=?,status=?,updated_at=? WHERE id=?", (output, job["exit_code"], final_status, now(), run_id))


def status(run_id: int) -> dict:
    with _lock:
        job = _jobs.get(run_id)
        if job:
            return {"id": run_id, "output": job["output"], "exit_code": job["exit_code"], "status": job["status"], "backend": job.get("backend", "")}
    with connect() as conn:
        row = conn.execute("SELECT * FROM command_runs WHERE id=?", (run_id,)).fetchone()
    return dict(row) if row else {}


def cancel(run_id: int) -> dict:
    with _lock:
        job = _jobs.get(run_id)
        if not job or job["status"] != "running":
            return status(run_id)
        job["cancelled"] = True
        process = job["process"]
    try:
        if os.name == "nt":
            _terminate(job)
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    return status(run_id)


def write_input(run_id: int, data: str) -> dict:
    with _lock:
        job = _jobs.get(run_id)
        if not job or job["status"] != "running":
            raise ValueError("The command is not running or no longer accepts input")
        master = job["master"]
        process = job["process"]
    if os.name == "nt":
        if job["backend"] == "conpty":
            process.write(data)
        else:
            if process.stdin is None:
                raise ValueError("The command does not accept input")
            process.stdin.write(data.encode("utf-8"))
            process.stdin.flush()
    else:
        os.write(master, data.encode("utf-8"))
    return status(run_id)


def resize(run_id: int, columns: int, rows: int) -> dict:
    with _lock:
        job = _jobs.get(run_id)
        if not job or job["status"] != "running":
            raise ValueError("The command is not running or no longer accepts terminal resize events")
        master = job["master"]
    if os.name == "nt" and job.get("backend") == "conpty":
        job["process"].setwinsize(rows, columns)
    elif os.name != "nt":
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
    return status(run_id)


def _process_alive(job: dict) -> bool:
    if job.get("backend") == "conpty":
        return bool(job["process"].isalive())
    return job["process"].poll() is None


def _terminate(job: dict) -> None:
    if job.get("backend") == "conpty":
        job["process"].terminate(force=True)
    else:
        job["process"].terminate()
