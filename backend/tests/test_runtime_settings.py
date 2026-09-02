from __future__ import annotations

import json

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


def test_runtime_ollama_settings_reject_invalid_url():
    with pytest.raises(ValueError):
        runtime_settings.normalize_url("192.168.1.249:11434")
