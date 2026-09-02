import subprocess
import threading
import time

from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.main import app


def make_repository(path):
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("# test\n", encoding="utf-8")


def test_background_job_parallel_limit_pause_resume_and_running_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    monkeypatch.setattr(settings, "agent_job_workers", 2)
    repository = tmp_path / "repo"
    make_repository(repository)
    finish = threading.Event()
    two_started = threading.Event()
    state_lock = threading.Lock()
    active = 0
    maximum = 0

    def fake_run(_session_id, _project, _content, checkpoint=None):
        nonlocal active, maximum
        with state_lock:
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                two_started.set()
        try:
            while not finish.is_set():
                if checkpoint:
                    checkpoint()
                time.sleep(0.01)
            if checkpoint:
                checkpoint()
            return {"id": None}
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr("backend.app.services.background_jobs.agent_runner.run", fake_run)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"path": str(repository)}).json()
        sessions = client.get(f"/api/projects/{project['id']}/sessions").json()
        sessions.extend([
            client.post(f"/api/projects/{project['id']}/sessions", json={"title": "Parallel two"}).json(),
            client.post(f"/api/projects/{project['id']}/sessions", json={"title": "Parallel three"}).json(),
        ])
        jobs = [
            client.post(f"/api/projects/{project['id']}/jobs", json={"session_id": session["id"], "prompt": f"Work {index}"}).json()
            for index, session in enumerate(sessions)
        ]
        assert two_started.wait(2)
        assert maximum == 2
        capacity = client.get(f"/api/projects/{project['id']}/jobs-capacity").json()
        assert capacity["workers"] == 2
        assert capacity["active"] == 2

        current = [client.get(f"/api/projects/{project['id']}/jobs/{job['id']}").json() for job in jobs]
        running = [job for job in current if job["status"] == "running"]
        queued = next(job for job in current if job["status"] == "queued")
        paused = client.post(f"/api/projects/{project['id']}/jobs/{running[0]['id']}/pause")
        assert paused.status_code == 200
        assert paused.json()["status"] == "paused"
        resumed = client.post(f"/api/projects/{project['id']}/jobs/{running[0]['id']}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "running"
        cancelled = client.delete(f"/api/projects/{project['id']}/jobs/{queued['id']}")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        running_cancel = client.delete(f"/api/projects/{project['id']}/jobs/{running[1]['id']}")
        assert running_cancel.status_code == 200
        assert running_cancel.json()["status"] == "cancelled"
        finish.set()
        for _ in range(200):
            states = [client.get(f"/api/projects/{project['id']}/jobs/{job['id']}").json()["status"] for job in jobs]
            if all(status in {"completed", "cancelled", "failed"} for status in states):
                break
            time.sleep(0.01)
        assert states.count("completed") == 1
        assert states.count("cancelled") == 2
