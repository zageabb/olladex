from typing import Any, Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    path: str
    name: str | None = None
    model: str | None = None


class SessionCreate(BaseModel):
    title: str = "New task"


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


class CommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=4_000)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)


class TerminalInputRequest(BaseModel):
    data: str = Field(min_length=1, max_length=10_000)


class FileWriteRequest(BaseModel):
    content: str
    session_id: int | None = None


class ChangeApplyRequest(BaseModel):
    hunk_indexes: list[int] | None = None


class ProjectSettingsRequest(BaseModel):
    model: str | None = None
    approval_mode: Literal["review", "assisted", "autonomous"] | None = None
    instructions: str | None = Field(default=None, max_length=100_000)
    git_author_name: str | None = Field(default=None, min_length=1, max_length=200)
    git_author_email: str | None = Field(default=None, min_length=3, max_length=320)


class GitPathsRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=200)


class GitBranchRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    checkout: bool = True


class GitCheckoutRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class GitCommitRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5_000)


class DiagramRequest(BaseModel):
    engine: Literal["mermaid", "dot"]
    source: str = Field(min_length=1, max_length=200_000)


class OfficeCreateRequest(BaseModel):
    kind: Literal["docx", "xlsx", "pptx"]
    path: str
    title: str = "Untitled"
    content: str = ""
    data: list[list[Any]] = []
