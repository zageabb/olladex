from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .database import connect
from .services import github as github_service
from .services import task_queue, worktrees


router = APIRouter(prefix="/api/tasks", tags=["task-worktrees"])


class TaskCommitRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5_000)


class TaskPushRequest(BaseModel):
    remote: str = Field(default="origin", min_length=1, max_length=120)


class TaskPullRequestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(default="", max_length=100_000)
    base: str = Field(default="main", min_length=1, max_length=200)


class TaskCleanupRequest(BaseModel):
    force: bool = False


def _project(project_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT p.*,mp.name AS profile_name,mp.chat_model AS profile_chat_model,"
            "mp.embedding_model AS profile_embedding_model,mp.temperature AS profile_temperature,"
            "mp.max_steps AS profile_max_steps,mp.context_files AS profile_context_files,"
            "mp.context_chars AS profile_context_chars "
            "FROM projects p LEFT JOIN model_profiles mp ON mp.id=p.model_profile_id WHERE p.id=?",
            (project_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return dict(row)


def _task(task_id: int) -> tuple[dict, dict]:
    task = task_queue.get(task_id)
    if not task:
        raise HTTPException(404, "Background task not found")
    if not task.get("worktree_path"):
        raise HTTPException(409, "This task does not have an isolated Git worktree")
    return task, _project(task["project_id"])


@router.get("/{task_id}/worktree")
def task_worktree(task_id: int, base: str = "main"):
    task, project = _task(task_id)
    try:
        return {"task_id": task_id, **worktrees.summary(project, task["worktree_path"], base)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{task_id}/worktree/commit")
def commit_task_worktree(task_id: int, body: TaskCommitRequest):
    task, project = _task(task_id)
    try:
        return {"task_id": task_id, **worktrees.commit_all(project, task["worktree_path"], body.message)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{task_id}/worktree/push")
def push_task_worktree(task_id: int, body: TaskPushRequest):
    task, project = _task(task_id)
    try:
        return {"task_id": task_id, **worktrees.push(project, task["worktree_path"], body.remote)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{task_id}/worktree/pull-request")
def create_task_pull_request(task_id: int, body: TaskPullRequestRequest):
    task, project = _task(task_id)
    task_project = worktrees.task_project(project, task["worktree_path"])
    try:
        prepared = github_service.prepare_pull_request(task_project, body.title, body.body, body.base)
        result = github_service.execute_pull_request(task_project, prepared)
        return {"task_id": task_id, "branch": task.get("worktree_branch", ""), **result}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{task_id}/worktree/cleanup")
def cleanup_task_worktree(task_id: int, body: TaskCleanupRequest):
    task, project = _task(task_id)
    if task.get("status") in {"queued", "running"}:
        raise HTTPException(409, "Running or queued task worktrees cannot be removed")
    try:
        summary = worktrees.summary(project, task["worktree_path"])
        if not body.force and summary.get("changes"):
            raise ValueError("Task worktree still has uncommitted changes; commit them or use force cleanup")
        result = worktrees.remove(project, task["worktree_path"], task.get("worktree_branch", ""), force=body.force)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    with connect() as conn:
        conn.execute("UPDATE background_tasks SET worktree_path='',worktree_branch='' WHERE id=?", (task_id,))
    return {"task_id": task_id, **result}
