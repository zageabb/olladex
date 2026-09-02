from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .database import connect, now
from .services import orchestration as orchestration_service
from .services import task_queue, worktrees


router = APIRouter(prefix="/api", tags=["orchestration"])


class OrchestratedTaskRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)
    title: str = Field(default="", max_length=256)
    parent_task_id: int | None = None
    depends_on: list[int] = Field(default_factory=list)
    agent_role: str = Field(default="worker", min_length=1, max_length=80)


class LeadOrchestrationRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=100_000)
    title: str = Field(default="", max_length=256)
    max_tasks: int = Field(default=6, ge=2, le=10)


def _project(project_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return dict(row)


def _project_exists(project_id: int) -> None:
    _project(project_id)


def _new_session(project_id: int, title: str) -> int:
    stamp = now()
    with connect() as conn:
        cursor = conn.execute("INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)", (project_id, title[:200], stamp, stamp))
        return int(cursor.lastrowid)


def _create(project_id: int, body: OrchestratedTaskRequest, parent_override: int | None = None) -> dict:
    _project_exists(project_id)
    title = body.title.strip() or body.prompt.strip().splitlines()[0][:100]
    session_id = _new_session(project_id, title)
    try:
        return task_queue.enqueue(
            project_id, session_id, title, body.prompt,
            source_kind="orchestrated", source_ref="",
            parent_task_id=parent_override if parent_override is not None else body.parent_task_id,
            depends_on=body.depends_on, agent_role=body.agent_role,
        )
    except ValueError as exc:
        with connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        raise HTTPException(409, str(exc)) from exc


@router.post("/projects/{project_id}/orchestration/tasks")
def create_orchestrated_task(project_id: int, body: OrchestratedTaskRequest):
    return _create(project_id, body)


@router.post("/projects/{project_id}/orchestration/lead")
def create_autonomous_lead(project_id: int, body: LeadOrchestrationRequest):
    project = _project(project_id)
    try:
        plan = orchestration_service.decompose(project, body.objective, body.max_tasks)
    except Exception as exc:
        raise HTTPException(502, f"Lead planning failed: {exc}") from exc
    title = body.title.strip() or body.objective.strip().splitlines()[0][:100]
    stamp = now()
    lead_session_id = _new_session(project_id, title)
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO background_tasks(project_id,session_id,title,prompt,source_kind,source_ref,status,parent_task_id,depends_on,agent_role,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, lead_session_id, title, body.objective, "lead_orchestration", "", "coordinating", None, "[]", "lead", stamp),
        )
        lead_id = int(cursor.lastrowid)
    child_ids: list[int] = []
    created: list[dict] = []
    try:
        for index, item in enumerate(plan):
            dependency_ids = [child_ids[dep] for dep in item.get("depends_on", []) if 0 <= dep < len(child_ids)]
            session_id = _new_session(project_id, item["title"])
            child = task_queue.enqueue(
                project_id, session_id, item["title"], item["prompt"],
                source_kind="lead_specialist", source_ref=f"lead:{lead_id}", parent_task_id=lead_id,
                depends_on=dependency_ids, agent_role=item["role"],
            )
            child_ids.append(child["id"])
            created.append(child)
        reviewer_title = f"Consolidate: {title}"[:256]
        reviewer_session = _new_session(project_id, reviewer_title)
        reviewer_prompt = (
            "Act as the lead reviewer for this coordinated implementation. Review all specialist hand-offs supplied below. "
            "Summarize what was implemented, identify conflicts or missing work, assess testing evidence, and give a concise integration/release recommendation. "
            "Do not invent results that are not present in the hand-offs."
        )
        reviewer = task_queue.enqueue(
            project_id, reviewer_session, reviewer_title, reviewer_prompt,
            source_kind="lead_consolidation", source_ref=f"lead:{lead_id}", parent_task_id=lead_id,
            depends_on=child_ids, agent_role="reviewer",
        )
    except Exception as exc:
        with connect() as conn:
            conn.execute("UPDATE background_tasks SET status='failed',error=?,completed_at=? WHERE id=?", (f"Could not create lead task graph: {exc}", now(), lead_id))
        raise HTTPException(409, str(exc)) from exc
    return {
        "lead": task_queue.get(lead_id),
        "specialists": created,
        "reviewer": reviewer,
        "plan": plan,
    }


@router.post("/tasks/{parent_task_id}/children")
def create_child_task(parent_task_id: int, body: OrchestratedTaskRequest):
    parent = task_queue.get(parent_task_id)
    if not parent:
        raise HTTPException(404, "Parent task not found")
    if body.parent_task_id is not None and body.parent_task_id != parent_task_id:
        raise HTTPException(409, "Child task parent does not match the route parent")
    return _create(parent["project_id"], body, parent_override=parent_task_id)


@router.get("/projects/{project_id}/orchestration")
def orchestration_graph(project_id: int):
    _project_exists(project_id)
    tasks = task_queue.list_for_project(project_id)
    by_parent: dict[int, list[int]] = {}
    for task in tasks:
        parent = task.get("parent_task_id")
        if parent:
            by_parent.setdefault(int(parent), []).append(task["id"])
    nodes = []
    for task in tasks:
        nodes.append({
            "id": task["id"], "title": task["title"], "status": task["status"],
            "agent_role": task.get("agent_role") or "worker", "parent_task_id": task.get("parent_task_id"),
            "depends_on": task.get("depends_on") or [], "children": by_parent.get(task["id"], []),
            "worktree_branch": task.get("worktree_branch") or "",
            "pr_number": task.get("pull_request_number") or 0, "pr_state": task.get("pull_request_state") or "",
            "result": task.get("result") or "", "error": task.get("error") or "",
        })
    return {"project_id": project_id, "nodes": nodes}


@router.get("/tasks/{task_id}/review-bundle")
def orchestration_review_bundle(task_id: int, base: str = "main"):
    root_task = task_queue.get(task_id)
    if not root_task:
        raise HTTPException(404, "Task not found")
    project = _project(root_task["project_id"])
    tasks = task_queue.list_for_project(root_task["project_id"])
    included = [root_task, *[task for task in tasks if task.get("parent_task_id") == task_id]]
    items = []
    for task in included:
        branch_summary = None
        branch_error = ""
        if task.get("worktree_path"):
            try:
                branch_summary = worktrees.summary(project, task["worktree_path"], base)
            except ValueError as exc:
                branch_error = str(exc)
        items.append({
            "id": task["id"], "title": task["title"], "agent_role": task.get("agent_role") or "worker",
            "status": task["status"], "depends_on": task.get("depends_on") or [],
            "worktree_branch": task.get("worktree_branch") or "",
            "pull_request_number": task.get("pull_request_number") or 0,
            "pull_request_state": task.get("pull_request_state") or "",
            "result": task.get("result") or "", "error": task.get("error") or "",
            "branch": branch_summary, "branch_error": branch_error,
        })
    return {"task_id": task_id, "base": base, "items": items}
