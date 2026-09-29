from __future__ import annotations

import json
import threading
from pathlib import Path
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
        if any(thread.is_alive() for thread in alive):
            raise RuntimeError("Previous task workers have not stopped")
        _stop.clear()
        _wake.clear()
        with connect() as conn:
            conn.execute("UPDATE background_tasks SET status='cancelled',completed_at=? WHERE status='running' AND cancel_requested=1", (now(),))
            conn.execute("UPDATE background_tasks SET status='interrupted',error='Application restarted; inspect completed work before continuing' WHERE status IN ('running','waiting_for_approval','waiting_for_input')")
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
    _threads = [thread for thread in _threads if thread.is_alive()]


def enqueue(
    project_id: int,
    session_id: int,
    title: str,
    prompt: str,
    source_kind: str = "manual",
    source_ref: str = "",
    parent_task_id: int | None = None,
    depends_on: list[int] | None = None,
    agent_role: str = "worker",
    *,
    swarm_id: int | None = None,
    model_profile_id: int | None = None,
    assigned_model: str = "",
    task_kind: str = "specialist",
    priority: int = 100,
    depth: int = 0,
) -> dict:
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
        if swarm_id is not None:
            swarm = conn.execute("SELECT id,project_id,status,max_agents,total_agents_created FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
            if not swarm or int(swarm["project_id"]) != project_id:
                raise ValueError("Swarm must exist in the same project")
            if swarm["status"] in {"completed", "failed", "cancelled"}:
                raise ValueError("Cannot add tasks to a finished swarm")
            if int(swarm["total_agents_created"] or 0) >= int(swarm["max_agents"] or 1):
                raise ValueError("Swarm has reached its maximum agent count")
        cursor = conn.execute(
            "INSERT INTO background_tasks(project_id,session_id,title,prompt,source_kind,source_ref,status,parent_task_id,depends_on,agent_role,swarm_id,model_profile_id,assigned_model,task_kind,priority,depth,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                project_id, session_id, title, prompt, source_kind, source_ref, "queued",
                parent_task_id, json.dumps(dependency_ids), agent_role or "worker", swarm_id,
                model_profile_id, assigned_model, task_kind or "specialist", int(priority), int(depth), stamp,
            ),
        )
        if swarm_id is not None:
            conn.execute("UPDATE swarm_runs SET total_agents_created=total_agents_created+1 WHERE id=?", (swarm_id,))
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
    try:
        result["blocking_dependency_ids"] = json.loads(result.get("blocking_dependency_ids") or "[]")
    except (TypeError, json.JSONDecodeError):
        result["blocking_dependency_ids"] = []
    return result


def list_for_project(project_id: int) -> list[dict]:
    with connect() as conn:
        result = [dict(row) for row in conn.execute("SELECT * FROM background_tasks WHERE project_id=? ORDER BY id DESC LIMIT 100", (project_id,))]
    for item in result:
        try:
            item["depends_on"] = json.loads(item.get("depends_on") or "[]")
        except json.JSONDecodeError:
            item["depends_on"] = []
        try:
            item["blocking_dependency_ids"] = json.loads(item.get("blocking_dependency_ids") or "[]")
        except (TypeError, json.JSONDecodeError):
            item["blocking_dependency_ids"] = []
        item["recovery"] = None
        if item.get("status") in {"budget_exhausted", "interrupted", "no_progress", "incomplete", "failed"}:
            try:
                item["recovery"] = recovery_info(int(item["id"]))
            except Exception:
                item["recovery"] = None
    return result


def cancel(task_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT status FROM background_tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return {}
        if row["status"] == "queued":
            conn.execute("UPDATE background_tasks SET status='cancelled',cancel_requested=1,completed_at=? WHERE id=?", (now(), task_id))
        elif row["status"] in {"running", "waiting_for_approval", "waiting_for_input"}:
            conn.execute("UPDATE background_tasks SET cancel_requested=1 WHERE id=?", (task_id,))
    _wake.set()
    return get(task_id)


def recovery_info(task_id: int) -> dict:
    task = get(task_id)
    if not task:
        raise ValueError("Background task not found")
    with connect() as conn:
        active = conn.execute(
            "SELECT id,status FROM agent_runs WHERE task_id=? AND status IN ('running','waiting_for_approval','waiting_for_input') ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        prior = conn.execute(
            "SELECT * FROM agent_runs WHERE task_id=? AND status IN ('budget_exhausted','interrupted','failed','cancelled','no_progress') ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        profile = conn.execute(
            "SELECT sp.agent_tool_budget,sp.resumed_task_tool_budget,sp.max_recovery_attempts "
            "FROM background_tasks bt LEFT JOIN swarm_runs sr ON sr.id=bt.swarm_id "
            "LEFT JOIN swarm_profiles sp ON sp.id=sr.profile_id WHERE bt.id=?",
            (task_id,),
        ).fetchone()
    checkpoint = str(prior["checkpoint"] or "") if prior else ""
    worktree_path = str(task.get("worktree_path") or "")
    worktree_branch = str(task.get("worktree_branch") or "")
    worktree_available = bool(worktree_path and Path(worktree_path).is_dir())
    branch_available = False
    if worktree_branch:
        try:
            project = _project_for_task(task)
            from . import worktrees
            code, _ = worktrees._git(Path(project["path"]).expanduser().resolve(), "show-ref", "--verify", "--quiet", f"refs/heads/{worktree_branch}")
            branch_available = code == 0
        except Exception:
            branch_available = False
    blocking = task.get("blocking_dependency_ids") or []
    if not isinstance(blocking, list):
        try:
            blocking = json.loads(blocking or "[]")
        except (TypeError, json.JSONDecodeError):
            blocking = []
    return {
        "task_id": task_id,
        "status": task.get("status"),
        "session_id": int(task.get("session_id") or 0),
        "active_run_id": int(active["id"]) if active else 0,
        "active_run_status": str(active["status"]) if active else "",
        "prior_run_id": int(prior["id"]) if prior else 0,
        "prior_run_status": str(prior["status"]) if prior else "",
        "checkpoint_available": bool(checkpoint and checkpoint not in {"[]", "null"}),
        "checkpoint_bytes": len(checkpoint.encode("utf-8")) if checkpoint else 0,
        "worktree_path": worktree_path,
        "worktree_branch": worktree_branch,
        "worktree_available": worktree_available,
        "branch_available": branch_available,
        "previous_budget": int(task.get("budget_override") or 0) or (int(profile["agent_tool_budget"] or 0) if profile else 0),
        "resumed_budget": int(profile["resumed_task_tool_budget"] or 20) if profile else 20,
        "max_recovery_attempts": int(profile["max_recovery_attempts"] or 2) if profile else 2,
        "recovery_attempt": int(task.get("recovery_attempt") or 0),
        "blocking_dependency_ids": [int(item) for item in blocking],
        "can_resume": (
            not active
            and task.get("status") in {"budget_exhausted", "interrupted", "no_progress", "incomplete", "failed"}
            and bool(prior)
            and bool(checkpoint and checkpoint not in {"[]", "null"})
            and (worktree_available or branch_available)
        ),
    }


def _recovery_context(task: dict, prior_run: dict, summary: dict, fresh_budget: int) -> str:
    dependency_context = _dependency_context(task)
    return (
        "Continue the existing task from its saved checkpoint and worktree. Inspect saved changes and uncertain command "
        "outcomes before editing. Do not restart or discard completed work. Do not claim completion until the task's "
        "acceptance criteria are supported by evidence.\n\n"
        f"Original task: {task.get('title') or ''}\n"
        f"Original objective and acceptance criteria:\n{task.get('prompt') or ''}\n\n"
        f"Prior result:\n{task.get('result') or 'No prior final result.'}\n\n"
        f"Prior stop reason:\n{task.get('error') or prior_run.get('status') or 'Unknown'}\n\n"
        f"Recovery budget: {fresh_budget} tool steps\n"
        f"Checkpoint source run: #{prior_run.get('id')}\n"
        f"Worktree: {task.get('worktree_path') or ''}\n"
        f"Branch: {task.get('worktree_branch') or ''}\n"
        f"Starting HEAD: {summary.get('head') or ''}\n"
        f"Uncommitted status: {json.dumps(summary.get('changes') or [])}\n"
        + (f"\n{dependency_context}\n" if dependency_context else "")
        + "\nExplicit remaining work: inspect the saved checkpoint, current worktree, prior command outcomes and acceptance criteria; "
        "finish only the work that remains, run relevant checks, and provide evidence for completion."
    )


def resume_task(
    task_id: int,
    *,
    fresh_budget: int | None = None,
    allow_failed: bool = False,
    recreate_missing_worktree: bool = False,
) -> dict:
    from . import conversation_runtime, worktrees
    task = get(task_id)
    if not task:
        raise ValueError("Background task not found")
    allowed = {"budget_exhausted", "interrupted", "no_progress", "incomplete"}
    if allow_failed:
        allowed.add("failed")
    if task.get("status") not in allowed:
        raise ValueError(f"Task status '{task.get('status')}' is not resumable")

    with connect() as conn:
        active = conn.execute(
            "SELECT id,status FROM agent_runs WHERE task_id=? AND status IN ('running','waiting_for_approval','waiting_for_input') ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        if active:
            raise ValueError(f"Task already has an active run #{active['id']} ({active['status']})")
        prior = conn.execute(
            "SELECT * FROM agent_runs WHERE task_id=? AND status IN ('budget_exhausted','interrupted','failed','cancelled','no_progress') ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        profile = conn.execute(
            "SELECT sp.agent_tool_budget,sp.resumed_task_tool_budget,sp.max_recovery_attempts "
            "FROM background_tasks bt LEFT JOIN swarm_runs sr ON sr.id=bt.swarm_id "
            "LEFT JOIN swarm_profiles sp ON sp.id=sr.profile_id WHERE bt.id=?",
            (task_id,),
        ).fetchone()
    if not prior:
        raise ValueError("No resumable prior run exists for this task")
    prior = dict(prior)
    checkpoint = str(prior.get("checkpoint") or "")
    if not checkpoint or checkpoint in {"[]", "null"}:
        raise ValueError("The most recent stopped run has no saved checkpoint")

    project = _project_for_task(task)
    worktree_path = str(task.get("worktree_path") or "")
    branch = str(task.get("worktree_branch") or "")
    if not branch:
        raise ValueError("The original task branch is unavailable")
    if not worktree_path or not Path(worktree_path).is_dir():
        root = Path(project["path"]).expanduser().resolve()
        code, _ = worktrees._git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
        if code != 0:
            raise ValueError("Both the original worktree and task branch are unavailable; automatic recovery is unsafe")
        if not recreate_missing_worktree:
            raise ValueError("The original worktree is missing but its branch still exists; retry with worktree recreation explicitly enabled")
        recreated = worktrees.create_for_task(project, task_id)
        if recreated["branch"] != branch:
            raise ValueError("Recreated worktree did not attach to the original task branch")
        set_worktree(task_id, recreated["path"], recreated["branch"])
        task = get(task_id)
        worktree_path = recreated["path"]

    summary = worktrees.summary(project, worktree_path)
    if summary.get("branch") != branch:
        raise ValueError(f"Recovery worktree is on '{summary.get('branch')}', expected '{branch}'")

    current_attempt = int(task.get("recovery_attempt") or 0)
    max_attempts = int(profile["max_recovery_attempts"] or 2) if profile else 2
    attempt = current_attempt + 1
    if attempt > max_attempts:
        raise ValueError(f"Task has reached the maximum recovery attempts ({max_attempts})")
    default_budget = int(profile["resumed_task_tool_budget"] or 20) if profile else 20
    budget = max(1, min(int(fresh_budget or default_budget), 200))
    starting_diff = json.dumps(
        {
            "branch_diff": summary.get("branch_diff") or "",
            "working_diff": summary.get("working_diff") or "",
            "changes": summary.get("changes") or [],
        },
        default=str,
    )[:500000]
    try:
        lineage = task.get("retry_lineage") or []
        if not isinstance(lineage, list):
            lineage = json.loads(lineage or "[]")
    except (TypeError, json.JSONDecodeError):
        lineage = []
    lineage = [*lineage, int(prior["id"])]

    previous = {
        "budget_override": int(task.get("budget_override") or 0),
        "recovery_attempt": current_attempt,
        "retry_lineage": task.get("retry_lineage") if isinstance(task.get("retry_lineage"), str) else json.dumps(task.get("retry_lineage") or []),
    }
    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET budget_override=?,recovery_attempt=?,retry_lineage=?,no_progress_reason='',error='',completed_at='',current_activity=? WHERE id=?",
            (budget, attempt, json.dumps(lineage), f"Recovery attempt {attempt}: restoring checkpoint from run #{prior['id']}", task_id),
        )

    content = _recovery_context(get(task_id), prior, summary, budget)
    try:
        run = conversation_runtime.launch(
            int(task["session_id"]),
            content,
            resume_id=int(prior["id"]),
            recovery_metadata={
                "recovery_attempt": attempt,
                "starting_head": summary.get("head") or "",
                "starting_diff": starting_diff,
                "fresh_budget": budget,
            },
        )
    except Exception:
        with connect() as conn:
            conn.execute(
                "UPDATE background_tasks SET budget_override=?,recovery_attempt=?,retry_lineage=? WHERE id=?",
                (previous["budget_override"], previous["recovery_attempt"], previous["retry_lineage"], task_id),
            )
        raise

    with connect() as conn:
        if task.get("parent_task_id"):
            conn.execute(
                "UPDATE background_tasks SET status='recovering',error='' WHERE id=? AND status IN ('coordinating','recovery_available','failed')",
                (task["parent_task_id"],),
            )
        if task.get("swarm_id"):
            conn.execute(
                "UPDATE swarm_runs SET status='recovering',completed_at='' WHERE id=? AND status NOT IN ('completed','cancelled')",
                (task["swarm_id"],),
            )

    if task.get("swarm_id"):
        try:
            from . import swarm
            swarm.emit_coordinator_event(
                int(task["swarm_id"]),
                "recovery_run_started",
                {
                    "task_id": task_id,
                    "prior_run_id": int(prior["id"]),
                    "run_id": int(run["id"]),
                    "recovery_attempt": attempt,
                    "budget": budget,
                    "worktree": worktree_path,
                    "branch": branch,
                    "checkpoint_bytes": len(checkpoint.encode("utf-8")),
                },
            )
        except Exception:
            pass
    return {
        "task_id": task_id,
        "session_id": int(task["session_id"]),
        "prior_run_id": int(prior["id"]),
        "run_id": int(run["id"]),
        "status": run["status"],
        "checkpoint_restored": True,
        "checkpoint_bytes": len(checkpoint.encode("utf-8")),
        "recovery_attempt": attempt,
        "fresh_budget": budget,
        "worktree_path": worktree_path,
        "worktree_branch": branch,
        "starting_head": summary.get("head") or "",
        "dirty_work_preserved": bool(summary.get("changes")),
    }


def blocked_descendants(task_id: int) -> list[dict]:
    with connect() as conn:
        tasks = [dict(row) for row in conn.execute(
            "SELECT * FROM background_tasks WHERE project_id=(SELECT project_id FROM background_tasks WHERE id=?) ORDER BY id",
            (task_id,),
        )]
    descendants: list[dict] = []
    frontier = {int(task_id)}
    seen: set[int] = set()
    while frontier:
        next_frontier: set[int] = set()
        for item in tasks:
            item_id = int(item["id"])
            if item_id in seen or item["status"] != "dependency_failed":
                continue
            deps = _dependency_ids(item)
            if any(dep in frontier for dep in deps):
                try:
                    blockers = json.loads(item.get("blocking_dependency_ids") or "[]")
                except (TypeError, json.JSONDecodeError):
                    blockers = []
                item["depends_on"] = deps
                item["blocking_dependency_ids"] = [int(value) for value in blockers]
                descendants.append(item)
                seen.add(item_id)
                next_frontier.add(item_id)
        frontier = next_frontier
    return descendants


def retry_blocked_dependants(task_id: int, *, full_chain: bool = True) -> dict:
    root = get(task_id)
    if not root:
        raise ValueError("Background task not found")
    if root.get("status") != "completed":
        raise ValueError("The recovered task must complete successfully before blocked dependants can be retried")
    descendants = blocked_descendants(task_id)
    if not full_chain:
        descendants = [item for item in descendants if task_id in _dependency_ids(item)]
    reset: list[int] = []
    with connect() as conn:
        for item in descendants:
            conn.execute(
                "UPDATE background_tasks SET status='queued',error='',blocking_dependency_ids='[]',completed_at='',cancel_requested=0,current_activity='Retry queued after dependency recovery' WHERE id=? AND status='dependency_failed'",
                (item["id"],),
            )
            reset.append(int(item["id"]))
        parent_id = root.get("parent_task_id")
        if parent_id and reset:
            conn.execute("UPDATE background_tasks SET status='recovering',error='' WHERE id=?", (parent_id,))
        if root.get("swarm_id") and reset:
            conn.execute("UPDATE swarm_runs SET status='recovering',completed_at='' WHERE id=?", (root["swarm_id"],))
    if reset:
        _wake.set()
    return {"task_id": task_id, "retried_task_ids": reset, "full_chain": full_chain}


def current_task() -> dict:
    task_id = current_task_id()
    if not task_id:
        return {}
    try:
        return get(task_id)
    except Exception:
        # Tool-level helpers may run in isolated unit tests or before database
        # initialization. Absence of task metadata must not break normal tools.
        return {}


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


def set_progress(task_id: int, progress: int, current_activity: str = "") -> None:
    value = max(0, min(int(progress), 100))
    with connect() as conn:
        if not conn.execute("SELECT id FROM background_tasks WHERE id=?", (task_id,)).fetchone():
            raise ValueError("Background task not found")
        conn.execute(
            "UPDATE background_tasks SET progress=?,current_activity=? WHERE id=?",
            (value, str(current_activity or "")[:1000], task_id),
        )


def current_worktree_path() -> str:
    task_id = current_task_id()
    if not task_id:
        return ""
    task = get(task_id)
    return task.get("worktree_path", "") if task else ""


def current_assigned_model() -> str:
    task_id = current_task_id()
    if not task_id:
        return ""
    task = get(task_id)
    return str(task.get("assigned_model") or "") if task else ""


def current_swarm_id() -> int | None:
    task_id = current_task_id()
    if not task_id:
        return None
    task = get(task_id)
    return int(task["swarm_id"]) if task and task.get("swarm_id") else None


def current_model_settings() -> dict:
    task_id = current_task_id()
    if not task_id:
        return {}
    with connect() as conn:
        row = conn.execute(
            "SELECT mp.chat_model,mp.embedding_model,mp.temperature,mp.max_steps,mp.context_files,mp.context_chars,mp.context_tokens,"
            "sp.agent_tool_budget,bt.budget_extra,bt.budget_override "
            "FROM background_tasks bt "
            "LEFT JOIN model_profiles mp ON mp.id=bt.model_profile_id "
            "LEFT JOIN swarm_runs sr ON sr.id=bt.swarm_id "
            "LEFT JOIN swarm_profiles sp ON sp.id=sr.profile_id "
            "WHERE bt.id=?",
            (task_id,),
        ).fetchone()
    if not row:
        return {}
    result = dict(row)
    base_budget = int(result.get("agent_tool_budget") or 0)
    override = int(result.get("budget_override") or 0)
    result["agent_tool_budget"] = override if override > 0 else base_budget + int(result.get("budget_extra") or 0)
    return result


def _dependency_ids(task: dict) -> list[int]:
    value = task.get("depends_on") or []
    if isinstance(value, list):
        return [int(item) for item in value if int(item) > 0]
    try:
        return [int(item) for item in json.loads(value or "[]") if int(item) > 0]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _dependency_state(conn, task: dict) -> tuple[bool, str, list[int]]:
    dependency_ids = _dependency_ids(task)
    if not dependency_ids:
        return True, "", []
    placeholders = ",".join("?" for _ in dependency_ids)
    states = {row["id"]: row["status"] for row in conn.execute(f"SELECT id,status FROM background_tasks WHERE id IN ({placeholders})", dependency_ids)}
    missing = [item for item in dependency_ids if item not in states]
    if missing:
        return False, f"Missing dependency tasks: {missing}", missing
    blocked_statuses = {"failed", "cancelled", "budget_exhausted", "interrupted", "dependency_failed", "no_progress", "incomplete"}
    blocked = [item for item, status in states.items() if status in blocked_statuses]
    if blocked:
        return False, f"Blocked by dependency task(s): {blocked}", blocked
    return all(states[item] == "completed" for item in dependency_ids), "", []


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


def _dependency_branches(task: dict) -> list[str]:
    dependency_ids = _dependency_ids(task)
    if not dependency_ids:
        return []
    placeholders = ",".join("?" for _ in dependency_ids)
    with connect() as conn:
        rows = [dict(row) for row in conn.execute(
            f"SELECT id,status,worktree_branch FROM background_tasks WHERE id IN ({placeholders}) ORDER BY id",
            dependency_ids,
        )]
    by_id = {int(row["id"]): row for row in rows}
    branches: list[str] = []
    for dependency_id in dependency_ids:
        item = by_id.get(dependency_id)
        if not item or item.get("status") != "completed":
            raise ValueError(f"Dependency task #{dependency_id} is not ready for workspace hand-off")
        branch = str(item.get("worktree_branch") or "").strip()
        if not branch:
            raise ValueError(f"Dependency task #{dependency_id} has no isolated task branch to inherit")
        if branch not in branches:
            branches.append(branch)
    return branches


def _claim_next() -> dict | None:
    with connect() as conn:
        candidates = [dict(row) for row in conn.execute("SELECT * FROM background_tasks WHERE status='queued' ORDER BY priority ASC,id ASC LIMIT 100")]
        for task in candidates:
            swarm_id = task.get("swarm_id")
            if swarm_id:
                swarm = conn.execute("SELECT status,max_concurrency,cancel_requested FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
                if not swarm:
                    conn.execute("UPDATE background_tasks SET status='failed',error=?,completed_at=? WHERE id=? AND status='queued'", ("Swarm no longer exists", now(), task["id"]))
                    continue
                if swarm["cancel_requested"] or swarm["status"] == "cancelled":
                    conn.execute("UPDATE background_tasks SET status='cancelled',cancel_requested=1,completed_at=? WHERE id=? AND status='queued'", (now(), task["id"]))
                    continue
                if swarm["status"] in {"completed", "failed"}:
                    conn.execute(
                        "UPDATE background_tasks SET status='cancelled',error=?,completed_at=? WHERE id=? AND status='queued'",
                        ("Swarm already finished", now(), task["id"]),
                    )
                    continue
                if swarm["status"] in {"paused", "planning", "ready_for_integration", "integrating", "checks_failed", "ready_to_promote"}:
                    continue
                if task.get("task_kind") in {"reviewer", "challenger"} and swarm["status"] != "reviewing":
                    continue
                active = conn.execute(
                    "SELECT COUNT(*) FROM background_tasks WHERE swarm_id=? AND status IN ('running','waiting_for_approval','waiting_for_input')",
                    (swarm_id,),
                ).fetchone()[0]
                if int(active) >= max(1, int(swarm["max_concurrency"] or 1)):
                    continue
            ready, blocked_reason, blocking_ids = _dependency_state(conn, task)
            if blocked_reason:
                conn.execute(
                    "UPDATE background_tasks SET status='dependency_failed',error=?,blocking_dependency_ids=?,completed_at=? WHERE id=? AND status='queued'",
                    (blocked_reason, json.dumps(blocking_ids), now(), task["id"]),
                )
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


def _project_for_task(task: dict) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (task["project_id"],)).fetchone()
    if not row:
        raise ValueError("Project not found")
    return dict(row)


def _prepare_isolation(task: dict) -> threading.Lock | None:
    from . import worktrees
    project = _project_for_task(task)
    dependency_ids = _dependency_ids(task)
    strict_isolation = (
        task.get("source_kind") == "lead_specialist"
        or str(task.get("source_kind") or "").startswith("swarm_")
        or (bool(dependency_ids) and task.get("source_kind") != "lead_consolidation")
    )
    try:
        isolated = worktrees.create_for_task(project, task["id"])
        set_worktree(task["id"], isolated["path"], isolated["branch"])
        task["worktree_path"] = isolated["path"]
        task["worktree_branch"] = isolated["branch"]
        if dependency_ids and task.get("source_kind") != "lead_consolidation":
            worktrees.inherit_branches(project, isolated["path"], _dependency_branches(task))
        return None
    except ValueError:
        if strict_isolation:
            raise
        with _lock:
            fallback = _fallback_project_locks.setdefault(task["project_id"], threading.Lock())
        fallback.acquire()
        return fallback


def _auto_commit_specialist(task: dict) -> str:
    if task.get("task_kind") in {"reviewer", "challenger"}:
        return ""
    if (
        task.get("source_kind") != "lead_specialist"
        and not str(task.get("source_kind") or "").startswith("swarm_")
    ) or not task.get("worktree_path"):
        return ""
    from . import worktrees
    project = _project_for_task(task)
    summary = worktrees.summary(project, task["worktree_path"])
    if not summary.get("changes"):
        return ""
    committed = worktrees.commit_all(project, task["worktree_path"], f"Olladex task #{task['id']}: {task['title']}")
    return str(committed.get("sha") or "")


def _finalize_swarm(task: dict, final_status: str, result: str = "", error: str = "") -> None:
    swarm_id = task.get("swarm_id")
    if not swarm_id or (task.get("agent_role") or "") != "reviewer":
        return
    if final_status == "completed":
        # Reviewer completion is evidence for the Coordinator finalization gate.
        # It must never mark the Swarm complete by itself.
        return
    with connect() as conn:
        swarm = conn.execute("SELECT status FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
        if not swarm or swarm["status"] in {"completed", "failed", "cancelled"}:
            return
        conn.execute(
            "UPDATE swarm_runs SET status='failed',completed_at=? WHERE id=?",
            (now(), swarm_id),
        )


def _mark_recovery_available(task: dict, reason: str) -> None:
    with connect() as conn:
        if task.get("parent_task_id"):
            conn.execute(
                "UPDATE background_tasks SET status='recovery_available',error=?,completed_at='' "
                "WHERE id=? AND status NOT IN ('completed','cancelled')",
                (reason[:20000], task["parent_task_id"]),
            )
        if task.get("swarm_id"):
            conn.execute(
                "UPDATE swarm_runs SET status='recovery_available',completed_at='' "
                "WHERE id=? AND status NOT IN ('completed','cancelled')",
                (task["swarm_id"],),
            )


def _finalize_parent(task: dict, final_status: str, result: str = "", error: str = "") -> None:
    parent_id = task.get("parent_task_id")
    if not parent_id or (task.get("agent_role") or "") != "reviewer":
        return
    with connect() as conn:
        parent = conn.execute("SELECT status FROM background_tasks WHERE id=?", (parent_id,)).fetchone()
        if not parent or parent["status"] not in {"coordinating", "queued", "recovering", "recovery_available"}:
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
        if final_status == "completed":
            commit_sha = _auto_commit_specialist(task)
            if commit_sha:
                result = f"{result}\n\nTask branch auto-committed as {commit_sha[:12]}."
        with connect() as conn:
            conn.execute("UPDATE background_tasks SET status=?,result=?,progress=?,current_activity=?,completed_at=? WHERE id=?", (final_status, result, 100 if final_status == "completed" else int(task.get("progress") or 0), "Completed" if final_status == "completed" else str(task.get("current_activity") or ""), now(), task["id"]))
        _finalize_parent(task, final_status, result=result, error="Lead consolidation task was cancelled")
        _finalize_swarm(task, final_status, result=result, error="Swarm reviewer was cancelled")
    except Exception as exc:
        from .ollama import AgentCancelled
        with connect() as conn:
            current = conn.execute("SELECT cancel_requested FROM background_tasks WHERE id=?", (task["id"],)).fetchone()
            if (current and current["cancel_requested"]) or isinstance(exc, AgentCancelled):
                conn.execute("UPDATE background_tasks SET status='cancelled',error='',completed_at=? WHERE id=?", (now(), task["id"]))
                final_status = "cancelled"
                error = "Lead consolidation task was cancelled"
            else:
                from .ollama import BudgetExhausted
                error = str(exc)[:20000]
                if isinstance(exc, BudgetExhausted):
                    conn.execute(
                        "UPDATE background_tasks SET status='budget_exhausted',error=?,completed_at=? WHERE id=?",
                        (error, now(), task["id"]),
                    )
                    final_status = "budget_exhausted"
                else:
                    conn.execute(
                        "UPDATE background_tasks SET status='failed',error=?,completed_at=? WHERE id=?",
                        (error, now(), task["id"]),
                    )
                    final_status = "failed"
        if final_status == "budget_exhausted":
            _mark_recovery_available(task, error or "A child task exhausted its budget and can be resumed")
        _finalize_parent(task, final_status, error=error)
        _finalize_swarm(task, final_status, error=error)
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
