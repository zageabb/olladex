from __future__ import annotations

import subprocess

from backend.app.config import settings
from backend.app.database import connect, init_db, now
from backend.app.services import task_queue, workspace, worktrees


def _git(root, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
    return completed.stdout.strip()


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Olladex Test")
    _git(repo, "config", "user.email", "olladex-test@example.invalid")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    return repo


def test_dependent_worktree_inherits_committed_specialist_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    repo = _repo(tmp_path)
    project = {
        "id": 1,
        "name": "Dependency handoff",
        "path": str(repo),
        "git_author_name": "Olladex Test",
        "git_author_email": "olladex-test@example.invalid",
    }

    first = worktrees.create_for_task(project, 1)
    first_project = worktrees.task_project(project, first["path"])
    first_file = workspace.project_root(first_project) / "TASK_TEST.md"
    first_file.write_text("created by task one\n", encoding="utf-8")
    committed = worktrees.commit_all(project, first["path"], "create task test")
    assert committed["sha"]

    second = worktrees.create_for_task(project, 2)
    handoff = worktrees.inherit_branches(project, second["path"], [first["branch"]])
    second_project = worktrees.task_project(project, second["path"])
    inherited = workspace.project_root(second_project) / "TASK_TEST.md"

    assert inherited.read_text(encoding="utf-8") == "created by task one\n"
    assert handoff["branch"] == second["branch"]
    assert first["branch"] != second["branch"]
    assert not (repo / "TASK_TEST.md").exists()


def test_lead_specialist_auto_commit_flows_into_dependent_task(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    repo = _repo(tmp_path)
    init_db()
    stamp = now()
    with connect() as conn:
        project_id = int(conn.execute(
            "INSERT INTO projects(name,path,model,git_author_name,git_author_email,created_at,last_opened_at) VALUES(?,?,?,?,?,?,?)",
            ("Queue handoff", str(repo), "qwen3:14b", "Olladex Test", "olladex-test@example.invalid", stamp, stamp),
        ).lastrowid)
        first_session = int(conn.execute(
            "INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (project_id, "Create file", stamp, stamp),
        ).lastrowid)
        second_session = int(conn.execute(
            "INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (project_id, "Verify file", stamp, stamp),
        ).lastrowid)

    first = task_queue.enqueue(
        project_id, first_session, "Create file", "create it",
        source_kind="lead_specialist", agent_role="worker",
    )
    second = task_queue.enqueue(
        project_id, second_session, "Verify file", "verify it",
        source_kind="lead_specialist", depends_on=[first["id"]], agent_role="tester",
    )

    project = {
        "id": project_id,
        "name": "Queue handoff",
        "path": str(repo),
        "git_author_name": "Olladex Test",
        "git_author_email": "olladex-test@example.invalid",
    }

    def handler(task: dict) -> str:
        if task["id"] == first["id"]:
            workspace.write_text(project, "TASK_TEST.md", "created by queued task one\n")
            return "created"
        return workspace.read_text(project, "TASK_TEST.md")

    monkeypatch.setattr(task_queue, "_handler", handler)
    assert task_queue.run_once() is True
    completed_first = task_queue.get(first["id"])
    assert completed_first["status"] == "completed"
    assert "auto-committed" in completed_first["result"]
    first_summary = worktrees.summary(project, completed_first["worktree_path"])
    assert first_summary["changes"] == []
    assert "TASK_TEST.md" in first_summary["branch_diff"]

    assert task_queue.run_once() is True
    completed_second = task_queue.get(second["id"])
    assert completed_second["status"] == "completed"
    assert "created by queued task one" in completed_second["result"]
    second_project = worktrees.task_project(project, completed_second["worktree_path"])
    assert workspace.read_text(second_project, "TASK_TEST.md") == "created by queued task one\n"
    assert not (repo / "TASK_TEST.md").exists()
