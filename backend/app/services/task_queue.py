from __future__ import annotations

import json
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
        _threads = [threading.Thread(target=_worker, name=f"olladex-task-worker-{index + 1}", daemon=True) for index in range(_worker_count())]
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


def enqueue(project_id: int, session_id: int, title: str, prompt: str, source_kind: str = "manual", source_ref: str = "", parent_task_id: int | None = None, depends_on: list[int] | None = None, agent_role: str = "worker") -> dict:
    stamp = now()
    dependency_ids = [int(item) for item in (depends_on or []) if int(item) > 0]
    with connect() as conn:
        if parent_task_id is not None:
            parent = conn.execute("SELECT id,project_id FROM background_tasks WHERE id=?", (parent_task_id,)).fetchone()
            if not parent or parent["project_id"] != project_id:
                raise ValueError("Parent task must exist in the same project")
        for dependency_id in dependency_ids:
            dependency = conn.execute("SELECT id,project_id FROM background_tasks WHERE id=?", (dependency_id,)).fetchone()
            if not dependency or dependency["project_id"] != project_id:
                raise ValueError(f"Dependency task #{dependency_id} must exist in the same project")
        cursor = conn.execute(
            "INSERT INTO background_tasks(project_id,session_id,title,prompt,source_kind,source_ref,status,parent_task_id,depends_on,agent_role,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, session_id, title, prompt, source_kind, source_ref, "queued", parent_task_id, json.dumps(dependency_ids), agent_role or "worker", stamp),
        )
        task_id = cursor.lastrowid
    _wake.set()
    return get(task_id)


def get(task_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM background_tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        return {}
    result = dict(row)
    try:
        result["depends_on"] = json.loads(result.get("depends_on") or "[]")
    except json.JSONDecodeError:
        result["depends_on"] = []
    return result


def list_for_project(project_id: int) -> list[dict]:
    with connect() as conn:
        result = [dict(row) for row in conn.execute("SELECT * FROM background_tasks WHERE project_id=? ORDER BY id DESC LIMIT 100", (project_id,))]
    for item in result:
        try:
            item["depends_on"] = json.loads(item.get("depends_on") or "[]")
        except json.JSONDecodeError:
            item["depends_on"] = []
    return result


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
        conn.execute("UPDATE background_tasks SET worktree_path=?,worktree_branch=? WHERE id=?", (path, branch, task_id))


def current_worktree_path() -> str:
    task_id = current_task_id()
    if not task_id:
        return ""
    task = get(task_id)
    return task.get("worktree_path", "") if task else ""


def _dependency_ids(task: dict) -> list[int]:
    value = task.get("depends_on") or []
    if isinstance(value, list):
        return [int(item) for item in value if int(item) > 0]
    try:
        return [int(item) for item in json.loads(value or "[]") if int(item) > 0]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _dependency_state(conn, task: dict) -> tuple[bool, str]:
    dependency_ids = _dependency_ids(task)
    if not dependency_ids:
        return True, ""
    placeholders = ",".join("?" for _ in dependency_ids)
    states = {row["id"]: row["status"] for row in conn.execute(f"SELECT id,status FROM background_tasks WHERE id IN ({placeholders})", dependency_ids)}
    missing = [item for item in dependency_ids if item not in states]
    if missing:
        return False, f"Missing dependency tasks: {missing}"
    failed = [item for item, status in states.items() if status in {"failed", "cancelled"}]
    if failed:
        return False, f"Dependency task(s) did not complete successfully: {failed}"
    return all(states[item] == "completed" for item in dependency_ids), ""


def _dependency_context(task: dict) -> str:
    dependency_ids = _dependency_ids(task)
    if not dependency_ids:
        return ""
    placeholders = ",".join("?" for _ in dependency_ids)
    with connect() as conn:
        rows = [dict(row) for row in conn.execute(f"SELECT id,title,agent_role,status,result,error,worktree_branch,pull_request_number,pull_request_state FROM background_tasks WHERE id IN ({placeholders}) ORDER BY id", dependency_ids)]
    parts = ["Dependency hand-offs from completed specialist tasks:"]
    for item in rows:
        parts.append(
            f"\nTask #{item['id']} — {item['title']} ({item.get('agent_role') or 'worker'}, {item['status']})\n"
            f"Branch: {item.get('worktree_branch') or 'none'} | PR: {item.get('pull_request_number') or 'none'} {item.get('pull_request_state') or ''}\n"
            f"Result:\n{(item.get('result') or item.get('error') or 'No result')[:12000]}"
        )
    return "\n".join(parts)


def _claim_next() -> dict | None:
    with connect() as conn:
        candidates = [dict(row) for row in conn.execute("SELECT * FROM background_tasks WHERE status='queued' ORDER BY id LIMIT 100")]
        for task in candidates:
            ready, blocked_reason = _dependency_state(conn, task)
            if blocked_reason:
                conn.execute("UPDATE background_tasks SET status='failed',error=?,completed_at=? WHERE id=? AND status='queued'", (blocked_reason, now(), task["id"]))
                continue
            if not ready:
                continue
            cursor = conn.execute("UPDATE background_tasks SET status='running',started_at=? WHERE id=? AND status='queued'", (now(), task["id"]))
            if cursor.rowcount == 1:
                try:
                    task["depends_on"] = json.loads(task.get("depends_on") or "[]")
                except json.JSONDecodeError:
                    task["depends_on"] = []
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


def _finalize_parent(task: dict, final_status: str, result: str = "", error: str = "") -> None:
    parent_id = task.get("parent_task_id")
    if not parent_id or (task.get("agent_role") or "") != "reviewer":
        return
    with connect() as conn:
        parent = conn.execute("SELECT status FROM background_tasks WHERE id=?", (parent_id,)).fetchone()
        if not parent or parent["status"] not in {"coordinating", "queued"}:
            return
        if final_status == "completed":
            conn.execute("UPDATE background_tasks SET status='completed',result=?,completed_at=? WHERE id=?", (result, now(), parent_id))
        else:
            conn.execute("UPDATE background_tasks SET status='failed',error=?,completed_at=? WHERE id=?", (error or "Lead consolidation task failed", now(), parent_id))


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
            _finalize_parent(task, "cancelled", error="Lead consolidation task was cancelled")
            return True
        dependency_context = _dependency_context(task)
        if dependency_context:
            task["prompt"] = f"{task['prompt']}\n\n{dependency_context}"
        result = handler(task)
        with connect() as conn:
            current = conn.execute("SELECT cancel_requested FROM background_tasks WHERE id=?", (task["id"],)).fetchone()
            final_status = "cancelled" if current and current["cancel_requested"] else "completed"
            conn.execute("UPDATE background_tasks SET status=?,result=?,completed_at=? WHERE id=?", (final_status, result, now(), task["id"]))
        _finalize_parent(task, final_status, result=result, error="Lead consolidation task was cancelled")
    except Exception as exc:
        with connect() as conn:
            current = conn.execute("SELECT cancel_requested FROM background_tasks WHERE id=?", (task["id"],)).fetchone()
            if current and current["cancel_requested"]:
                conn.execute("UPDATE background_tasks SET status='cancelled',error='',completed_at=? WHERE id=?", (now(), task["id"]))
                final_status = "cancelled"
                error = "Lead consolidation task was cancelled"
            else:
                error = str(exc)[:20000]
                conn.execute("UPDATE background_tasks SET status='failed',error=?,completed_at=? WHERE id=?", (error, now(), task["id"]))
                final_status = "failed"
        _finalize_parent(task, final_status, error=error)
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
