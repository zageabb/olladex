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
    ollama_model: str | None = None
    ollama_embedding_model: str | None = None


@router.get("/api/settings/ollama")
def get_ollama_settings():
    configured = runtime_settings.current()
    return {
        **configured,
        **runtime_settings.test_connection(
            configured["ollama_url"],
            configured["ollama_model"],
            configured["ollama_embedding_model"],
        ),
    }


@router.put("/api/settings/ollama")
def update_ollama_settings(body: OllamaSettingsRequest):
    try:
        probe = runtime_settings.test_connection(body.ollama_url, body.ollama_model, body.ollama_embedding_model)
        if not probe.get("connected"):
            raise HTTPException(400, probe.get("error") or "Ollama server is not reachable")
        if body.ollama_model and not probe.get("model_available"):
            raise HTTPException(400, f"Chat model '{body.ollama_model}' is not installed on this Ollama server")
        if body.ollama_embedding_model and not probe.get("embedding_available"):
            raise HTTPException(400, f"Embedding model '{body.ollama_embedding_model}' is not installed on this Ollama server")
        configured = runtime_settings.save(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {**configured, **probe}


@router.post("/api/settings/ollama/test")
def test_ollama_settings(body: OllamaTestRequest):
    try:
        return runtime_settings.test_connection(body.ollama_url, body.ollama_model, body.ollama_embedding_model)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
