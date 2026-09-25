from __future__ import annotations

import json

from ..database import connect, now
from . import ollama, task_queue


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_TASK_STATUSES = {"queued", "running", "waiting_for_approval", "waiting_for_input"}


def skill_enabled(project_id: int) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT enabled FROM project_skills WHERE project_id=? AND skill='swarm'",
            (project_id,),
        ).fetchone()
    return bool(row and row["enabled"])


def set_skill(project_id: int, enabled: bool) -> dict:
    with connect() as conn:
        if not conn.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ValueError("Project not found")
        conn.execute(
            "INSERT INTO project_skills(project_id,skill,enabled) VALUES(?,?,?) "
            "ON CONFLICT(project_id,skill) DO UPDATE SET enabled=excluded.enabled",
            (project_id, "swarm", 1 if enabled else 0),
        )
    return {"project_id": project_id, "skill": "swarm", "enabled": bool(enabled)}


def list_profiles() -> list[dict]:
    with connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM swarm_profiles ORDER BY is_builtin DESC,name")]
    for item in rows:
        item["role_profiles"] = _json_object(item.get("role_profiles"))
    return rows


def get_profile(profile_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM swarm_profiles WHERE id=?", (profile_id,)).fetchone()
    if not row:
        raise ValueError("Swarm profile not found")
    result = dict(row)
    result["role_profiles"] = _json_object(result.get("role_profiles"))
    return result


def resolve_model_profile(model_profile_id: int | None) -> tuple[int | None, str]:
    if not model_profile_id:
        return None, ""
    with connect() as conn:
        row = conn.execute("SELECT id,chat_model FROM model_profiles WHERE id=?", (model_profile_id,)).fetchone()
    if not row:
        raise ValueError(f"Model profile #{model_profile_id} not found")
    return int(row["id"]), str(row["chat_model"] or "")


def resolve_role(profile: dict, role: str) -> tuple[int | None, str]:
    role_map = _json_object(profile.get("role_profiles"))
    selected = role_map.get(role)
    if selected is None:
        selected = profile.get("default_worker_profile_id")
    return resolve_model_profile(int(selected) if selected else None)


def coordinator_model(profile: dict) -> tuple[int | None, str]:
    selected = profile.get("coordinator_profile_id") or profile.get("default_worker_profile_id")
    return resolve_model_profile(int(selected) if selected else None)


def validate_models(profile: dict) -> dict:
    status = ollama.status()
    if not status.get("connected"):
        raise ValueError(status.get("error") or "Ollama server is unavailable")
    installed = set(status.get("models") or [])
    assignments: dict[str, str] = {}
    _, coordinator = coordinator_model(profile)
    if coordinator:
        assignments["coordinator"] = coordinator
    for role in ["architect", "researcher", "backend", "frontend", "coder", "tester", "reviewer", "challenger", "integrator", "documentation", "worker"]:
        _, model = resolve_role(profile, role)
        if model:
            assignments[role] = model
    missing = sorted({model for model in assignments.values() if model not in installed})
    if missing:
        raise ValueError("Required local Ollama model(s) are not installed: " + ", ".join(missing))
    return {"installed": sorted(installed), "assignments": assignments}


def create_run(
    project_id: int,
    session_id: int,
    title: str,
    objective: str,
    profile_id: int,
    *,
    max_agents: int | None = None,
    max_concurrency: int | None = None,
) -> dict:
    if not skill_enabled(project_id):
        raise ValueError("Swarm skill is disabled for this project")
    profile = get_profile(profile_id)
    validate_models(profile)
    max_agents_value = max(2, min(int(max_agents or profile["max_agents"]), 20))
    concurrency_value = max(1, min(int(max_concurrency or profile["max_concurrency"]), max_agents_value, 8))
    stamp = now()
    with connect() as conn:
        project = conn.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone()
        session = conn.execute("SELECT id FROM sessions WHERE id=? AND project_id=?", (session_id, project_id)).fetchone()
        if not project or not session:
            raise ValueError("Project or session not found")
        cursor = conn.execute(
            "INSERT INTO swarm_runs(project_id,session_id,title,objective,status,profile_id,max_agents,max_concurrency,created_at,started_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (project_id, session_id, title[:256], objective, "planning", profile_id, max_agents_value, concurrency_value, stamp, stamp),
        )
        swarm_id = int(cursor.lastrowid)
    return get_run(swarm_id)


def get_run(swarm_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
    if not row:
        raise ValueError("Swarm not found")
    result = dict(row)
    result["agents"] = list_agents(swarm_id)
    return result


def list_runs(project_id: int) -> list[dict]:
    with connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM swarm_runs WHERE project_id=? ORDER BY id DESC", (project_id,))]
    for item in rows:
        item["agent_counts"] = _agent_counts(item["id"])
    return rows


def list_agents(swarm_id: int) -> list[dict]:
    with connect() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT bt.*, ar.id AS run_id, ar.status AS run_status "
            "FROM background_tasks bt "
            "LEFT JOIN agent_runs ar ON ar.task_id=bt.id "
            "WHERE bt.swarm_id=? ORDER BY bt.priority ASC,bt.id ASC",
            (swarm_id,),
        )]
    return rows


def pause(swarm_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT status FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
        if not row:
            raise ValueError("Swarm not found")
        if row["status"] in TERMINAL_STATUSES:
            raise ValueError("Finished swarms cannot be paused")
        conn.execute("UPDATE swarm_runs SET status='paused' WHERE id=?", (swarm_id,))
    return get_run(swarm_id)


def resume(swarm_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT status FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
        if not row:
            raise ValueError("Swarm not found")
        if row["status"] != "paused":
            raise ValueError("Only paused swarms can be resumed")
        conn.execute("UPDATE swarm_runs SET status='running' WHERE id=?", (swarm_id,))
    return get_run(swarm_id)


def cancel(swarm_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT status FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
        if not row:
            raise ValueError("Swarm not found")
        conn.execute("UPDATE swarm_runs SET status='cancelled',cancel_requested=1,completed_at=? WHERE id=?", (now(), swarm_id))
        task_ids = [int(row[0]) for row in conn.execute(
            "SELECT id FROM background_tasks WHERE swarm_id=? AND status IN ('queued','running','waiting_for_approval','waiting_for_input')",
            (swarm_id,),
        )]
    for task_id in task_ids:
        task_queue.cancel(task_id)
    return get_run(swarm_id)


def set_status(swarm_id: int, status: str) -> None:
    stamp = now() if status in TERMINAL_STATUSES else ""
    with connect() as conn:
        if stamp:
            conn.execute("UPDATE swarm_runs SET status=?,completed_at=? WHERE id=?", (status, stamp, swarm_id))
        else:
            conn.execute("UPDATE swarm_runs SET status=? WHERE id=?", (status, swarm_id))


def publish(swarm_id: int, category: str, content: str, *, task_id: int | None = None, key: str = "", confidence: float | None = None) -> dict:
    category = category.strip().lower()
    if category not in {"fact", "finding", "decision", "question", "answer", "risk", "file", "interface", "test_result", "dependency", "assumption", "recommendation"}:
        raise ValueError("Unsupported blackboard category")
    stamp = now()
    with connect() as conn:
        if not conn.execute("SELECT id FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone():
            raise ValueError("Swarm not found")
        if task_id is not None:
            task = conn.execute("SELECT id FROM background_tasks WHERE id=? AND swarm_id=?", (task_id, swarm_id)).fetchone()
            if not task:
                raise ValueError("Task does not belong to this swarm")
        cursor = conn.execute(
            "INSERT INTO swarm_blackboard(swarm_id,task_id,category,key,content,confidence,created_at) VALUES(?,?,?,?,?,?,?)",
            (swarm_id, task_id, category, key, content, confidence, stamp),
        )
        row = conn.execute("SELECT * FROM swarm_blackboard WHERE id=?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def blackboard(swarm_id: int, *, category: str = "", task_id: int | None = None) -> list[dict]:
    clauses = ["swarm_id=?"]
    params: list[object] = [swarm_id]
    if category:
        clauses.append("category=?")
        params.append(category.strip().lower())
    if task_id is not None:
        clauses.append("task_id=?")
        params.append(task_id)
    with connect() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM swarm_blackboard WHERE " + " AND ".join(clauses) + " ORDER BY id",
            params,
        )]


def _agent_counts(swarm_id: int) -> dict:
    with connect() as conn:
        rows = conn.execute(
            "SELECT status,COUNT(*) AS count FROM background_tasks WHERE swarm_id=? GROUP BY status",
            (swarm_id,),
        ).fetchall()
    counts = {row["status"]: int(row["count"]) for row in rows}
    counts["total"] = sum(counts.values())
    counts["active"] = sum(counts.get(status, 0) for status in ACTIVE_TASK_STATUSES)
    return counts


def _json_object(value: object) -> dict:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
