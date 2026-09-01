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


class FileWriteRequest(BaseModel):
    content: str
    session_id: int | None = None


class DiagramRequest(BaseModel):
    engine: Literal["mermaid", "dot"]
    source: str = Field(min_length=1, max_length=200_000)


class OfficeCreateRequest(BaseModel):
    kind: Literal["docx", "xlsx", "pptx"]
    path: str
    title: str = "Untitled"
    content: str = ""
    data: list[list[Any]] = []

