from __future__ import annotations

import queue
import threading
from collections.abc import Callable

from ..config import settings
from ..database import connect, now, rows
from . import agent_runner


_queue: queue.Queue[int] = queue.Queue()
_lock = threading.Lock()
_control = threading.Condition()
_workers: list[threading.Thread] = []
_active_job_ids: set[int] = set()
_project_loader: Callable[[int], dict] | None = None


class JobCancelled(Exception):
    """Stop a cooperative background turn without recording a failure."""


def start(project_loader: Callable[[int], dict]) -> None:
    global _project_loader
    _project_loader = project_loader
    with _lock:
        _workers[:] = [worker for worker in _workers if worker.is_alive()]
        desired = max(1, min(settings.agent_job_workers, 8))
        for index in range(len(_workers), desired):
            worker = threading.Thread(target=_work, name=f"olladex-agent-jobs-{index + 1}", daemon=True)
            worker.start()
            _workers.append(worker)
    with connect() as conn:
        conn.execute("UPDATE agent_jobs SET status='queued',started_at='' WHERE status='running'")
        queued = [row["id"] for row in conn.execute("SELECT id FROM agent_jobs WHERE status='queued' ORDER BY id")]
    for job_id in queued:
        _queue.put(job_id)


def enqueue(project_id: int, session_id: int, prompt: str, source: str = "manual") -> dict:
    stamp = now()
    with connect() as conn:
        session = conn.execute("SELECT id FROM sessions WHERE id=? AND project_id=?", (session_id, project_id)).fetchone()
        if not session:
            raise ValueError("Session not found in this project")
        cursor = conn.execute("INSERT INTO agent_jobs(project_id,session_id,prompt,source,status,created_at) VALUES(?,?,?,?,?,?)", (project_id, session_id, prompt, source, "queued", stamp))
        job_id = cursor.lastrowid
    _queue.put(job_id)
    return get(job_id)


def get(job_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM agent_jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else {}


def list_for_project(project_id: int) -> list[dict]:
    with connect() as conn:
        return rows(conn.execute("SELECT * FROM agent_jobs WHERE project_id=? ORDER BY id DESC LIMIT 100", (project_id,)))


def cancel(job_id: int, project_id: int) -> dict:
    with connect() as conn:
        job = conn.execute("SELECT * FROM agent_jobs WHERE id=? AND project_id=?", (job_id, project_id)).fetchone()
        if not job:
            raise ValueError("Background job not found")
        if job["status"] not in {"queued", "running", "paused"}:
            raise ValueError("Only active jobs can be cancelled")
        conn.execute("UPDATE agent_jobs SET status='cancelled',completed_at=? WHERE id=?", (now(), job_id))
    with _control:
        _control.notify_all()
    return get(job_id)


def pause(job_id: int, project_id: int) -> dict:
    with connect() as conn:
        job = conn.execute("SELECT * FROM agent_jobs WHERE id=? AND project_id=?", (job_id, project_id)).fetchone()
        if not job:
            raise ValueError("Background job not found")
        if job["status"] != "running":
            raise ValueError("Only running jobs can be paused")
        conn.execute("UPDATE agent_jobs SET status='paused' WHERE id=?", (job_id,))
    return get(job_id)


def resume(job_id: int, project_id: int) -> dict:
    with connect() as conn:
        job = conn.execute("SELECT * FROM agent_jobs WHERE id=? AND project_id=?", (job_id, project_id)).fetchone()
        if not job:
            raise ValueError("Background job not found")
        if job["status"] != "paused":
            raise ValueError("Only paused jobs can be resumed")
        with _lock:
            attached = job_id in _active_job_ids
        status = "running" if attached else "queued"
        conn.execute("UPDATE agent_jobs SET status=? WHERE id=?", (status, job_id))
    if attached:
        with _control:
            _control.notify_all()
    else:
        _queue.put(job_id)
    return get(job_id)


def capacity() -> dict:
    with _lock:
        workers = len([worker for worker in _workers if worker.is_alive()])
        active = len(_active_job_ids)
    return {"workers": workers, "active": active, "available": max(0, workers - active)}


def _checkpoint(job_id: int) -> None:
    while True:
        job = get(job_id)
        if not job or job["status"] == "cancelled":
            raise JobCancelled()
        if job["status"] != "paused":
            return
        with _control:
            _control.wait(timeout=0.25)


def _work() -> None:
    while True:
        job_id = _queue.get()
        try:
            job = get(job_id)
            if not job or job["status"] != "queued" or _project_loader is None:
                continue
            with _lock:
                _active_job_ids.add(job_id)
            with connect() as conn:
                claimed = conn.execute("UPDATE agent_jobs SET status='running',started_at=?,error='' WHERE id=? AND status='queued'", (now(), job_id))
                if claimed.rowcount != 1:
                    continue
            project = _project_loader(job["project_id"])
            message = agent_runner.run(job["session_id"], project, job["prompt"], checkpoint=lambda: _checkpoint(job_id))
            _checkpoint(job_id)
            with connect() as conn:
                conn.execute("UPDATE agent_jobs SET status='completed',result_message_id=?,completed_at=? WHERE id=?", (message["id"], now(), job_id))
        except JobCancelled:
            pass
        except Exception as exc:
            with connect() as conn:
                conn.execute("UPDATE agent_jobs SET status='failed',error=?,completed_at=? WHERE id=? AND status!='cancelled'", (str(exc)[:20_000], now(), job_id))
        finally:
            with _lock:
                _active_job_ids.discard(job_id)
            _queue.task_done()
