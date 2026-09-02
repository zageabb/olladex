from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .services import runtime_settings

router = APIRouter()


class OllamaSettingsRequest(BaseModel):
    ollama_url: str
    ollama_model: str = ""
    ollama_embedding_model: str = ""


class OllamaTestRequest(BaseModel):
    ollama_url: str | None = None


@router.get("/api/settings/ollama")
def get_ollama_settings():
    configured = runtime_settings.current()
    return {**configured, **runtime_settings.test_connection(configured["ollama_url"])}


@router.put("/api/settings/ollama")
def update_ollama_settings(body: OllamaSettingsRequest):
    try:
        configured = runtime_settings.save(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {**configured, **runtime_settings.test_connection(configured["ollama_url"])}


@router.post("/api/settings/ollama/test")
def test_ollama_settings(body: OllamaTestRequest):
    try:
        return runtime_settings.test_connection(body.ollama_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
