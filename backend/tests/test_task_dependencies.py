from __future__ import annotations

import pytest

from backend.app.config import settings
from backend.app.database import connect, init_db, now
from backend.app.services import task_queue


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    init_db()
    stamp = now()
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO projects(name,path,model,created_at,last_opened_at) VALUES(?,?,?,?,?)",
            ("Test", str(tmp_path / "repo"), "qwen3:14b", stamp, stamp),
        )
        project_id = int(cursor.lastrowid)
        cursor = conn.execute(
            "INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (project_id, "Task session", stamp, stamp),
        )
        session_id = int(cursor.lastrowid)
    return project_id, session_id


def test_dependency_waits_until_prerequisite_completes(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    first = task_queue.enqueue(project_id, session_id, "First", "first")
    second = task_queue.enqueue(project_id, session_id, "Second", "second", depends_on=[first["id"]])

    with connect() as conn:
        second_row = dict(conn.execute("SELECT * FROM background_tasks WHERE id=?", (second["id"],)).fetchone())
        ready, reason = task_queue._dependency_state(conn, second_row)
        assert ready is False
        assert reason == ""
        conn.execute("UPDATE background_tasks SET status='completed',completed_at=? WHERE id=?", (now(), first["id"]))
        ready, reason = task_queue._dependency_state(conn, second_row)
        assert ready is True
        assert reason == ""


@pytest.mark.parametrize("status", sorted(task_queue.RECOVERABLE_TASK_STATUSES))
def test_recoverable_prerequisite_waits_for_recovery(tmp_path, monkeypatch, status):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    first = task_queue.enqueue(project_id, session_id, "First", "first")
    second = task_queue.enqueue(project_id, session_id, "Second", "second", depends_on=[first["id"]])

    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET status=?,error='recoverable stop',completed_at=? WHERE id=?",
            (status, now(), first["id"]),
        )
        second_row = dict(conn.execute("SELECT * FROM background_tasks WHERE id=?", (second["id"],)).fetchone())
        ready, reason = task_queue._dependency_state(conn, second_row)
        blockers = task_queue._dependency_blockers(conn, second_row)

    assert ready is False
    assert reason == ""
    assert blockers == []
    assert task_queue.get(second["id"])["status"] == "queued"


def test_failed_prerequisite_blocks_dependent_task(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    first = task_queue.enqueue(project_id, session_id, "First", "first")
    second = task_queue.enqueue(project_id, session_id, "Second", "second", depends_on=[first["id"]])

    with connect() as conn:
        conn.execute("UPDATE background_tasks SET status='failed',error='boom',completed_at=? WHERE id=?", (now(), first["id"]))
        second_row = dict(conn.execute("SELECT * FROM background_tasks WHERE id=?", (second["id"],)).fetchone())
        ready, reason = task_queue._dependency_state(conn, second_row)

    assert ready is False
    assert str(first["id"]) in reason


def test_enqueue_rejects_cross_project_dependency(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    stamp = now()
    with connect() as conn:
        other_project = int(conn.execute(
            "INSERT INTO projects(name,path,model,created_at,last_opened_at) VALUES(?,?,?,?,?)",
            ("Other", str(tmp_path / "other"), "qwen3:14b", stamp, stamp),
        ).lastrowid)
        other_session = int(conn.execute(
            "INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (other_project, "Other", stamp, stamp),
        ).lastrowid)
    external = task_queue.enqueue(other_project, other_session, "External", "external")

    try:
        task_queue.enqueue(project_id, session_id, "Dependent", "dependent", depends_on=[external["id"]])
    except ValueError as exc:
        assert "same project" in str(exc)
    else:
        raise AssertionError("Cross-project dependency should be rejected")



def test_parallel_swarm_tasks_reject_overlapping_ownership_without_dependency(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    stamp = now()
    with connect() as conn:
        swarm_id = int(conn.execute(
            "INSERT INTO swarm_runs(project_id,session_id,title,objective,status,max_agents,max_concurrency,created_at,started_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (project_id, session_id, "Ownership", "Coordinate safely", "running", 6, 3, stamp, stamp),
        ).lastrowid)

    first = task_queue.enqueue(
        project_id,
        session_id,
        "Own auth",
        "Implement authentication.",
        swarm_id=swarm_id,
        source_kind="swarm_specialist",
        agent_role="backend",
        task_kind="backend",
        ownership_scope=["backend/app/auth.py"],
        acceptance_criteria=["Authentication tests pass."],
    )

    with pytest.raises(ValueError) as exc:
        task_queue.enqueue(
            project_id,
            session_id,
            "Also own auth",
            "Change authentication too.",
            swarm_id=swarm_id,
            source_kind="swarm_specialist",
            agent_role="backend",
            task_kind="backend",
            ownership_scope=["backend/app/auth.py"],
            acceptance_criteria=["Regression is fixed."],
        )

    assert str(first["id"]) in str(exc.value)
    assert "ownership conflict" in str(exc.value).lower()


def test_overlapping_ownership_is_allowed_when_explicitly_sequenced(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    stamp = now()
    with connect() as conn:
        swarm_id = int(conn.execute(
            "INSERT INTO swarm_runs(project_id,session_id,title,objective,status,max_agents,max_concurrency,created_at,started_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (project_id, session_id, "Ownership", "Coordinate safely", "running", 6, 3, stamp, stamp),
        ).lastrowid)

    first = task_queue.enqueue(
        project_id,
        session_id,
        "Base auth change",
        "Implement authentication.",
        swarm_id=swarm_id,
        source_kind="swarm_specialist",
        ownership_scope=["backend/app/auth.py"],
        acceptance_criteria=["Authentication tests pass."],
    )
    second = task_queue.enqueue(
        project_id,
        session_id,
        "Follow-up auth change",
        "Extend authentication.",
        swarm_id=swarm_id,
        source_kind="swarm_specialist",
        depends_on=[first["id"]],
        ownership_scope=["backend/app/auth.py"],
        acceptance_criteria=["Follow-up behaviour is verified."],
    )

    assert second["depends_on"] == [first["id"]]
    assert second["ownership_scope"] == ["backend/app/auth.py"]
    assert second["acceptance_criteria"] == ["Follow-up behaviour is verified."]
    assert "Assigned ownership for this task" in second["prompt"]
    assert "Acceptance criteria for this task" in second["prompt"]
