from __future__ import annotations

import json
import sqlite3

import pytest

from backend.app.config import settings
from backend.app.services import runtime_settings


def test_runtime_ollama_settings_persist_and_reload(tmp_path, monkeypatch):
    original = (settings.data_root, settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model)
    monkeypatch.setattr(settings, "data_root", tmp_path)
    try:
        saved = runtime_settings.save({
            "ollama_url": "http://192.168.1.249:11434/",
            "ollama_model": "qwen3:14b",
            "ollama_embedding_model": "nomic-embed-text",
        })
        assert saved["ollama_url"] == "http://192.168.1.249:11434"
        payload = json.loads((tmp_path / "app-settings.json").read_text())
        assert payload["ollama_url"] == "http://192.168.1.249:11434"

        settings.ollama_url = "http://127.0.0.1:11434"
        loaded = runtime_settings.load()
        assert loaded["ollama_url"] == "http://192.168.1.249:11434"
    finally:
        settings.data_root, settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model = original


def test_runtime_ollama_settings_sync_builtin_profiles_and_default_projects(tmp_path, monkeypatch):
    original = (settings.data_root, settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model)
    monkeypatch.setattr(settings, "data_root", tmp_path)
    settings.ollama_model = "qwen3:14b"
    settings.ollama_embedding_model = "nomic-embed-text"
    try:
        with sqlite3.connect(settings.database_path) as conn:
            conn.executescript("""
                CREATE TABLE model_profiles (id INTEGER PRIMARY KEY, chat_model TEXT, embedding_model TEXT, updated_at TEXT, is_builtin INTEGER);
                CREATE TABLE projects (id INTEGER PRIMARY KEY, model TEXT, model_profile_id INTEGER);
                INSERT INTO model_profiles VALUES (1, 'qwen3:14b', 'nomic-embed-text', '', 1);
                INSERT INTO model_profiles VALUES (2, 'custom:latest', '', '', 0);
                INSERT INTO projects VALUES (1, 'qwen3:14b', 1);
                INSERT INTO projects VALUES (2, 'qwen3:14b', NULL);
                INSERT INTO projects VALUES (3, 'custom:latest', 2);
            """)

        runtime_settings.save({
            "ollama_url": "http://192.168.1.249:11434",
            "ollama_model": "gemma3:12b",
            "ollama_embedding_model": "mxbai-embed-large:latest",
        })

        with sqlite3.connect(settings.database_path) as conn:
            builtin = conn.execute("SELECT chat_model,embedding_model FROM model_profiles WHERE id=1").fetchone()
            projects = conn.execute("SELECT id,model FROM projects ORDER BY id").fetchall()
        assert builtin == ("gemma3:12b", "mxbai-embed-large:latest")
        assert projects == [(1, "gemma3:12b"), (2, "gemma3:12b"), (3, "custom:latest")]
    finally:
        settings.data_root, settings.ollama_url, settings.ollama_model, settings.ollama_embedding_model = original


def test_runtime_ollama_connection_reports_selected_model_availability(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "gemma3:12b"}, {"name": "nomic-embed-text"}]}

    monkeypatch.setattr(runtime_settings.httpx, "get", lambda *args, **kwargs: Response())
    result = runtime_settings.test_connection(
        "http://192.168.1.249:11434",
        "gemma3:12b",
        "nomic-embed-text",
    )
    assert result["connected"] is True
    assert result["model_available"] is True
    assert result["embedding_available"] is True

    missing = runtime_settings.test_connection(
        "http://192.168.1.249:11434",
        "missing:model",
        "nomic-embed-text",
    )
    assert missing["model_available"] is False


def test_runtime_ollama_settings_reject_invalid_url():
    with pytest.raises(ValueError):
        runtime_settings.normalize_url("192.168.1.249:11434")
