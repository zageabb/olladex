from __future__ import annotations

import threading
from collections.abc import Callable

from ..database import connect, now


TaskHandler = Callable[[dict], str]
_handler: TaskHandler | None = None
_thread: threading.Thread | None = None
_stop = threading.Event()
_wake = threading.Event()
_lock = threading.Lock()


def start(handler: TaskHandler) -> None:
    global _handler, _thread
    with _lock:
        if _thread and _thread.is_alive():
            _handler = handler
            return
        _handler = handler
        _stop.clear()
        _wake.clear()
        with connect() as conn:
            conn.execute("UPDATE background_tasks SET status='cancelled',completed_at=? WHERE status='running' AND cancel_requested=1", (now(),))
            conn.execute("UPDATE background_tasks SET status='queued',started_at='' WHERE status='running'")
        _thread = threading.Thread(target=_worker, name="olladex-task-queue", daemon=True)
        _thread.start()


def stop() -> None:
    global _thread
    _stop.set()
    _wake.set()
    thread = _thread
    if thread and thread.is_alive():
        thread.join(timeout=2)
    _thread = None


def enqueue(project_id: int, session_id: int, title: str, prompt: str, source_kind: str = "manual", source_ref: str = "") -> dict:
    stamp = now()
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO background_tasks(project_id,session_id,title,prompt,source_kind,source_ref,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (project_id, session_id, title, prompt, source_kind, source_ref, "queued", stamp),
        )
        task_id = cursor.lastrowid
    _wake.set()
    return get(task_id)


def get(task_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM background_tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else {}


def list_for_project(project_id: int) -> list[dict]:
    with connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM background_tasks WHERE project_id=? ORDER BY id DESC LIMIT 100", (project_id,))]


def cancel(task_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT status FROM background_tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return {}
        if row["status"] == "queued":
            conn.execute("UPDATE background_tasks SET status='cancelled',cancel_requested=1,completed_at=? WHERE id=?", (now(), task_id))
        elif row["status"] == "running":
            conn.execute("UPDATE background_tasks SET cancel_requested=1 WHERE id=?", (task_id,))
    return get(task_id)


def run_once() -> bool:
    handler = _handler
    if handler is None:
        return False
    with connect() as conn:
        row = conn.execute("SELECT * FROM background_tasks WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return False
        task = dict(row)
        cursor = conn.execute("UPDATE background_tasks SET status='running',started_at=? WHERE id=? AND status='queued'", (now(), task["id"]))
        if cursor.rowcount != 1:
            return True
    try:
        result = handler(task)
        with connect() as conn:
            current = conn.execute("SELECT cancel_requested FROM background_tasks WHERE id=?", (task["id"],)).fetchone()
            final_status = "cancelled" if current and current["cancel_requested"] else "completed"
            conn.execute("UPDATE background_tasks SET status=?,result=?,completed_at=? WHERE id=?", (final_status, result, now(), task["id"]))
    except Exception as exc:
        with connect() as conn:
            conn.execute("UPDATE background_tasks SET status='failed',error=?,completed_at=? WHERE id=?", (str(exc)[:20_000], now(), task["id"]))
    return True


def _worker() -> None:
    while not _stop.is_set():
        if run_once():
            continue
        _wake.wait(1)
        _wake.clear()
