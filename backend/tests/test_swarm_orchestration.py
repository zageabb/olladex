from __future__ import annotations

import json

from backend.app.services import orchestration


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, path, json=None):
        return _Response(self._payload)


def test_swarm_decomposition_keeps_specialist_roles_and_rejects_reviewer(monkeypatch):
    payload = {
        "message": {
            "content": json.dumps({
                "tasks": [
                    {"title": "Architecture", "role": "architect", "prompt": "Map the architecture", "depends_on": []},
                    {"title": "Duplicate reviewer", "role": "reviewer", "prompt": "Review too early", "depends_on": [0]},
                ]
            })
        }
    }
    monkeypatch.setattr(orchestration.workspace, "repository_intelligence", lambda project: {"frameworks": []})
    monkeypatch.setattr(orchestration.ollama, "client", lambda timeout=120: _Client(payload))

    tasks = orchestration.decompose({"model": "test"}, "Improve the project", 4, swarm_mode=True)

    assert tasks[0]["role"] == "architect"
    assert tasks[1]["role"] == "worker"
    assert tasks[1]["depends_on"] == [0]
