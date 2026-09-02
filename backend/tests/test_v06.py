import subprocess
import time

from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.main import app
from backend.app.services import github, ollama


def make_repository(path, remote="https://github.com/example/olladex-test.git"):
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# test\n", encoding="utf-8")


def test_background_jobs_and_profile_management(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    monkeypatch.setattr(ollama, "chat", lambda project, history, **kwargs: ("Background work complete", []))
    repository = tmp_path / "repo"
    make_repository(repository)

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"path": str(repository)}).json()
        session = client.get(f"/api/projects/{project['id']}/sessions").json()[0]
        created = client.post(f"/api/projects/{project['id']}/jobs", json={"session_id": session["id"], "prompt": "Inspect the project"})
        assert created.status_code == 200
        job = created.json()
        for _ in range(100):
            job = client.get(f"/api/projects/{project['id']}/jobs/{job['id']}").json()
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        assert job["status"] == "completed"
        assert job["result_message_id"]
        messages = client.get(f"/api/sessions/{session['id']}/messages").json()
        assert messages[-1]["content"] == "Background work complete"

        profile = client.post("/api/model-profiles", json={"name": "Editable", "chat_model": "qwen", "embedding_model": "embed", "temperature": 0.2, "max_steps": 7, "context_files": 5, "context_chars": 16000}).json()
        updated = client.patch(f"/api/model-profiles/{profile['id']}", json={"name": "Edited", "chat_model": "qwen-new", "embedding_model": "embed", "temperature": 0.1, "max_steps": 9, "context_files": 6, "context_chars": 18000})
        assert updated.status_code == 200
        assert updated.json()["chat_model"] == "qwen-new"
        assert client.delete(f"/api/model-profiles/{profile['id']}").json()["deleted"] is True
        built_in = next(item for item in client.get("/api/model-profiles").json() if item["name"] == "Balanced local")
        assert client.delete(f"/api/model-profiles/{built_in['id']}").status_code == 409


def test_github_overview_issue_and_reviewed_pull_request(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    monkeypatch.setattr(settings, "github_token", "test-token")
    repository = tmp_path / "repo"
    make_repository(repository)
    requests = []

    def fake_request(method, path, **kwargs):
        requests.append((method, path, kwargs))
        if path.endswith("/issues"):
            return [{"number": 12, "title": "Add health check", "body": "Create an endpoint", "html_url": "https://github.com/example/olladex-test/issues/12", "labels": [{"name": "enhancement"}]}]
        if path.endswith("/pulls") and method == "GET":
            return []
        if path.endswith("/issues/12"):
            return {"number": 12, "title": "Add health check", "body": "Create an endpoint", "html_url": "https://github.com/example/olladex-test/issues/12"}
        if path.endswith("/pulls") and method == "POST":
            return {"number": 4, "html_url": "https://github.com/example/olladex-test/pull/4", "state": "open", "title": kwargs["json"]["title"]}
        raise AssertionError((method, path))

    monkeypatch.setattr(github, "_request", fake_request)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"path": str(repository)}).json()
        overview = client.get(f"/api/projects/{project['id']}/github")
        assert overview.status_code == 200
        assert overview.json()["repository"] == "example/olladex-test"
        assert overview.json()["issues"][0]["number"] == 12

        proposal = client.post(f"/api/projects/{project['id']}/github/pull-requests", json={"title": "Health endpoint", "body": "Implements #12", "head": "feature/health", "base": "main", "draft": True})
        assert proposal.status_code == 200
        assert proposal.json()["status"] == "pending"
        approved = client.post(f"/api/projects/{project['id']}/github/operations/{proposal.json()['id']}/approve")
        assert approved.status_code == 200
        assert approved.json()["result"]["number"] == 4
        assert any(method == "POST" and path.endswith("/pulls") for method, path, _ in requests)
