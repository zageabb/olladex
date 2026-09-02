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


class AgentJobRequest(BaseModel):
    session_id: int = Field(ge=1)
    prompt: str = Field(min_length=1, max_length=100_000)
    source: str = Field(default="manual", min_length=1, max_length=80)


class CommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=4_000)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)


class TerminalInputRequest(BaseModel):
    data: str = Field(min_length=1, max_length=10_000)


class TerminalResizeRequest(BaseModel):
    columns: int = Field(ge=20, le=500)
    rows: int = Field(ge=5, le=200)


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
    model_profile_id: int | None = Field(default=None, ge=1)


class ModelProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    chat_model: str = Field(min_length=1, max_length=200)
    embedding_model: str = Field(default="", max_length=200)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_steps: int = Field(default=8, ge=1, le=30)
    context_files: int = Field(default=8, ge=1, le=30)
    context_chars: int = Field(default=32000, ge=4000, le=200000)


class GitPathsRequest(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=200)


class GitBranchRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    checkout: bool = True


class GitCheckoutRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class GitCommitRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5_000)


class GitRemoteOperationRequest(BaseModel):
    action: Literal["fetch", "pull", "push"]
    remote: str = Field(default="origin", min_length=1, max_length=120)
    branch: str | None = Field(default=None, max_length=120)


class GitHubPullRequestRequest(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    body: str = Field(default="", max_length=100_000)
    head: str = Field(min_length=1, max_length=120)
    base: str = Field(default="main", min_length=1, max_length=120)
    draft: bool = False


class DiagramRequest(BaseModel):
    engine: Literal["mermaid", "dot"]
    source: str = Field(min_length=1, max_length=200_000)


class OfficeCreateRequest(BaseModel):
    kind: Literal["docx", "xlsx", "pptx"]
    path: str
    title: str = "Untitled"
    content: str = ""
    data: list[list[Any]] = []
