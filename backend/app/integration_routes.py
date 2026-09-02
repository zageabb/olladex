from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .database import connect
from .services import github as github_service
from .services import integration, task_queue, worktrees


router = APIRouter(prefix="/api/tasks", tags=["integration"])


class IntegrationSelectionRequest(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=20)
    base: str = Field(default="main", min_length=1, max_length=200)


class IntegrationChecksRequest(BaseModel):
    command: str = Field(min_length=1, max_length=5000)


class IntegrationPushRequest(BaseModel):
    remote: str = Field(default="origin", min_length=1, max_length=120)


class IntegrationPullRequestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(default="", max_length=100_000)
    base: str = Field(default="main", min_length=1, max_length=200)


def _lead(task_id: int) -> tuple[dict, dict]:
    task = task_queue.get(task_id)
    if not task:
        raise HTTPException(404, "Lead task not found")
    if (task.get("agent_role") or "") != "lead":
        raise HTTPException(409, "Integration is only available for lead tasks")
    with connect() as conn:
        project = conn.execute("SELECT * FROM projects WHERE id=?", (task["project_id"],)).fetchone()
    if not project:
        raise HTTPException(404, "Project not found")
    return task, dict(project)


def _selected_branches(lead: dict, task_ids: list[int]) -> list[str]:
    tasks = {task["id"]: task for task in task_queue.list_for_project(lead["project_id"])}
    branches: list[str] = []
    for task_id in task_ids:
        task = tasks.get(task_id)
        if not task or task.get("parent_task_id") != lead["id"]:
            raise HTTPException(409, f"Task #{task_id} is not a child of lead task #{lead['id']}")
        if task.get("agent_role") == "reviewer":
            continue
        if task.get("status") != "completed":
            raise HTTPException(409, f"Task #{task_id} is not completed")
        branch = task.get("worktree_branch") or ""
        path = task.get("worktree_path") or ""
        if not branch or not path:
            raise HTTPException(409, f"Task #{task_id} does not have an available worktree branch")
        try:
            summary = worktrees.summary(_project_for(lead["project_id"]), path)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if summary.get("changes"):
            raise HTTPException(409, f"Task #{task_id} still has uncommitted changes")
        branches.append(branch)
    if not branches:
        raise HTTPException(409, "Select at least one completed specialist task")
    return branches


def _project_for(project_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return dict(row)


def _pr_number(url: str) -> int:
    match = re.search(r"/pull/(\d+)(?:\b|/|$)", url or "")
    return int(match.group(1)) if match else 0


@router.post("/{lead_task_id}/integration/preflight")
def integration_preflight(lead_task_id: int, body: IntegrationSelectionRequest):
    lead, project = _lead(lead_task_id)
    branches = _selected_branches(lead, body.task_ids)
    try:
        return {"lead_task_id": lead_task_id, "task_ids": body.task_ids, **integration.preflight(project, branches, body.base)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{lead_task_id}/integration")
def create_integration(lead_task_id: int, body: IntegrationSelectionRequest):
    lead, project = _lead(lead_task_id)
    branches = _selected_branches(lead, body.task_ids)
    try:
        result = integration.create(project, lead_task_id, branches, body.base)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET integration_path=?,integration_branch=?,integration_check_command='',integration_check_status='',integration_check_output='',integration_pr_number=0,integration_pr_url='',integration_pr_state='' WHERE id=?",
            (result["path"], result["branch"], lead_task_id),
        )
    return {"lead_task_id": lead_task_id, "task_ids": body.task_ids, **result}


@router.get("/{lead_task_id}/integration")
def get_integration(lead_task_id: int, base: str = "main"):
    lead, project = _lead(lead_task_id)
    path = lead.get("integration_path") or ""
    if not path:
        return {
            "lead_task_id": lead_task_id, "path": "", "branch": "", "base": base,
            "check_command": lead.get("integration_check_command") or "", "check_status": lead.get("integration_check_status") or "",
            "check_output": lead.get("integration_check_output") or "", "pull_request_number": lead.get("integration_pr_number") or 0,
            "pull_request_url": lead.get("integration_pr_url") or "", "pull_request_state": lead.get("integration_pr_state") or "",
        }
    try:
        summary = integration.summary(project, path, base)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "lead_task_id": lead_task_id, **summary,
        "check_command": lead.get("integration_check_command") or "", "check_status": lead.get("integration_check_status") or "",
        "check_output": lead.get("integration_check_output") or "", "pull_request_number": lead.get("integration_pr_number") or 0,
        "pull_request_url": lead.get("integration_pr_url") or "", "pull_request_state": lead.get("integration_pr_state") or "",
    }


@router.post("/{lead_task_id}/integration/checks")
def run_integration_checks(lead_task_id: int, body: IntegrationChecksRequest):
    lead, project = _lead(lead_task_id)
    path = lead.get("integration_path") or ""
    if not path:
        raise HTTPException(409, "Create an integration worktree first")
    try:
        result = integration.run_checks(project, path, body.command)
    except (ValueError, TimeoutError) as exc:
        raise HTTPException(409, str(exc)) from exc
    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET integration_check_command=?,integration_check_status=?,integration_check_output=? WHERE id=?",
            (body.command, "passed" if result["passed"] else "failed", result["output"], lead_task_id),
        )
    return {"lead_task_id": lead_task_id, **result}


@router.post("/{lead_task_id}/integration/push")
def push_integration(lead_task_id: int, body: IntegrationPushRequest):
    lead, project = _lead(lead_task_id)
    path = lead.get("integration_path") or ""
    if not path:
        raise HTTPException(409, "Create an integration worktree first")
    if lead.get("integration_check_status") != "passed":
        raise HTTPException(409, "Combined checks must pass before pushing the integration branch")
    try:
        return {"lead_task_id": lead_task_id, **integration.push(project, path, body.remote)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{lead_task_id}/integration/pull-request")
def create_integration_pull_request(lead_task_id: int, body: IntegrationPullRequestRequest):
    lead, project = _lead(lead_task_id)
    path = lead.get("integration_path") or ""
    if not path:
        raise HTTPException(409, "Create an integration worktree first")
    if lead.get("integration_check_status") != "passed":
        raise HTTPException(409, "Combined checks must pass before creating the integration pull request")
    target_project = integration.integration_project(project, path)
    try:
        prepared = github_service.prepare_pull_request(target_project, body.title, body.body, body.base)
        result = github_service.execute_pull_request(target_project, prepared)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    number = _pr_number(result.get("url", ""))
    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET integration_pr_number=?,integration_pr_url=?,integration_pr_state='OPEN' WHERE id=?",
            (number, result.get("url", ""), lead_task_id),
        )
    return {"lead_task_id": lead_task_id, "pull_request_number": number, **result}
