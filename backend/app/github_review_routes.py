from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .database import connect
from .services import github as github_service


router = APIRouter(prefix="/api/projects", tags=["github-review"])


class PullRequestCommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=100_000)


class PullRequestReviewRequest(BaseModel):
    event: str = Field(pattern="^(approve|comment|request-changes)$")
    body: str = Field(default="", max_length=100_000)


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


@router.get("/{project_id}/github/pull-requests/review")
def list_pull_requests(project_id: int, state: str = "open"):
    try:
        return github_service.pull_requests(_project(project_id), state)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{project_id}/github/pull-requests/{number}")
def get_pull_request(project_id: int, number: int):
    try:
        return github_service.pull_request(_project(project_id), number)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{project_id}/github/pull-requests/{number}/diff")
def get_pull_request_diff(project_id: int, number: int):
    try:
        return {"number": number, "diff": github_service.pull_request_diff(_project(project_id), number)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{project_id}/github/pull-requests/{number}/comments")
def comment_on_pull_request(project_id: int, number: int, body: PullRequestCommentRequest):
    try:
        return github_service.add_pull_request_comment(_project(project_id), number, body.body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{project_id}/github/pull-requests/{number}/reviews")
def review_pull_request(project_id: int, number: int, body: PullRequestReviewRequest):
    try:
        return github_service.submit_pull_request_review(_project(project_id), number, body.event, body.body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
