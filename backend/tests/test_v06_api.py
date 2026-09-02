import time

from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.main import app
from backend.app.services import github as github_service
from backend.app.services import ollama


def open_project(client, path):
    return client.post("/api/projects", json={"path": str(path)}).json()


def test_model_profile_full_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    repository = tmp_path / "repository"
    repository.mkdir()
    with TestClient(app) as client:
        project = open_project(client, repository)
        profiles = client.get("/api/model-profiles").json()
        assert client.delete(f"/api/model-profiles/{profiles[0]['id']}").status_code == 409
        rename = {key: profiles[0][key] for key in ("chat_model", "embedding_model", "temperature", "max_steps", "context_files", "context_chars")}
        assert client.put(f"/api/model-profiles/{profiles[0]['id']}", json={"name": "Renamed built-in", **rename}).status_code == 409
        created = client.post("/api/model-profiles", json={"name": "Custom", "chat_model": "coder", "embedding_model": "embed", "temperature": 0.2, "max_steps": 7, "context_files": 6, "context_chars": 16000}).json()
        updated = client.put(f"/api/model-profiles/{created['id']}", json={"name": "Custom updated", "chat_model": "coder-2", "embedding_model": "embed", "temperature": 0.1, "max_steps": 9, "context_files": 7, "context_chars": 18000})
        assert updated.status_code == 200
        assert updated.json()["max_steps"] == 9
        client.patch(f"/api/projects/{project['id']}/settings", json={"model_profile_id": created["id"]})
        assert client.delete(f"/api/model-profiles/{created['id']}").status_code == 200
        assert client.get(f"/api/projects/{project['id']}/settings").json()["model_profile_id"] is None


def test_background_task_runs_and_persists_session(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.setattr(ollama, "chat", lambda *args, **kwargs: ("Background work complete", []))
    with TestClient(app) as client:
        project = open_project(client, repository)
        created = client.post(f"/api/projects/{project['id']}/tasks", json={"prompt": "Inspect the project", "title": "Queued inspection"}).json()
        current = created
        for _ in range(50):
            current = client.get(f"/api/tasks/{created['id']}").json()
            if current["status"] in {"completed", "failed"}:
                break
            time.sleep(0.04)
        assert current["status"] == "completed"
        assert current["result"] == "Background work complete"
        messages = client.get(f"/api/sessions/{current['session_id']}/messages").json()
        assert [message["role"] for message in messages] == ["user", "assistant"]


def test_github_pr_requires_separate_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    repository = tmp_path / "repository"
    repository.mkdir()
    prepared = {"action": "create_pr", "repository": "owner/repo", "title": "Feature", "body": "Details", "head": "feature", "base": "main", "args": ["pr"], "command": "gh pr create --repo owner/repo"}
    monkeypatch.setattr(github_service, "status", lambda project: {"available": True, "authenticated": True, "repository": "owner/repo", "error": ""})
    monkeypatch.setattr(github_service, "issues", lambda project: [{"number": 1, "title": "Issue", "body": "", "url": "https://example.test/1", "labels": []}])
    monkeypatch.setattr(github_service, "prepare_pull_request", lambda project, title, body, base: {**prepared, "title": title, "body": body, "base": base})
    monkeypatch.setattr(github_service, "execute_pull_request", lambda project, operation: {"output": "https://github.com/owner/repo/pull/2", "url": "https://github.com/owner/repo/pull/2"})
    with TestClient(app) as client:
        project = open_project(client, repository)
        assert client.get(f"/api/projects/{project['id']}/github").json()["authenticated"] is True
        assert client.get(f"/api/projects/{project['id']}/github/issues").json()[0]["number"] == 1
        operation = client.post(f"/api/projects/{project['id']}/github/pull-requests", json={"title": "Feature", "body": "Details", "base": "main"}).json()
        assert operation["status"] == "pending"
        approved = client.post(f"/api/projects/{project['id']}/github/operations/{operation['id']}/approve")
        assert approved.status_code == 200
        assert approved.json()["status"] == "completed"
        assert client.post(f"/api/projects/{project['id']}/github/operations/{operation['id']}/approve").status_code == 409


def test_github_remote_slug_parsing(monkeypatch):
    monkeypatch.setattr(github_service.git, "_git", lambda project, *args: (0, "git@github.com:owner/example.git\n"))
    assert github_service.repository_slug({}) == "owner/example"
