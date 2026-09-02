from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import httpx

from ..config import settings


def _settings_path() -> Path:
    return settings.data_root / "app-settings.json"


def normalize_url(value: str) -> str:
    url = value.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Enter a valid Ollama URL, for example http://192.168.1.249:11434")
    return url


def current() -> dict:
    return {
        "ollama_url": settings.ollama_url,
        "ollama_model": settings.ollama_model,
        "ollama_embedding_model": settings.ollama_embedding_model,
    }


def apply(values: dict) -> dict:
    if values.get("ollama_url"):
        settings.ollama_url = normalize_url(str(values["ollama_url"]))
    if "ollama_model" in values:
        settings.ollama_model = str(values.get("ollama_model") or "").strip()
    if "ollama_embedding_model" in values:
        settings.ollama_embedding_model = str(values.get("ollama_embedding_model") or "").strip()
    return current()


def load() -> dict:
    path = _settings_path()
    if not path.exists():
        return current()
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(values, dict):
            return apply(values)
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return current()


def save(values: dict) -> dict:
    updated = apply(values)
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return updated


def test_connection(url: str | None = None) -> dict:
    target = normalize_url(url) if url else settings.ollama_url.rstrip("/")
    try:
        response = httpx.get(f"{target}/api/tags", timeout=5.0)
        response.raise_for_status()
        payload = response.json()
        models = [item.get("name") or item.get("model") for item in payload.get("models", [])]
        models = [item for item in models if item]
        return {"connected": True, "url": target, "models": models}
    except Exception as exc:
        return {"connected": False, "url": target, "models": [], "error": str(exc)}
