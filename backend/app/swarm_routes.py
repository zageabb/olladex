from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .database import connect, now
from .services import orchestration as orchestration_service
from .services import swarm as swarm_service
from .services import task_queue


router = APIRouter(prefix="/api", tags=["swarm"])


class SwarmSkillRequest(BaseModel):
    enabled: bool


class SwarmCreateRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=100_000)
    title: str = Field(default="", max_length=256)
    profile_id: int
    max_agents: int | None = Field(default=None, ge=2, le=20)
    max_concurrency: int | None = Field(default=None, ge=1, le=8)


class BlackboardWriteRequest(BaseModel):
    category: str = Field(min_length=1, max_length=40)
    content: str = Field(min_length=1, max_length=50_000)
    key: str = Field(default="", max_length=200)
    task_id: int | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class AgentInputRequest(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


def _project(project_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT p.*,mp.chat_model AS profile_chat_model,mp.embedding_model AS profile_embedding_model,"
            "mp.temperature AS profile_temperature,mp.max_steps AS profile_max_steps,"
            "mp.context_files AS profile_context_files,mp.context_chars AS profile_context_chars,"
            "mp.context_tokens AS profile_context_tokens "
            "FROM projects p LEFT JOIN model_profiles mp ON mp.id=p.model_profile_id WHERE p.id=?",
            (project_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return dict(row)


def _new_session(project_id: int, title: str) -> int:
    stamp = now()
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (project_id, title[:200], stamp, stamp),
        )
        return int(cursor.lastrowid)


@router.get("/projects/{project_id}/skills/swarm")
def swarm_skill(project_id: int):
    _project(project_id)
    return {"project_id": project_id, "skill": "swarm", "enabled": swarm_service.skill_enabled(project_id)}


@router.put("/projects/{project_id}/skills/swarm")
def update_swarm_skill(project_id: int, body: SwarmSkillRequest):
    _project(project_id)
    try:
        return swarm_service.set_skill(project_id, body.enabled)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/swarm-profiles")
def swarm_profiles():
    return swarm_service.list_profiles()


@router.get("/projects/{project_id}/swarms")
def swarms(project_id: int):
    _project(project_id)
    return swarm_service.list_runs(project_id)


@router.post("/projects/{project_id}/swarms")
def create_swarm(project_id: int, body: SwarmCreateRequest):
    project = _project(project_id)
    title = body.title.strip() or body.objective.strip().splitlines()[0][:100]
    session_id = _new_session(project_id, title)
    try:
        swarm = swarm_service.create_run(
            project_id,
            session_id,
            title,
            body.objective,
            body.profile_id,
            max_agents=body.max_agents,
            max_concurrency=body.max_concurrency,
        )
        profile = swarm_service.get_profile(body.profile_id)
        reserved = (1 if profile.get("require_reviewer") else 0) + (1 if profile.get("require_challenger") else 0)
        specialist_budget = int(swarm["max_agents"]) - reserved
        if specialist_budget < 2:
            raise ValueError("This Swarm profile needs at least two specialist slots plus its required review roles")

        coordinator_profile_id, coordinator_model = swarm_service.coordinator_model(profile)
        planning_project = dict(project)
        planning_project["profile_chat_model"] = coordinator_model or project.get("profile_chat_model")
        plan = orchestration_service.decompose(planning_project, body.objective, specialist_budget)

        child_ids: list[int] = []
        created: list[dict] = []
        for item in plan:
            dependencies = [child_ids[index] for index in item.get("depends_on", []) if 0 <= index < len(child_ids)]
            role = item.get("role") or "worker"
            model_profile_id, assigned_model = swarm_service.resolve_role(profile, role)
            task_session = _new_session(project_id, item["title"])
            task = task_queue.enqueue(
                project_id,
                task_session,
                item["title"],
                item["prompt"],
                source_kind="swarm_specialist",
                source_ref=f"swarm:{swarm['id']}",
                depends_on=dependencies,
                agent_role=role,
                swarm_id=swarm["id"],
                model_profile_id=model_profile_id,
                assigned_model=assigned_model,
                task_kind=role,
                priority=100,
                depth=1,
            )
            child_ids.append(task["id"])
            created.append(task)

        verification_ids = list(child_ids)
        challenger = None
        if profile.get("require_challenger"):
            model_profile_id, assigned_model = swarm_service.resolve_role(profile, "challenger")
            challenger_session = _new_session(project_id, f"Challenge: {title}")
            challenger = task_queue.enqueue(
                project_id,
                challenger_session,
                f"Challenge: {title}",
                "Act as an independent challenger. Inspect the completed specialist hand-offs and inherited code. "
                "Try to disprove the solution by finding regressions, edge cases, security issues, invalid assumptions, "
                "API incompatibilities, error paths, race conditions, and missing tests. Do not claim issues without evidence.",
                source_kind="swarm_challenger",
                source_ref=f"swarm:{swarm['id']}",
                depends_on=child_ids,
                agent_role="challenger",
                swarm_id=swarm["id"],
                model_profile_id=model_profile_id,
                assigned_model=assigned_model,
                task_kind="challenger",
                priority=200,
                depth=1,
            )
            verification_ids = [challenger["id"]]

        reviewer = None
        if profile.get("require_reviewer"):
            model_profile_id, assigned_model = swarm_service.resolve_role(profile, "reviewer")
            reviewer_session = _new_session(project_id, f"Review: {title}")
            reviewer = task_queue.enqueue(
                project_id,
                reviewer_session,
                f"Review: {title}",
                "Act as the independent final reviewer. Review all dependency hand-offs, actual inherited changes and "
                "test evidence. Identify conflicts, omissions, unsupported success claims and remaining risks. "
                "Summarize what is ready for integration and what still needs work.",
                source_kind="swarm_reviewer",
                source_ref=f"swarm:{swarm['id']}",
                depends_on=verification_ids,
                agent_role="reviewer",
                swarm_id=swarm["id"],
                model_profile_id=model_profile_id,
                assigned_model=assigned_model,
                task_kind="reviewer",
                priority=300,
                depth=1,
            )

        with connect() as conn:
            conn.execute(
                "UPDATE swarm_runs SET status='running' WHERE id=?",
                (swarm["id"],),
            )
        return {
            "swarm": swarm_service.get_run(swarm["id"]),
            "coordinator": {"model_profile_id": coordinator_profile_id, "model": coordinator_model},
            "plan": plan,
            "specialists": created,
            "challenger": challenger,
            "reviewer": reviewer,
        }
    except Exception as exc:
        with connect() as conn:
            run = conn.execute("SELECT id FROM swarm_runs WHERE session_id=? ORDER BY id DESC LIMIT 1", (session_id,)).fetchone()
            if run:
                conn.execute("UPDATE swarm_runs SET status='failed',completed_at=? WHERE id=?", (now(), run["id"]))
            else:
                conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(409, str(exc)) from exc


@router.get("/swarms/{swarm_id}")
def get_swarm(swarm_id: int):
    try:
        return swarm_service.get_run(swarm_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/swarms/{swarm_id}/pause")
def pause_swarm(swarm_id: int):
    try:
        return swarm_service.pause(swarm_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/swarms/{swarm_id}/resume")
def resume_swarm(swarm_id: int):
    try:
        return swarm_service.resume(swarm_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/swarms/{swarm_id}")
def cancel_swarm(swarm_id: int):
    try:
        return swarm_service.cancel(swarm_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/swarms/{swarm_id}/agents")
def swarm_agents(swarm_id: int):
    try:
        swarm_service.get_run(swarm_id)
        return swarm_service.list_agents(swarm_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/swarms/{swarm_id}/events")
def swarm_events(swarm_id: int, after: int = 0, limit: int = 200):
    try:
        swarm_service.get_run(swarm_id)
        return swarm_service.events(swarm_id, after=after, limit=limit)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/swarms/{swarm_id}/blackboard")
def read_blackboard(swarm_id: int, category: str = "", task_id: int | None = None):
    try:
        swarm_service.get_run(swarm_id)
        return swarm_service.blackboard(swarm_id, category=category, task_id=task_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/swarms/{swarm_id}/blackboard")
def write_blackboard(swarm_id: int, body: BlackboardWriteRequest):
    try:
        return swarm_service.publish(
            swarm_id,
            body.category,
            body.content,
            task_id=body.task_id,
            key=body.key,
            confidence=body.confidence,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/swarm-agents/{task_id}/input")
def steer_swarm_agent(task_id: int, body: AgentInputRequest):
    task = task_queue.get(task_id)
    if not task or not task.get("swarm_id"):
        raise HTTPException(404, "Swarm agent not found")
    with connect() as conn:
        run = conn.execute(
            "SELECT id FROM agent_runs WHERE task_id=? AND status IN ('running','waiting_for_approval','waiting_for_input') ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
    if not run:
        raise HTTPException(409, "This swarm agent is not currently running")
    from .services import conversation_runtime
    conversation_runtime.steer(int(run["id"]), body.content)
    return {"task_id": task_id, "run_id": int(run["id"]), "status": "received"}


@router.delete("/swarm-agents/{task_id}")
def stop_swarm_agent(task_id: int):
    task = task_queue.get(task_id)
    if not task or not task.get("swarm_id"):
        raise HTTPException(404, "Swarm agent not found")
    return task_queue.cancel(task_id)
