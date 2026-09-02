from __future__ import annotations

import json
import sqlite3
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


def _sync_builtin_defaults(previous_model: str, updated: dict) -> None:
    database_path = settings.database_path
    if not database_path.exists():
        return
    try:
        with sqlite3.connect(database_path) as conn:
            builtin_ids = [row[0] for row in conn.execute("SELECT id FROM model_profiles WHERE is_builtin=1")]
            conn.execute(
                "UPDATE model_profiles SET chat_model=?,embedding_model=?,updated_at=datetime('now') WHERE is_builtin=1",
                (updated["ollama_model"], updated["ollama_embedding_model"]),
            )
            if builtin_ids:
                placeholders = ",".join("?" for _ in builtin_ids)
                conn.execute(
                    f"UPDATE projects SET model=? WHERE model_profile_id IN ({placeholders})",
                    (updated["ollama_model"], *builtin_ids),
                )
            if previous_model:
                conn.execute(
                    "UPDATE projects SET model=? WHERE model_profile_id IS NULL AND model=?",
                    (updated["ollama_model"], previous_model),
                )
    except sqlite3.Error:
        # Runtime settings should remain usable even before/while the database is initialized.
        return


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
    previous_model = settings.ollama_model
    updated = apply(values)
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    _sync_builtin_defaults(previous_model, updated)
    return updated


def test_connection(
    url: str | None = None,
    model: str | None = None,
    embedding_model: str | None = None,
) -> dict:
    target = normalize_url(url) if url else settings.ollama_url.rstrip("/")
    selected_model = (model if model is not None else settings.ollama_model).strip()
    selected_embedding = (embedding_model if embedding_model is not None else settings.ollama_embedding_model).strip()
    try:
        response = httpx.get(f"{target}/api/tags", timeout=5.0)
        response.raise_for_status()
        payload = response.json()
        models = [item.get("name") or item.get("model") for item in payload.get("models", [])]
        models = [item for item in models if item]
        model_available = not selected_model or selected_model in models
        embedding_available = not selected_embedding or selected_embedding in models
        return {
            "connected": True,
            "url": target,
            "models": models,
            "selected_model": selected_model,
            "selected_embedding_model": selected_embedding,
            "model_available": model_available,
            "embedding_available": embedding_available,
        }
    except Exception as exc:
        return {
            "connected": False,
            "url": target,
            "models": [],
            "selected_model": selected_model,
            "selected_embedding_model": selected_embedding,
            "model_available": False,
            "embedding_available": False,
            "error": str(exc),
        }
