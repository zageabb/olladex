from __future__ import annotations

import re

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


class TaskLifecycleRequest(BaseModel):
    cleanup_merged: bool = True


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


def _task_record(task_id: int) -> dict:
    task = task_queue.get(task_id)
    if not task:
        raise HTTPException(404, "Background task not found")
    return task


def _task(task_id: int) -> tuple[dict, dict]:
    task = _task_record(task_id)
    if not task.get("worktree_path"):
        raise HTTPException(409, "This task does not have an isolated Git worktree")
    return task, _project(task["project_id"])


def _check_summary(checks: list[dict] | None) -> dict:
    items = checks or []
    failing = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
    pending = {"QUEUED", "IN_PROGRESS", "PENDING", "WAITING", "REQUESTED"}
    states: list[dict] = []
    for item in items:
        conclusion = str(item.get("conclusion") or item.get("state") or item.get("status") or "UNKNOWN").upper()
        name = str(item.get("name") or item.get("context") or item.get("workflowName") or "Check")
        states.append({"name": name, "state": conclusion})
    if any(item["state"] in failing for item in states):
        overall = "failing"
    elif any(item["state"] in pending for item in states):
        overall = "pending"
    elif states:
        overall = "passing"
    else:
        overall = "none"
    return {"overall": overall, "checks": states}


def _pr_number(url: str) -> int:
    match = re.search(r"/pull/(\d+)(?:\b|/|$)", url or "")
    return int(match.group(1)) if match else 0


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
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    number = _pr_number(result.get("url", ""))
    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET pull_request_number=?,pull_request_url=?,pull_request_state='OPEN' WHERE id=?",
            (number, result.get("url", ""), task_id),
        )
    return {"task_id": task_id, "branch": task.get("worktree_branch", ""), "pull_request_number": number, **result}


@router.post("/{task_id}/lifecycle")
def sync_task_lifecycle(task_id: int, body: TaskLifecycleRequest):
    task = _task_record(task_id)
    project = _project(task["project_id"])
    number = int(task.get("pull_request_number") or 0)
    if not number:
        return {
            "task_id": task_id,
            "pull_request_number": 0,
            "pull_request_url": task.get("pull_request_url", ""),
            "pull_request_state": task.get("pull_request_state", ""),
            "checks": {"overall": "none", "checks": []},
            "worktree_cleaned": False,
        }
    try:
        pr = github_service.pull_request(project, number)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    state = str(pr.get("state") or "").upper()
    url = str(pr.get("url") or task.get("pull_request_url") or "")
    checks = _check_summary(pr.get("statusCheckRollup"))
    cleaned = False
    cleanup_blocked = ""
    if body.cleanup_merged and state == "MERGED" and task.get("worktree_path"):
        try:
            summary = worktrees.summary(project, task["worktree_path"])
            if summary.get("changes"):
                cleanup_blocked = "Merged task worktree still has uncommitted changes"
            else:
                worktrees.remove(project, task["worktree_path"], task.get("worktree_branch", ""), force=False)
                cleaned = True
        except ValueError as exc:
            cleanup_blocked = str(exc)
    with connect() as conn:
        if cleaned:
            conn.execute(
                "UPDATE background_tasks SET pull_request_url=?,pull_request_state=?,worktree_path='',worktree_branch='' WHERE id=?",
                (url, state, task_id),
            )
        else:
            conn.execute(
                "UPDATE background_tasks SET pull_request_url=?,pull_request_state=? WHERE id=?",
                (url, state, task_id),
            )
    return {
        "task_id": task_id,
        "pull_request_number": number,
        "pull_request_url": url,
        "pull_request_state": state,
        "review_decision": pr.get("reviewDecision") or "",
        "mergeable": pr.get("mergeable") or "",
        "checks": checks,
        "worktree_cleaned": cleaned,
        "cleanup_blocked": cleanup_blocked,
    }


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
