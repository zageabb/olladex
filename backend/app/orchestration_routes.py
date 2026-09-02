from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .database import connect, now
from .services import task_queue, worktrees


router = APIRouter(prefix="/api", tags=["orchestration"])


class OrchestratedTaskRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)
    title: str = Field(default="", max_length=256)
    parent_task_id: int | None = None
    depends_on: list[int] = Field(default_factory=list)
    agent_role: str = Field(default="worker", min_length=1, max_length=80)


def _project(project_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return dict(row)


def _project_exists(project_id: int) -> None:
    _project(project_id)


def _create(project_id: int, body: OrchestratedTaskRequest, parent_override: int | None = None) -> dict:
    _project_exists(project_id)
    title = body.title.strip() or body.prompt.strip().splitlines()[0][:100]
    stamp = now()
    with connect() as conn:
        cursor = conn.execute("INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)", (project_id, title, stamp, stamp))
        session_id = cursor.lastrowid
    try:
        return task_queue.enqueue(
            project_id,
            session_id,
            title,
            body.prompt,
            source_kind="orchestrated",
            source_ref="",
            parent_task_id=parent_override if parent_override is not None else body.parent_task_id,
            depends_on=body.depends_on,
            agent_role=body.agent_role,
        )
    except ValueError as exc:
        with connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        raise HTTPException(409, str(exc)) from exc


@router.post("/projects/{project_id}/orchestration/tasks")
def create_orchestrated_task(project_id: int, body: OrchestratedTaskRequest):
    return _create(project_id, body)


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
            "id": task["id"],
            "title": task["title"],
            "status": task["status"],
            "agent_role": task.get("agent_role") or "worker",
            "parent_task_id": task.get("parent_task_id"),
            "depends_on": task.get("depends_on") or [],
            "children": by_parent.get(task["id"], []),
            "worktree_branch": task.get("worktree_branch") or "",
            "pr_number": task.get("pull_request_number") or 0,
            "pr_state": task.get("pull_request_state") or "",
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
            "id": task["id"],
            "title": task["title"],
            "agent_role": task.get("agent_role") or "worker",
            "status": task["status"],
            "depends_on": task.get("depends_on") or [],
            "worktree_branch": task.get("worktree_branch") or "",
            "pull_request_number": task.get("pull_request_number") or 0,
            "pull_request_state": task.get("pull_request_state") or "",
            "branch": branch_summary,
            "branch_error": branch_error,
        })
    return {"task_id": task_id, "base": base, "items": items}
