from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .database import connect
from .services import development_state, git


router = APIRouter(prefix="/api", tags=["development"])


class DevelopmentModeRequest(BaseModel):
    mode: str = Field(min_length=1, max_length=32)


class DevelopmentContinueRequest(BaseModel):
    profile_id: int
    max_agents: int | None = Field(default=None, ge=2, le=20)
    max_concurrency: int | None = Field(default=None, ge=1, le=8)


def _project(project_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return dict(row)


def _response(project: dict, action: str) -> dict:
    return development_state.action_report(project, action)


@router.get("/projects/{project_id}/development-state")
def get_development_state(project_id: int):
    project = _project(project_id)
    state = development_state.snapshot(project)
    return {
        "project_id": project_id,
        "current_objective": state.get("current_objective") or "",
        "current_item": state.get("current_item"),
        "items": state.get("items") or [],
        "agents_present": state["agents_present"],
        "development_present": state["development_present"],
        "development_mode": development_state.normalise_mode(project.get("development_mode") or "build"),
        "available_modes": development_state.DEVELOPMENT_MODES,
        "git": git.summary(project),
    }


@router.post("/projects/{project_id}/development-actions/{action}")
def run_development_action(project_id: int, action: str):
    project = _project(project_id)
    try:
        return _response(project, action.strip().lower().lstrip("/"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/projects/{project_id}/development-mode")
def update_development_mode(project_id: int, body: DevelopmentModeRequest):
    project = _project(project_id)
    try:
        mode = development_state.normalise_mode(body.mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with connect() as conn:
        conn.execute("UPDATE projects SET development_mode=? WHERE id=?", (mode, project_id))
    return {
        "project_id": project_id,
        "development_mode": mode,
        "description": development_state.DEVELOPMENT_MODES[mode],
    }


@router.get("/projects/{project_id}/development-evidence")
def get_development_evidence(project_id: int):
    project = _project(project_id)
    return development_state.evidence_report(project)


@router.post("/projects/{project_id}/development-actions/continue/start")
def start_current_development_item(project_id: int, body: DevelopmentContinueRequest):
    project = _project(project_id)
    state = development_state.snapshot(project)
    current = state.get("current_item")
    if not current:
        raise HTTPException(409, "No incomplete DEVELOPMENT.md item is available to continue")
    mode = development_state.normalise_mode(project.get("development_mode") or "build")
    if mode in {"explore", "plan", "verify"}:
        raise HTTPException(409, f"Development mode '{mode}' does not permit implementation execution")
    objective = "\n\n".join(
        part for part in (
            state.get("current_objective") or "",
            f"Continue {current['key']} — {current['title']}.",
            current.get("body") or "",
            (
                "Continue autonomously until the current objective is verified complete, "
                "a genuinely ambiguous product decision is required, progress is blocked outside the repository, "
                "or continuing would risk destructive changes. Do not stop merely because one implementation step completed."
                if mode == "autonomous" else ""
            ),
        )
        if part
    )
    from .services import swarm as swarm_service
    readiness = swarm_service.preflight(
        project_id,
        body.profile_id,
        max_agents=body.max_agents,
        max_concurrency=body.max_concurrency,
    )
    if not readiness.get("ready"):
        failures = "; ".join(
            str(item.get("detail") or item.get("name") or "preflight failed")
            for item in readiness.get("checks") or []
            if not item.get("ok")
        )
        raise HTTPException(409, "Advanced orchestration preflight failed: " + (failures or "unknown readiness failure"))

    from .swarm_routes import SwarmCreateRequest, create_swarm
    result = create_swarm(
        project_id,
        SwarmCreateRequest(
            objective=objective,
            title=f"{current['key']}: {current['title']}",
            profile_id=body.profile_id,
            max_agents=body.max_agents,
            max_concurrency=body.max_concurrency,
        ),
    )
    swarm_id = int((result.get("swarm") or {}).get("id") or 0)
    if swarm_id:
        with connect() as conn:
            conn.execute(
                "UPDATE swarm_runs SET development_item_key=? WHERE id=?",
                (current["key"], swarm_id),
            )
        result["swarm"]["development_item_key"] = current["key"]
    return result



@router.post("/projects/{project_id}/development-actions/merge/start")
def merge_current_development_item(project_id: int):
    project = _project(project_id)
    mode = development_state.normalise_mode(project.get("development_mode") or "build")
    if mode not in {"autonomous", "release"}:
        raise HTTPException(409, "Merge execution requires Autonomous or Release development mode")
    report = development_state.merge_report(project)
    if not report.get("ready"):
        raise HTTPException(
            409,
            "Release gate is blocked: " + "; ".join(report.get("blockers") or ["evidence incomplete"]),
        )
    linked = report.get("linked_swarm") or {}
    swarm_id = int(linked.get("id") or 0)
    if not swarm_id:
        raise HTTPException(
            409,
            "No DEVELOPMENT.md-linked Advanced orchestration integration is available for deterministic promotion",
        )
    from .swarm_routes import SwarmPromotionRequest, promote_swarm_integration
    return promote_swarm_integration(
        swarm_id,
        SwarmPromotionRequest(target_branch=report.get("target_branch") or "main"),
    )
