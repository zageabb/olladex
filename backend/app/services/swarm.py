from __future__ import annotations

import json
import subprocess

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


def create_profile(data: dict) -> dict:
    stamp = now()
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("Swarm profile name is required")
    coordinator_id = _validated_model_profile_id(data.get("coordinator_profile_id"))
    worker_id = _validated_model_profile_id(data.get("default_worker_profile_id"))
    role_profiles = _validated_role_profiles(data.get("role_profiles") or {})
    with connect() as conn:
        if conn.execute("SELECT id FROM swarm_profiles WHERE name=?", (name,)).fetchone():
            raise ValueError("A Swarm profile with that name already exists")
        cursor = conn.execute(
            "INSERT INTO swarm_profiles("
            "name,enabled,coordinator_profile_id,default_worker_profile_id,role_profiles,"
            "max_agents,max_concurrency,max_depth,dynamic_size,agent_tool_budget,coordinator_tool_budget,"
            "require_reviewer,require_challenger,is_builtin,created_at,updated_at"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
            (
                name, 1 if data.get("enabled", True) else 0, coordinator_id, worker_id,
                json.dumps(role_profiles, sort_keys=True),
                max(2, min(int(data.get("max_agents") or 6), 20)),
                max(1, min(int(data.get("max_concurrency") or 3), 8)),
                max(1, min(int(data.get("max_depth") or 1), 4)),
                1 if data.get("dynamic_size", True) else 0,
                max(1, min(int(data.get("agent_tool_budget") or 30), 200)),
                max(1, min(int(data.get("coordinator_tool_budget") or 20), 200)),
                1 if data.get("require_reviewer", True) else 0,
                1 if data.get("require_challenger", False) else 0,
                stamp, stamp,
            ),
        )
        profile_id = int(cursor.lastrowid)
    return get_profile(profile_id)


def update_profile(profile_id: int, data: dict) -> dict:
    current = get_profile(profile_id)
    name = str(data.get("name") or current["name"]).strip()
    if current.get("is_builtin") and name != current["name"]:
        raise ValueError("Built-in Swarm profile names cannot be changed")
    coordinator_id = _validated_model_profile_id(data.get("coordinator_profile_id"))
    worker_id = _validated_model_profile_id(data.get("default_worker_profile_id"))
    role_profiles = _validated_role_profiles(data.get("role_profiles") or {})
    with connect() as conn:
        duplicate = conn.execute("SELECT id FROM swarm_profiles WHERE name=? AND id<>?", (name, profile_id)).fetchone()
        if duplicate:
            raise ValueError("A Swarm profile with that name already exists")
        conn.execute(
            "UPDATE swarm_profiles SET name=?,enabled=?,coordinator_profile_id=?,default_worker_profile_id=?,"
            "role_profiles=?,max_agents=?,max_concurrency=?,max_depth=?,dynamic_size=?,agent_tool_budget=?,"
            "coordinator_tool_budget=?,require_reviewer=?,require_challenger=?,updated_at=? WHERE id=?",
            (
                name, 1 if data.get("enabled", True) else 0, coordinator_id, worker_id,
                json.dumps(role_profiles, sort_keys=True),
                max(2, min(int(data.get("max_agents") or 6), 20)),
                max(1, min(int(data.get("max_concurrency") or 3), 8)),
                max(1, min(int(data.get("max_depth") or 1), 4)),
                1 if data.get("dynamic_size", True) else 0,
                max(1, min(int(data.get("agent_tool_budget") or 30), 200)),
                max(1, min(int(data.get("coordinator_tool_budget") or 20), 200)),
                1 if data.get("require_reviewer", True) else 0,
                1 if data.get("require_challenger", False) else 0,
                now(), profile_id,
            ),
        )
    return get_profile(profile_id)


def delete_profile(profile_id: int) -> dict:
    profile = get_profile(profile_id)
    if profile.get("is_builtin"):
        raise ValueError("Built-in Swarm profiles cannot be deleted")
    with connect() as conn:
        conn.execute("DELETE FROM swarm_profiles WHERE id=?", (profile_id,))
    return {"id": profile_id, "status": "deleted"}


def _validated_model_profile_id(value: object) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    profile_id = int(value)
    with connect() as conn:
        if not conn.execute("SELECT id FROM model_profiles WHERE id=?", (profile_id,)).fetchone():
            raise ValueError(f"Model profile #{profile_id} not found")
    return profile_id


def _validated_role_profiles(value: object) -> dict:
    role_map = _json_object(value)
    allowed = {"architect", "researcher", "backend", "frontend", "coder", "tester", "reviewer", "challenger", "integrator", "documentation", "worker"}
    result: dict[str, int] = {}
    for role, raw_id in role_map.items():
        if role not in allowed or raw_id in (None, "", 0, "0"):
            continue
        profile_id = _validated_model_profile_id(raw_id)
        if profile_id is not None:
            result[role] = profile_id
    return result


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


def initial_specialist_budget(profile: dict, max_agents: int) -> int:
    reserved = (1 if profile.get("require_reviewer") else 0) + (1 if profile.get("require_challenger") else 0)
    available = int(max_agents) - reserved
    if available < 2:
        raise ValueError("This Swarm profile needs at least two specialist slots plus its required review roles")
    if profile.get("dynamic_size") and available > 2:
        return available - 1
    return available


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


def preflight(
    project_id: int,
    profile_id: int,
    *,
    max_agents: int | None = None,
    max_concurrency: int | None = None,
) -> dict:
    profile = get_profile(profile_id)
    requested_agents = max(2, min(int(max_agents or profile["max_agents"]), 20))
    requested_concurrency = max(1, min(int(max_concurrency or profile["max_concurrency"]), requested_agents, 8))

    checks: list[dict] = []
    with connect() as conn:
        project = conn.execute("SELECT id,path FROM projects WHERE id=?", (project_id,)).fetchone()
        if not project:
            raise ValueError("Project not found")
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        busy_timeout = int(conn.execute("PRAGMA busy_timeout").fetchone()[0])

    checks.append({
        "name": "sqlite_wal",
        "ok": journal_mode == "wal",
        "detail": f"journal_mode={journal_mode}",
    })
    checks.append({
        "name": "sqlite_busy_timeout",
        "ok": busy_timeout >= 5000,
        "detail": f"busy_timeout={busy_timeout}ms",
    })

    path = str(project["path"] or "")
    git_ok = False
    git_detail = "Project path is not a Git repository"
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=path,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
        git_ok = completed.returncode == 0 and completed.stdout.strip() == "true"
        git_detail = completed.stdout.strip() or git_detail
    except (OSError, subprocess.SubprocessError) as exc:
        git_detail = str(exc)
    checks.append({"name": "git_repository", "ok": git_ok, "detail": git_detail})

    try:
        model_status = validate_models(profile)
        checks.append({
            "name": "ollama_models",
            "ok": True,
            "detail": ", ".join(sorted(set(model_status.get("assignments", {}).values()))) or "No explicit model assignments",
        })
    except ValueError as exc:
        model_status = {"installed": [], "assignments": {}}
        checks.append({"name": "ollama_models", "ok": False, "detail": str(exc)})

    checks.append({
        "name": "swarm_limits",
        "ok": requested_concurrency <= requested_agents,
        "detail": f"max_agents={requested_agents}, max_concurrency={requested_concurrency}",
    })

    return {
        "ready": all(item["ok"] for item in checks),
        "project_id": project_id,
        "profile_id": profile_id,
        "max_agents": requested_agents,
        "max_concurrency": requested_concurrency,
        "checks": checks,
        "models": model_status,
    }


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
    emit_coordinator_event(swarm_id, "created", {"status": "planning", "title": title[:256]})
    return get_run(swarm_id)


def get_run(swarm_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
    if not row:
        raise ValueError("Swarm not found")
    result = dict(row)
    result["agents"] = list_agents(swarm_id)
    with connect() as conn:
        activity = conn.execute(
            "SELECT category,key,content,created_at FROM swarm_blackboard "
            "WHERE swarm_id=? AND task_id IS NULL AND category IN ('decision','risk') "
            "ORDER BY id DESC LIMIT 1",
            (swarm_id,),
        ).fetchone()
    result["coordinator_activity"] = dict(activity) if activity else None
    result["coordinator_budget"] = coordinator_budget(swarm_id)
    return result


def list_runs(project_id: int) -> list[dict]:
    with connect() as conn:
        rows = [dict(row) for row in conn.execute("SELECT * FROM swarm_runs WHERE project_id=? ORDER BY id DESC", (project_id,))]
    for item in rows:
        item["agent_counts"] = _agent_counts(item["id"])
    return rows


def list_agents(swarm_id: int) -> list[dict]:
    with connect() as conn:
        budget_row = conn.execute(
            "SELECT sp.agent_tool_budget FROM swarm_runs sr LEFT JOIN swarm_profiles sp ON sp.id=sr.profile_id WHERE sr.id=?",
            (swarm_id,),
        ).fetchone()
        tool_budget = int(budget_row["agent_tool_budget"] or 0) if budget_row else 0
        rows = [dict(row) for row in conn.execute(
            "SELECT bt.*, "
            "(SELECT ar.id FROM agent_runs ar WHERE ar.task_id=bt.id ORDER BY ar.id DESC LIMIT 1) AS run_id, "
            "(SELECT ar.status FROM agent_runs ar WHERE ar.task_id=bt.id ORDER BY ar.id DESC LIMIT 1) AS run_status "
            "FROM background_tasks bt "
            "WHERE bt.swarm_id=? ORDER BY bt.priority ASC,bt.id ASC",
            (swarm_id,),
        )]
        for item in rows:
            insight = conn.execute(
                "SELECT category,content,created_at FROM swarm_blackboard "
                "WHERE swarm_id=? AND task_id=? AND category IN ('finding','risk','handoff') "
                "ORDER BY id DESC LIMIT 1",
                (swarm_id, item["id"]),
            ).fetchone()
            item["latest_insight"] = dict(insight) if insight else None
            try:
                item["depends_on"] = json.loads(item.get("depends_on") or "[]")
            except (TypeError, json.JSONDecodeError):
                item["depends_on"] = []
            run_id = item.get("run_id")
            item["tool_budget"] = tool_budget
            if not run_id:
                item["tool_usage"] = 0
                item["latest_event"] = None
                continue
            item["tool_usage"] = int(conn.execute(
                "SELECT COUNT(*) FROM agent_events WHERE run_id=? AND kind='tool_started'",
                (run_id,),
            ).fetchone()[0])
            event = conn.execute(
                "SELECT kind,payload,created_at FROM agent_events WHERE run_id=? "
                "AND kind NOT IN ('text_delta','assistant_start') ORDER BY id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            if not event:
                item["latest_event"] = None
                continue
            payload = _json_object(event["payload"])
            item["latest_event"] = {
                "kind": event["kind"],
                "payload": payload,
                "created_at": event["created_at"],
            }
            item["current_activity"] = _event_summary(event["kind"], payload)
    return rows


def _event_summary(kind: str, payload: dict) -> str:
    if kind in {"finding", "decision", "risk", "handoff"}:
        return str(payload.get("content") or "")
    if kind == "progress":
        return str(payload.get("message") or "Working")
    if kind == "plan":
        steps = payload.get("steps") or []
        return "Plan: " + " · ".join(str(step) for step in steps[:3])
    if kind in {"tool_start", "tool_started"}:
        return "Using " + str(payload.get("tool") or "tool")
    if kind == "tool_result":
        return str(payload.get("summary") or "Tool completed")
    if kind == "assistant_end":
        return str(payload.get("content") or "")[:400]
    if kind == "status":
        return "Status: " + str(payload.get("status") or "")
    return kind.replace("_", " ").title()



def events(swarm_id: int, after: int = 0, limit: int = 200) -> list[dict]:
    limit = max(1, min(int(limit or 200), 1000))
    with connect() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT ae.id,ae.run_id,ae.kind,ae.payload,ae.created_at,"
            "bt.id AS task_id,bt.title AS task_title,bt.agent_role,bt.assigned_model "
            "FROM agent_events ae "
            "JOIN agent_runs ar ON ar.id=ae.run_id "
            "JOIN background_tasks bt ON bt.id=ar.task_id "
            "WHERE bt.swarm_id=? AND ae.id>? "
            "ORDER BY ae.id ASC LIMIT ?",
            (swarm_id, max(0, int(after)), limit),
        )]
    for item in rows:
        item["payload"] = _json_object(item.get("payload"))
    return rows

def emit_coordinator_event(swarm_id: int, kind: str, payload: dict) -> dict:
    stamp = now()
    with connect() as conn:
        if not conn.execute("SELECT id FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone():
            raise ValueError("Swarm not found")
        cursor = conn.execute(
            "INSERT INTO swarm_coordinator_events(swarm_id,kind,payload,created_at) VALUES(?,?,?,?)",
            (swarm_id, kind, json.dumps(payload, default=str), stamp),
        )
        row = conn.execute("SELECT * FROM swarm_coordinator_events WHERE id=?", (cursor.lastrowid,)).fetchone()
    result = dict(row)
    result["payload"] = _json_object(result.get("payload"))
    return result


def consume_coordinator_budget(swarm_id: int, purpose: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT sp.coordinator_tool_budget FROM swarm_runs sr "
            "LEFT JOIN swarm_profiles sp ON sp.id=sr.profile_id WHERE sr.id=?",
            (swarm_id,),
        ).fetchone()
        if not row:
            raise ValueError("Swarm not found")
        budget = max(1, int(row["coordinator_tool_budget"] or 1))
        used = int(conn.execute(
            "SELECT COUNT(*) FROM swarm_coordinator_events WHERE swarm_id=? AND kind='model_call'",
            (swarm_id,),
        ).fetchone()[0])
        if used >= budget:
            remaining = 0
            allowed = False
            exhaustion_recorded = bool(conn.execute(
                "SELECT id FROM swarm_coordinator_events WHERE swarm_id=? AND kind='budget_exhausted' LIMIT 1",
                (swarm_id,),
            ).fetchone())
        else:
            remaining = budget - used - 1
            allowed = True
            exhaustion_recorded = False
    if allowed:
        emit_coordinator_event(
            swarm_id,
            "model_call",
            {"purpose": purpose, "used": used + 1, "budget": budget, "remaining": remaining},
        )
    elif not exhaustion_recorded:
        emit_coordinator_event(
            swarm_id,
            "budget_exhausted",
            {"purpose": purpose, "used": used, "budget": budget, "remaining": 0},
        )
    return {"allowed": allowed, "used": used + (1 if allowed else 0), "budget": budget, "remaining": remaining}


def coordinator_budget(swarm_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT sp.coordinator_tool_budget FROM swarm_runs sr "
            "LEFT JOIN swarm_profiles sp ON sp.id=sr.profile_id WHERE sr.id=?",
            (swarm_id,),
        ).fetchone()
        if not row:
            raise ValueError("Swarm not found")
        budget = max(1, int(row["coordinator_tool_budget"] or 1))
        used = int(conn.execute(
            "SELECT COUNT(*) FROM swarm_coordinator_events WHERE swarm_id=? AND kind='model_call'",
            (swarm_id,),
        ).fetchone()[0])
    return {"used": used, "budget": budget, "remaining": max(0, budget - used)}


def coordinator_events(swarm_id: int, after: int = 0, limit: int = 200) -> list[dict]:
    limit = max(1, min(int(limit or 200), 1000))
    with connect() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM swarm_coordinator_events WHERE swarm_id=? AND id>? ORDER BY id ASC LIMIT ?",
            (swarm_id, max(0, int(after)), limit),
        )]
    for item in rows:
        item["payload"] = _json_object(item.get("payload"))
    return rows


def steer_coordinator(swarm_id: int, content: str) -> dict:
    content = content.strip()
    if not content:
        raise ValueError("Coordinator guidance cannot be empty")
    with connect() as conn:
        row = conn.execute("SELECT coordinator_instructions,status FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
        if not row:
            raise ValueError("Swarm not found")
        if row["status"] in TERMINAL_STATUSES:
            raise ValueError("Finished swarms cannot be steered")
        existing = str(row["coordinator_instructions"] or "").strip()
        combined = (existing + "\n" + content).strip()
        if len(combined) > 12000:
            combined = combined[-12000:]
        conn.execute("UPDATE swarm_runs SET coordinator_instructions=? WHERE id=?", (combined, swarm_id))
    publish(swarm_id, "decision", "User guidance to Coordinator: " + content, key="")
    emit_coordinator_event(swarm_id, "guidance", {"content": content})
    return {"swarm_id": swarm_id, "status": "received", "coordinator_instructions": combined}


def broadcast_guidance(swarm_id: int, content: str) -> dict:
    content = content.strip()
    if not content:
        raise ValueError("Swarm guidance cannot be empty")

    coordinator = steer_coordinator(swarm_id, content)
    marker = "\n\nSwarm-wide user guidance:\n" + content

    with connect() as conn:
        run = conn.execute("SELECT status FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
        if not run:
            raise ValueError("Swarm not found")
        if run["status"] in TERMINAL_STATUSES:
            raise ValueError("Finished swarms cannot be steered")

        queued_ids = [
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM background_tasks WHERE swarm_id=? AND status='queued'",
                (swarm_id,),
            )
        ]
        for task_id in queued_ids:
            row = conn.execute("SELECT prompt FROM background_tasks WHERE id=?", (task_id,)).fetchone()
            prompt = str(row["prompt"] or "") if row else ""
            if content not in prompt[-12000:]:
                conn.execute(
                    "UPDATE background_tasks SET prompt=? WHERE id=?",
                    ((prompt + marker)[-100000:], task_id),
                )

        active_runs = [
            int(row["id"])
            for row in conn.execute(
                "SELECT ar.id FROM agent_runs ar "
                "JOIN background_tasks bt ON bt.id=ar.task_id "
                "WHERE bt.swarm_id=? AND ar.status IN ('running','waiting_for_approval','waiting_for_input')",
                (swarm_id,),
            )
        ]

    from . import conversation_runtime
    steered: list[int] = []
    for run_id in active_runs:
        try:
            conversation_runtime.steer(run_id, "Swarm-wide user guidance: " + content)
            steered.append(run_id)
        except Exception:
            # A run may finish between the query and steering. Queued/future work
            # still retains the persistent guidance.
            continue

    emit_coordinator_event(
        swarm_id,
        "broadcast",
        {
            "content": content,
            "queued_tasks_updated": len(queued_ids),
            "active_runs_steered": len(steered),
        },
    )
    return {
        **coordinator,
        "queued_tasks_updated": len(queued_ids),
        "active_runs_steered": len(steered),
    }


def board_snapshot(
    swarm_id: int,
    *,
    after_event: int = 0,
    after_coordinator_event: int = 0,
    after_blackboard: int = 0,
    limit: int = 200,
) -> dict:
    run = get_run(swarm_id)
    agent_items = run.get("agents") or []
    status_counts: dict[str, int] = {}
    for agent in agent_items:
        status = str(agent.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    complete = status_counts.get("completed", 0)
    active = sum(status_counts.get(state, 0) for state in ("running", "waiting_for_input", "waiting_for_approval"))
    failed = sum(status_counts.get(state, 0) for state in ("failed", "budget_exhausted"))
    overall_progress = 0
    if agent_items:
        overall_progress = round(sum(
            100 if agent.get("status") == "completed"
            else max(0, min(int(agent.get("progress") or 0), 99))
            for agent in agent_items
        ) / len(agent_items))

    tool_usage_total = sum(int(agent.get("tool_usage") or 0) for agent in agent_items)
    tool_budget_per_agent = max((int(agent.get("tool_budget") or 0) for agent in agent_items), default=0)
    tool_budget_capacity = int(run.get("max_agents") or 0) * tool_budget_per_agent if tool_budget_per_agent else 0

    integration_ready = bool(
        run.get("status") == "completed"
        and any(
            agent.get("status") == "completed"
            and agent.get("task_kind") not in {"reviewer", "challenger"}
            and agent.get("worktree_branch")
            for agent in agent_items
        )
    )

    agent_events = events(swarm_id, after=after_event, limit=limit)
    coordinator_items = coordinator_events(swarm_id, after=after_coordinator_event, limit=limit)
    blackboard_items = blackboard(swarm_id, after=after_blackboard, limit=limit)

    return {
        "swarm": run,
        "summary": {
            "total_agents": len(agent_items),
            "max_agents": int(run.get("max_agents") or 0),
            "active_agents": active,
            "max_concurrency": int(run.get("max_concurrency") or 0),
            "completed_agents": complete,
            "failed_agents": failed,
            "progress": overall_progress,
            "tool_usage": tool_usage_total,
            "tool_budget_capacity": tool_budget_capacity,
            "coordinator_budget": run.get("coordinator_budget") or {"used": 0, "budget": 0, "remaining": 0},
            "integration_ready": integration_ready,
        },
        "events": agent_events,
        "coordinator_events": coordinator_items,
        "blackboard": blackboard_items,
        "cursors": {
            "event": int(agent_events[-1]["id"]) if agent_events else max(0, int(after_event)),
            "coordinator_event": int(coordinator_items[-1]["id"]) if coordinator_items else max(0, int(after_coordinator_event)),
            "blackboard": int(blackboard_items[-1]["id"]) if blackboard_items else max(0, int(after_blackboard)),
        },
    }


def pause(swarm_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT status FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
        if not row:
            raise ValueError("Swarm not found")
        if row["status"] not in {"running", "reviewing", "waiting"}:
            raise ValueError("Only active orchestration can be paused")
        conn.execute("UPDATE swarm_runs SET status='paused' WHERE id=?", (swarm_id,))
    emit_coordinator_event(swarm_id, "status", {"status": "paused"})
    return get_run(swarm_id)


def resume(swarm_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT status FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
        if not row:
            raise ValueError("Swarm not found")
        if row["status"] != "paused":
            raise ValueError("Only paused swarms can be resumed")
        conn.execute("UPDATE swarm_runs SET status='running' WHERE id=?", (swarm_id,))
    emit_coordinator_event(swarm_id, "status", {"status": "running", "reason": "resumed"})
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
    emit_coordinator_event(swarm_id, "status", {"status": "cancelled"})
    return get_run(swarm_id)


def set_status(swarm_id: int, status: str) -> None:
    stamp = now() if status in TERMINAL_STATUSES else ""
    with connect() as conn:
        row = conn.execute("SELECT status FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
        if not row:
            raise ValueError("Swarm not found")
        previous = str(row["status"])
        if previous == status:
            return
        if stamp:
            conn.execute("UPDATE swarm_runs SET status=?,completed_at=? WHERE id=?", (status, stamp, swarm_id))
        else:
            conn.execute("UPDATE swarm_runs SET status=? WHERE id=?", (status, swarm_id))
    emit_coordinator_event(swarm_id, "status", {"status": status, "previous": previous})


def publish(swarm_id: int, category: str, content: str, *, task_id: int | None = None, key: str = "", confidence: float | None = None) -> dict:
    category = category.strip().lower()
    if category not in {"fact", "finding", "decision", "question", "answer", "risk", "file", "interface", "test_result", "dependency", "assumption", "recommendation", "handoff"}:
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
    result = dict(row)
    if task_id is None and category in {"decision", "risk"}:
        emit_coordinator_event(
            swarm_id,
            category,
            {"content": content, "key": key, "confidence": confidence},
        )
    return result


def blackboard(
    swarm_id: int,
    *,
    category: str = "",
    task_id: int | None = None,
    after: int = 0,
    limit: int | None = None,
) -> list[dict]:
    clauses = ["swarm_id=?", "id>?"]
    params: list[object] = [swarm_id, max(0, int(after or 0))]
    if category:
        clauses.append("category=?")
        params.append(category.strip().lower())
    if task_id is not None:
        clauses.append("task_id=?")
        params.append(task_id)
    sql = "SELECT * FROM swarm_blackboard WHERE " + " AND ".join(clauses) + " ORDER BY id"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(1, min(int(limit or 200), 1000)))
    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, params)]


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
