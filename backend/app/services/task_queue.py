from __future__ import annotations

import threading
from collections.abc import Callable

from ..config import settings
from ..database import connect, now


TaskHandler = Callable[[dict], str]
_handler: TaskHandler | None = None
_threads: list[threading.Thread] = []
_stop = threading.Event()
_wake = threading.Event()
_lock = threading.Lock()
_local = threading.local()
_fallback_project_locks: dict[int, threading.Lock] = {}


def _worker_count() -> int:
    return max(1, min(int(settings.task_workers or 1), 8))


def start(handler: TaskHandler) -> None:
    global _handler, _threads
    with _lock:
        _handler = handler
        alive = [thread for thread in _threads if thread.is_alive()]
        if len(alive) == _worker_count():
            _threads = alive
            return
        _stop.set()
        _wake.set()
        for thread in alive:
            thread.join(timeout=2)
        _stop.clear()
        _wake.clear()
        with connect() as conn:
            conn.execute("UPDATE background_tasks SET status='cancelled',completed_at=? WHERE status='running' AND cancel_requested=1", (now(),))
            conn.execute("UPDATE background_tasks SET status='queued',started_at='' WHERE status='running'")
        _threads = [
            threading.Thread(target=_worker, name=f"olladex-task-worker-{index + 1}", daemon=True)
            for index in range(_worker_count())
        ]
        for thread in _threads:
            thread.start()


def stop() -> None:
    global _threads
    _stop.set()
    _wake.set()
    for thread in _threads:
        if thread.is_alive():
            thread.join(timeout=2)
    _threads = []


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
    _wake.set()
    return get(task_id)


def current_task_id() -> int | None:
    return getattr(_local, "task_id", None)


def cancel_requested() -> bool:
    task_id = current_task_id()
    if not task_id:
        return False
    with connect() as conn:
        row = conn.execute("SELECT cancel_requested,status FROM background_tasks WHERE id=?", (task_id,)).fetchone()
    return bool(row and (row["cancel_requested"] or row["status"] == "cancelled"))


def set_worktree(task_id: int, path: str, branch: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET worktree_path=?,worktree_branch=? WHERE id=?",
            (path, branch, task_id),
        )


def current_worktree_path() -> str:
    task_id = current_task_id()
    if not task_id:
        return ""
    task = get(task_id)
    return task.get("worktree_path", "") if task else ""


def _claim_next() -> dict | None:
    with connect() as conn:
        candidates = [dict(row) for row in conn.execute("SELECT * FROM background_tasks WHERE status='queued' ORDER BY id LIMIT 50")]
        for task in candidates:
            cursor = conn.execute(
                "UPDATE background_tasks SET status='running',started_at=? WHERE id=? AND status='queued'",
                (now(), task["id"]),
            )
            if cursor.rowcount == 1:
                return task
    return None


def _prepare_isolation(task: dict) -> threading.Lock | None:
    from . import worktrees

    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (task["project_id"],)).fetchone()
    if not row:
        raise ValueError("Project not found")
    project = dict(row)
    try:
        isolated = worktrees.create_for_task(project, task["id"])
        set_worktree(task["id"], isolated["path"], isolated["branch"])
        task["worktree_path"] = isolated["path"]
        task["worktree_branch"] = isolated["branch"]
        return None
    except ValueError:
        with _lock:
            fallback = _fallback_project_locks.setdefault(task["project_id"], threading.Lock())
        fallback.acquire()
        return fallback


def run_once() -> bool:
    handler = _handler
    if handler is None:
        return False
    task = _claim_next()
    if not task:
        return False
    _local.task_id = task["id"]
    fallback_lock: threading.Lock | None = None
    try:
        fallback_lock = _prepare_isolation(task)
        if cancel_requested():
            with connect() as conn:
                conn.execute("UPDATE background_tasks SET status='cancelled',completed_at=? WHERE id=?", (now(), task["id"]))
            return True
        result = handler(task)
        with connect() as conn:
            current = conn.execute("SELECT cancel_requested FROM background_tasks WHERE id=?", (task["id"],)).fetchone()
            final_status = "cancelled" if current and current["cancel_requested"] else "completed"
            conn.execute("UPDATE background_tasks SET status=?,result=?,completed_at=? WHERE id=?", (final_status, result, now(), task["id"]))
    except Exception as exc:
        with connect() as conn:
            current = conn.execute("SELECT cancel_requested FROM background_tasks WHERE id=?", (task["id"],)).fetchone()
            if current and current["cancel_requested"]:
                conn.execute("UPDATE background_tasks SET status='cancelled',error='',completed_at=? WHERE id=?", (now(), task["id"]))
            else:
                conn.execute("UPDATE background_tasks SET status='failed',error=?,completed_at=? WHERE id=?", (str(exc)[:20_000], now(), task["id"]))
    finally:
        _local.task_id = None
        if fallback_lock:
            fallback_lock.release()
    return True


def _worker() -> None:
    while not _stop.is_set():
        if run_once():
            continue
        _wake.wait(0.5)
        _wake.clear()
