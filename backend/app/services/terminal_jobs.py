from __future__ import annotations

import os
import pty
import select
import signal
import subprocess
import threading
import time

from ..database import connect, now
from .terminal import blocked
from .workspace import project_root


_jobs: dict[int, dict] = {}
_lock = threading.Lock()


def start(project: dict, run_id: int, command: str, timeout_seconds: int = 600) -> dict:
    if blocked(command):
        with connect() as conn:
            conn.execute("UPDATE command_runs SET output=?,exit_code=?,status=?,updated_at=? WHERE id=?", ("Command blocked by Olladex safety policy.", 126, "blocked", now(), run_id))
        return status(run_id)
    master, slave = pty.openpty()
    env = os.environ.copy()
    env["TERM"] = "dumb"
    process = subprocess.Popen(
        ["/bin/bash", "-lc", command],
        cwd=project_root(project),
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave)
    job = {"process": process, "master": master, "output": "", "status": "running", "exit_code": -1, "started": time.monotonic(), "timeout": timeout_seconds}
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
    master = job["master"]
    timed_out = False
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
            except OSError:
                pass
        if process.poll() is not None:
            break
    try:
        os.close(master)
    except OSError:
        pass
    exit_code = process.returncode if process.returncode is not None else 1
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
            return {"id": run_id, "output": job["output"], "exit_code": job["exit_code"], "status": job["status"]}
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
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    return status(run_id)

