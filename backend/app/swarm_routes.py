from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .database import connect, now
from .services import orchestration as orchestration_service
from .services import swarm as swarm_service
from .services import task_queue, integration, worktrees
from .services import github as github_service


router = APIRouter(prefix="/api", tags=["swarm"])


class SwarmSkillRequest(BaseModel):
    enabled: bool


class SwarmProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    coordinator_profile_id: int | None = None
    default_worker_profile_id: int | None = None
    role_profiles: dict[str, int] = Field(default_factory=dict)
    max_agents: int = Field(default=6, ge=2, le=20)
    max_concurrency: int = Field(default=3, ge=1, le=8)
    max_depth: int = Field(default=1, ge=1, le=4)
    dynamic_size: bool = True
    agent_tool_budget: int = Field(default=30, ge=1, le=200)
    coordinator_tool_budget: int = Field(default=20, ge=1, le=200)
    require_reviewer: bool = True
    require_challenger: bool = False


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


class SwarmIntegrationSelectionRequest(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=20)
    base: str = Field(default="main", min_length=1, max_length=200)


class SwarmIntegrationChecksRequest(BaseModel):
    command: str = Field(min_length=1, max_length=5000)


class SwarmIntegrationPushRequest(BaseModel):
    remote: str = Field(default="origin", min_length=1, max_length=120)


class SwarmIntegrationPullRequestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(default="", max_length=100_000)
    base: str = Field(default="main", min_length=1, max_length=200)


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


@router.post("/swarm-profiles")
def create_swarm_profile(body: SwarmProfileRequest):
    try:
        return swarm_service.create_profile(body.model_dump())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.put("/swarm-profiles/{profile_id}")
def update_swarm_profile(profile_id: int, body: SwarmProfileRequest):
    try:
        return swarm_service.update_profile(profile_id, body.model_dump())
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/swarm-profiles/{profile_id}")
def delete_swarm_profile(profile_id: int):
    try:
        return swarm_service.delete_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


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
        specialist_budget = swarm_service.initial_specialist_budget(profile, int(swarm["max_agents"]))

        coordinator_profile_id, coordinator_model = swarm_service.coordinator_model(profile)
        planning_project = dict(project)
        planning_project["profile_chat_model"] = coordinator_model or project.get("profile_chat_model")
        plan = orchestration_service.decompose(planning_project, body.objective, specialist_budget, swarm_mode=True)

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

        swarm_service.set_status(int(swarm["id"]), "running")
        from .services import swarm_coordinator
        swarm_coordinator.start(int(swarm["id"]))
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
                failed_swarm_id = int(run["id"])
            else:
                failed_swarm_id = None
                conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        if failed_swarm_id is not None:
            swarm_service.set_status(failed_swarm_id, "failed")
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(409, str(exc)) from exc


@router.get("/swarms/{swarm_id}")
def get_swarm(swarm_id: int):
    try:
        return swarm_service.get_run(swarm_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/swarms/{swarm_id}/coordinator/input")
def steer_swarm_coordinator(swarm_id: int, body: AgentInputRequest):
    try:
        return swarm_service.steer_coordinator(swarm_id, body.content)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


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
        from .services import swarm_coordinator
        swarm_coordinator.stop(swarm_id)
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


@router.get("/swarms/{swarm_id}/coordinator/events")
def coordinator_events(swarm_id: int, after: int = 0, limit: int = 200):
    try:
        swarm_service.get_run(swarm_id)
        return swarm_service.coordinator_events(swarm_id, after=after, limit=limit)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/swarms/{swarm_id}/events")
def swarm_events(swarm_id: int, after: int = 0, limit: int = 200):
    try:
        swarm_service.get_run(swarm_id)
        return swarm_service.events(swarm_id, after=after, limit=limit)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


def _swarm_integration_branches(swarm_id: int, task_ids: list[int]) -> tuple[dict, dict, list[str]]:
    run = swarm_service.get_run(swarm_id)
    project = _project(int(run["project_id"]))
    tasks = {item["id"]: item for item in swarm_service.list_agents(swarm_id)}
    branches: list[str] = []
    for task_id in task_ids:
        task = tasks.get(task_id)
        if not task:
            raise HTTPException(409, f"Task #{task_id} is not part of swarm #{swarm_id}")
        if task.get("task_kind") in {"reviewer", "challenger"}:
            continue
        if task.get("status") != "completed":
            raise HTTPException(409, f"Task #{task_id} is not completed")
        branch = str(task.get("worktree_branch") or "")
        path = str(task.get("worktree_path") or "")
        if not branch or not path:
            raise HTTPException(409, f"Task #{task_id} has no available worktree branch")
        try:
            summary = worktrees.summary(project, path)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if summary.get("changes"):
            raise HTTPException(409, f"Task #{task_id} still has uncommitted changes")
        try:
            changed = integration.changed_files(project, branch)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if changed and branch not in branches:
            branches.append(branch)
    if not branches:
        raise HTTPException(409, "Select at least one completed specialist task")
    return run, project, branches


@router.post("/swarms/{swarm_id}/integration/preflight")
def swarm_integration_preflight(swarm_id: int, body: SwarmIntegrationSelectionRequest):
    _, project, branches = _swarm_integration_branches(swarm_id, body.task_ids)
    try:
        return {"swarm_id": swarm_id, "task_ids": body.task_ids, **integration.preflight(project, branches, body.base)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/swarms/{swarm_id}/integration")
def create_swarm_integration(swarm_id: int, body: SwarmIntegrationSelectionRequest):
    run, project, branches = _swarm_integration_branches(swarm_id, body.task_ids)
    if run["status"] != "completed":
        raise HTTPException(409, "Swarm final verification must complete before integration")
    try:
        result = integration.create(project, swarm_id, branches, body.base, namespace="swarm")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    with connect() as conn:
        conn.execute(
            "UPDATE swarm_runs SET status='integrating',integration_path=?,integration_branch=?,"
            "integration_check_command='',integration_check_status='',integration_check_output='',"
            "integration_pr_number=0,integration_pr_url='',integration_pr_state='' WHERE id=?",
            (result["path"], result["branch"], swarm_id),
        )
    return {"swarm_id": swarm_id, "task_ids": body.task_ids, **result}


@router.get("/swarms/{swarm_id}/integration")
def get_swarm_integration(swarm_id: int, base: str = "main"):
    run = swarm_service.get_run(swarm_id)
    project = _project(int(run["project_id"]))
    path = run.get("integration_path") or ""
    if not path:
        return {
            "swarm_id": swarm_id, "path": "", "branch": "", "base": base,
            "check_command": run.get("integration_check_command") or "",
            "check_status": run.get("integration_check_status") or "",
            "check_output": run.get("integration_check_output") or "",
        }
    try:
        summary = integration.summary(project, path, base)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "swarm_id": swarm_id, **summary,
        "check_command": run.get("integration_check_command") or "",
        "check_status": run.get("integration_check_status") or "",
        "check_output": run.get("integration_check_output") or "",
    }


@router.post("/swarms/{swarm_id}/integration/checks")
def run_swarm_integration_checks(swarm_id: int, body: SwarmIntegrationChecksRequest):
    run = swarm_service.get_run(swarm_id)
    project = _project(int(run["project_id"]))
    path = run.get("integration_path") or ""
    if not path:
        raise HTTPException(409, "Create a Swarm integration worktree first")
    try:
        result = integration.run_checks(project, path, body.command)
    except (ValueError, TimeoutError) as exc:
        raise HTTPException(409, str(exc)) from exc
    with connect() as conn:
        conn.execute(
            "UPDATE swarm_runs SET integration_check_command=?,integration_check_status=?,integration_check_output=? WHERE id=?",
            (body.command, "passed" if result["passed"] else "failed", result["output"], swarm_id),
        )
    return {"swarm_id": swarm_id, **result}


def _pull_request_number(url: str) -> int:
    match = re.search(r"/pull/(\\d+)(?:\\b|/|$)", url or "")
    return int(match.group(1)) if match else 0


@router.post("/swarms/{swarm_id}/integration/push")
def push_swarm_integration(swarm_id: int, body: SwarmIntegrationPushRequest):
    run = swarm_service.get_run(swarm_id)
    project = _project(int(run["project_id"]))
    path = run.get("integration_path") or ""
    if not path:
        raise HTTPException(409, "Create a Swarm integration worktree first")
    if run.get("integration_check_status") != "passed":
        raise HTTPException(409, "Combined checks must pass before pushing the integration branch")
    try:
        return {"swarm_id": swarm_id, **integration.push(project, path, body.remote)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/swarms/{swarm_id}/integration/pull-request")
def create_swarm_integration_pull_request(swarm_id: int, body: SwarmIntegrationPullRequestRequest):
    run = swarm_service.get_run(swarm_id)
    project = _project(int(run["project_id"]))
    path = run.get("integration_path") or ""
    if not path:
        raise HTTPException(409, "Create a Swarm integration worktree first")
    if run.get("integration_check_status") != "passed":
        raise HTTPException(409, "Combined checks must pass before creating the integration pull request")
    target_project = integration.integration_project(project, path)
    try:
        prepared = github_service.prepare_pull_request(target_project, body.title, body.body, body.base)
        result = github_service.execute_pull_request(target_project, prepared)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    number = _pull_request_number(result.get("url", ""))
    with connect() as conn:
        conn.execute(
            "UPDATE swarm_runs SET integration_pr_number=?,integration_pr_url=?,integration_pr_state='OPEN' WHERE id=?",
            (number, result.get("url", ""), swarm_id),
        )
    return {"swarm_id": swarm_id, "pull_request_number": number, **result}


@router.get("/swarms/{swarm_id}/blackboard")
def read_blackboard(swarm_id: int, category: str = "", task_id: int | None = None, after: int = 0, limit: int = 200):
    try:
        swarm_service.get_run(swarm_id)
        return swarm_service.blackboard(swarm_id, category=category, task_id=task_id, after=after, limit=limit)
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


@router.get("/swarm-agents/{task_id}")
def swarm_agent_detail(task_id: int):
    task = task_queue.get(task_id)
    if not task or not task.get("swarm_id"):
        raise HTTPException(404, "Swarm agent not found")
    project = _project(int(task["project_id"]))
    with connect() as conn:
        run = conn.execute(
            "SELECT * FROM agent_runs WHERE task_id=? ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        commands = [dict(row) for row in conn.execute(
            "SELECT id,command,output,exit_code,status,cwd,created_at,updated_at "
            "FROM command_runs WHERE task_id=? ORDER BY id DESC LIMIT 50",
            (task_id,),
        )]
    for item in commands:
        item["output"] = str(item.get("output") or "")[-20000:]
    board = swarm_service.blackboard(int(task["swarm_id"]), task_id=task_id, limit=100)
    worktree_summary = None
    changed_files: list[str] = []
    path = str(task.get("worktree_path") or "")
    branch = str(task.get("worktree_branch") or "")
    if path:
        try:
            worktree_summary = worktrees.summary(project, path)
        except ValueError:
            worktree_summary = {"path": path, "branch": branch, "unavailable": True}
    if branch:
        try:
            changed_files = integration.changed_files(project, branch)
        except ValueError:
            changed_files = []
    return {
        "task": swarm_service.list_agents(int(task["swarm_id"])) and next(
            (item for item in swarm_service.list_agents(int(task["swarm_id"])) if item["id"] == task_id),
            task,
        ),
        "run": dict(run) if run else None,
        "commands": commands,
        "blackboard": board,
        "changed_files": changed_files,
        "worktree": worktree_summary,
    }


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
