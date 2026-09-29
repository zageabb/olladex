from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.app import swarm_routes
from backend.app.config import settings
from backend.app.database import connect, init_db, now
from backend.app.services import conversation_runtime, swarm, swarm_coordinator, swarm_finalization, task_queue, worktrees


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def _seed(tmp_path, monkeypatch, objective: str = "Create main.py"):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    init_db()
    conversation_runtime.init()
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Olladex Test")
    _git(repo, "config", "user.email", "olladex-test@example.invalid")
    _git(repo, "branch", "-M", "main")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "baseline")
    stamp = now()
    with connect() as conn:
        project_id = int(conn.execute(
            "INSERT INTO projects(name,path,model,git_author_name,git_author_email,created_at,last_opened_at) VALUES(?,?,?,?,?,?,?)",
            ("Finalization Test", str(repo), "qwen3:14b", "Olladex Test", "olladex-test@example.invalid", stamp, stamp),
        ).lastrowid)
        session_id = int(conn.execute(
            "INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (project_id, "Swarm", stamp, stamp),
        ).lastrowid)
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Development'").fetchone()["id"])
        swarm_id = int(conn.execute(
            "INSERT INTO swarm_runs(project_id,session_id,title,objective,status,profile_id,max_agents,max_concurrency,created_at,started_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (project_id, session_id, "Finalization", objective, "reviewing", profile_id, 10, 3, stamp, stamp),
        ).lastrowid)
    project = swarm_routes._project(project_id)
    return project, session_id, swarm_id, repo


def _complete_specialist(project: dict, session_id: int, swarm_id: int, *, filename: str | None = "main.py", source_kind: str = "swarm_specialist", source_ref: str = "", role: str = "backend"):
    task = task_queue.enqueue(
        int(project["id"]),
        session_id,
        f"{role} work",
        "work",
        swarm_id=swarm_id,
        source_kind=source_kind,
        source_ref=source_ref,
        agent_role=role,
        task_kind=role,
    )
    isolated = worktrees.create_for_task(project, task["id"])
    task_queue.set_worktree(task["id"], isolated["path"], isolated["branch"])
    if filename:
        target = Path(isolated["path"]) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("print('generated')\n", encoding="utf-8")
        worktrees.commit_all(project, isolated["path"], f"Task {task['id']}")
    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET status='completed',result=?,completed_at=? WHERE id=?",
            ("Completed implementation work with evidence.", now(), task["id"]),
        )
    return task_queue.get(task["id"])


def _complete_reviewer(project: dict, session_id: int, swarm_id: int, report: str):
    task = task_queue.enqueue(
        int(project["id"]),
        session_id,
        "Final review",
        "review",
        swarm_id=swarm_id,
        source_kind="swarm_reviewer",
        agent_role="reviewer",
        task_kind="reviewer",
        priority=300,
    )
    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET status='completed',result=?,completed_at=? WHERE id=?",
            (report, now(), task["id"]),
        )
    return task_queue.get(task["id"])


def test_empty_reviewer_report_blocks_finalization(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed(tmp_path, monkeypatch)
    _complete_specialist(project, session_id, swarm_id)
    _complete_reviewer(project, session_id, swarm_id, "")

    with pytest.raises(ValueError, match="reviewer final report|Reviewer final report"):
        swarm_finalization.review_gate(swarm_id, project)

    swarm_coordinator._prepare_finalization(swarm.get_run(swarm_id))
    assert swarm.get_run(swarm_id)["status"] == "failed"
    assert not swarm.get_run(swarm_id)["integration_path"]


def test_completed_recovery_without_meaningful_diff_blocks_finalization(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed(tmp_path, monkeypatch)
    failed = task_queue.enqueue(
        int(project["id"]),
        session_id,
        "Failed backend",
        "fail",
        swarm_id=swarm_id,
        source_kind="swarm_specialist",
        agent_role="backend",
        task_kind="backend",
    )
    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET status='failed',error='boom',completed_at=? WHERE id=?",
            (now(), failed["id"]),
        )
    recovery = _complete_specialist(
        project,
        session_id,
        swarm_id,
        filename=None,
        source_kind="swarm_recovery",
        source_ref=f"swarm:{swarm_id}:recovery:1:failed:{failed['id']}",
        role="backend",
    )
    _complete_reviewer(
        project,
        session_id,
        swarm_id,
        "Reviewer inspected the recovery path and provides a sufficiently long final report for validation.",
    )

    with pytest.raises(ValueError, match="Recovery task .* without a meaningful committed diff"):
        swarm_finalization.review_gate(swarm_id, project)

    assert Path(recovery["worktree_path"]).exists()


def test_integration_prepared_and_checks_passed_is_not_completed_until_local_promotion(tmp_path, monkeypatch):
    project, session_id, swarm_id, repo = _seed(tmp_path, monkeypatch, objective="Create main.py")
    specialist = _complete_specialist(project, session_id, swarm_id, filename="main.py")
    _complete_reviewer(
        project,
        session_id,
        swarm_id,
        "Reviewer verified the committed specialist change, inspected the implementation, and found it ready for deterministic integration.",
    )

    swarm_coordinator._prepare_finalization(swarm.get_run(swarm_id))
    prepared = swarm.get_run(swarm_id)

    assert prepared["status"] == "integrating"
    assert prepared["integration_path"]
    assert prepared["integration_branch"].startswith("olladex/integration-swarm-")
    assert prepared["status"] != "completed"
    assert not (repo / "main.py").exists()
    assert Path(specialist["worktree_path"]).exists()

    checks = swarm_routes.run_swarm_integration_checks(
        swarm_id,
        swarm_routes.SwarmIntegrationChecksRequest(command="test -f main.py"),
    )
    assert checks["passed"] is True
    assert swarm.get_run(swarm_id)["status"] == "ready_to_promote"
    assert not (repo / "main.py").exists()

    promoted = swarm_routes.promote_swarm_integration(
        swarm_id,
        swarm_routes.SwarmPromotionRequest(target_branch="main"),
    )

    run = swarm.get_run(swarm_id)
    assert promoted["status"] == "completed"
    assert run["status"] == "completed"
    assert run["promotion_status"] == "promoted"
    assert run["promoted_commit"]
    assert (repo / "main.py").read_text(encoding="utf-8") == "print('generated')\n"
    assert _git(repo, "branch", "--show-current") == "main"
    assert _git(repo, "rev-parse", "HEAD") == run["promoted_commit"]
    assert Path(prepared["integration_path"]).exists()
    assert Path(specialist["worktree_path"]).exists()


def test_missing_expected_file_changes_checks_to_failed_state(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed(tmp_path, monkeypatch, objective="Create main.py")
    _complete_specialist(project, session_id, swarm_id, filename="other.py")
    _complete_reviewer(
        project,
        session_id,
        swarm_id,
        "Reviewer inspected the committed branch and supplied a complete report, but objective evidence still controls finalization.",
    )
    swarm_coordinator._prepare_finalization(swarm.get_run(swarm_id))

    with pytest.raises(Exception) as exc:
        swarm_routes.run_swarm_integration_checks(
            swarm_id,
            swarm_routes.SwarmIntegrationChecksRequest(command="test -f other.py"),
        )
    assert "main.py" in str(exc.value)
    run = swarm.get_run(swarm_id)
    assert run["status"] == "checks_failed"
    assert run["status"] != "completed"
