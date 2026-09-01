import subprocess
import time

from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.database import connect, now
from backend.app.main import app


def test_v03_git_terminal_and_summary_workflow(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, capture_output=True)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repository, check=True)
    (repository / "README.md").write_text("# Local project\n", encoding="utf-8")
    monkeypatch.setattr(settings, "data_root", data_root)

    with TestClient(app) as client:
        project = client.post("/api/projects", json={"path": str(repository)}).json()
        project_id = project["id"]

        profiles = client.get("/api/model-profiles").json()
        assert len(profiles) >= 3
        custom = client.post("/api/model-profiles", json={"name": "API test", "chat_model": "qwen-test", "embedding_model": "", "temperature": 0.3, "max_steps": 5, "context_files": 4, "context_chars": 12000})
        assert custom.status_code == 200
        configured = client.patch(f"/api/projects/{project_id}/settings", json={"model_profile_id": custom.json()["id"]}).json()
        assert configured["profile_name"] == "API test"
        cleared = client.patch(f"/api/projects/{project_id}/settings", json={"model_profile_id": None}).json()
        assert cleared["model_profile_id"] is None
        client.patch(f"/api/projects/{project_id}/settings", json={"model_profile_id": custom.json()["id"]})

        indexed = client.post(f"/api/projects/{project_id}/index").json()
        assert indexed["files"] == 1
        assert indexed["changed"] == 1
        assert client.post(f"/api/projects/{project_id}/index").json()["changed"] == 0

        staged = client.post(f"/api/projects/{project_id}/git/stage", json={"paths": ["README.md"]})
        assert staged.status_code == 200
        assert staged.json()["changes"][0]["staged"] is True
        committed = client.post(f"/api/projects/{project_id}/git/commit", json={"message": "Initial API commit"})
        assert committed.status_code == 200
        branched = client.post(f"/api/projects/{project_id}/git/branches", json={"name": "feature/v03", "checkout": True})
        assert branched.json()["branch"] == "feature/v03"

        proposed = client.post(f"/api/projects/{project_id}/git/operations", json={"action": "push", "remote": "origin", "branch": "feature/v03"})
        assert proposed.status_code == 200
        assert proposed.json()["status"] == "pending"
        approved = client.post(f"/api/projects/{project_id}/git/operations/{proposed.json()['id']}/approve")
        assert approved.status_code == 200
        assert approved.json()["status"] == "completed"

        started = client.post(f"/api/projects/{project_id}/terminal/start", json={"command": "read value; printf 'received:%s' \"$value\""}).json()
        run_id = started["id"]
        resized = client.post(f"/api/terminal/{run_id}/resize", json={"columns": 100, "rows": 30})
        assert resized.status_code == 200
        sent = client.post(f"/api/terminal/{run_id}/input", json={"data": "hello\n"})
        assert sent.status_code == 200
        terminal_state = {}
        for _ in range(40):
            terminal_state = client.get(f"/api/terminal/{run_id}").json()
            if terminal_state["status"] != "running":
                break
            time.sleep(0.05)
        assert terminal_state["status"] == "completed"
        assert "received:hello" in terminal_state["output"]

        session = client.get(f"/api/projects/{project_id}/sessions").json()[0]
        with connect() as conn:
            conn.execute("INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)", (session["id"], "user", "Add a health endpoint", now()))
            conn.execute("INSERT INTO messages(session_id,role,content,activities,created_at) VALUES(?,?,?,?,?)", (session["id"], "assistant", "Added the endpoint and tests pass", "[]", now()))
        summary = client.post(f"/api/sessions/{session['id']}/summary").json()
        assert "Add a health endpoint" in summary["summary"]
        assert client.get(f"/api/sessions/{session['id']}/summary").json()["summary"] == summary["summary"]
