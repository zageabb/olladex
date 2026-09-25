from __future__ import annotations

from backend.app.config import settings
from backend.app.database import connect, init_db, now
from backend.app.services import swarm, task_queue


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    init_db()
    repo = tmp_path / "repo"
    repo.mkdir()
    stamp = now()
    with connect() as conn:
        project_id = int(conn.execute(
            "INSERT INTO projects(name,path,model,created_at,last_opened_at) VALUES(?,?,?,?,?)",
            ("Swarm Test", str(repo), "qwen3:14b", stamp, stamp),
        ).lastrowid)
        session_id = int(conn.execute(
            "INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (project_id, "Swarm", stamp, stamp),
        ).lastrowid)
    return project_id, session_id


def _create_swarm(project_id: int, session_id: int, max_agents: int = 4, max_concurrency: int = 2) -> int:
    stamp = now()
    with connect() as conn:
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Development'").fetchone()["id"])
        swarm_id = int(conn.execute(
            "INSERT INTO swarm_runs(project_id,session_id,title,objective,status,profile_id,max_agents,max_concurrency,created_at,started_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (project_id, session_id, "Test swarm", "Test objective", "running", profile_id, max_agents, max_concurrency, stamp, stamp),
        ).lastrowid)
    return swarm_id


def test_swarm_schema_and_builtin_profiles_are_created(tmp_path, monkeypatch):
    project_id, _ = _seed(tmp_path, monkeypatch)
    profiles = swarm.list_profiles()

    assert {item["name"] for item in profiles} >= {"Quick Review", "Development", "Bug Hunt", "Deep Development"}
    assert swarm.skill_enabled(project_id) is False
    assert swarm.set_skill(project_id, True)["enabled"] is True
    assert swarm.skill_enabled(project_id) is True


def test_swarm_enqueue_persists_model_role_and_enforces_agent_limit(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=2, max_concurrency=2)

    first = task_queue.enqueue(
        project_id, session_id, "One", "one",
        swarm_id=swarm_id, assigned_model="qwen2.5-coder:7b",
        agent_role="backend", task_kind="backend", priority=50, depth=1,
    )
    second = task_queue.enqueue(
        project_id, session_id, "Two", "two",
        swarm_id=swarm_id, assigned_model="phi4:14b",
        agent_role="reviewer", task_kind="reviewer", priority=100, depth=1,
    )

    assert first["assigned_model"] == "qwen2.5-coder:7b"
    assert first["agent_role"] == "backend"
    assert first["task_kind"] == "backend"
    assert first["priority"] == 50
    assert second["assigned_model"] == "phi4:14b"

    try:
        task_queue.enqueue(project_id, session_id, "Three", "three", swarm_id=swarm_id)
    except ValueError as exc:
        assert "maximum agent count" in str(exc)
    else:
        raise AssertionError("Swarm should reject tasks above max_agents")


def test_claim_next_respects_swarm_concurrency(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=3, max_concurrency=1)

    first = task_queue.enqueue(project_id, session_id, "First", "first", swarm_id=swarm_id, priority=10)
    second = task_queue.enqueue(project_id, session_id, "Second", "second", swarm_id=swarm_id, priority=20)

    claimed = task_queue._claim_next()
    assert claimed and claimed["id"] == first["id"]
    assert task_queue._claim_next() is None

    with connect() as conn:
        conn.execute("UPDATE background_tasks SET status='completed',completed_at=? WHERE id=?", (now(), first["id"]))

    claimed = task_queue._claim_next()
    assert claimed and claimed["id"] == second["id"]


def test_paused_swarm_does_not_claim_tasks(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=2, max_concurrency=2)
    task = task_queue.enqueue(project_id, session_id, "Paused", "paused", swarm_id=swarm_id)

    swarm.pause(swarm_id)
    assert task_queue._claim_next() is None
    assert task_queue.get(task["id"])["status"] == "queued"

    swarm.resume(swarm_id)
    claimed = task_queue._claim_next()
    assert claimed and claimed["id"] == task["id"]


def test_blackboard_is_scoped_to_swarm_and_task(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id)
    task = task_queue.enqueue(project_id, session_id, "Research", "research", swarm_id=swarm_id)

    finding = swarm.publish(
        swarm_id,
        "finding",
        "Authentication flow uses a shared dependency.",
        task_id=task["id"],
        key="auth-flow",
        confidence=0.9,
    )
    swarm.publish(swarm_id, "risk", "Expired-token behaviour needs regression coverage.")

    task_items = swarm.blackboard(swarm_id, task_id=task["id"])
    findings = swarm.blackboard(swarm_id, category="finding")

    assert finding["task_id"] == task["id"]
    assert len(task_items) == 1
    assert task_items[0]["key"] == "auth-flow"
    assert len(findings) == 1
    assert findings[0]["category"] == "finding"
