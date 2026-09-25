from __future__ import annotations

from backend.app.config import settings
from backend.app.database import connect, init_db, now
from backend.app.services import conversation_runtime, swarm, swarm_coordinator, task_queue


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    init_db()
    conversation_runtime.init()
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


def test_swarm_profile_role_model_assignments(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    with connect() as conn:
        fast_id = int(conn.execute("SELECT id FROM model_profiles WHERE name='Fast review'").fetchone()["id"])
        deep_id = int(conn.execute("SELECT id FROM model_profiles WHERE name='Deep implementation'").fetchone()["id"])

    created = swarm.create_profile({
        "name": "Custom Swarm",
        "coordinator_profile_id": fast_id,
        "default_worker_profile_id": deep_id,
        "role_profiles": {"tester": fast_id, "reviewer": fast_id},
        "max_agents": 6,
        "max_concurrency": 2,
        "max_depth": 1,
        "dynamic_size": True,
        "agent_tool_budget": 25,
        "coordinator_tool_budget": 15,
        "require_reviewer": True,
        "require_challenger": False,
    })

    assert created["coordinator_profile_id"] == fast_id
    assert created["default_worker_profile_id"] == deep_id
    assert created["role_profiles"]["tester"] == fast_id
    assert swarm.resolve_role(created, "tester")[0] == fast_id
    assert swarm.resolve_role(created, "backend")[0] == deep_id

    updated = swarm.update_profile(created["id"], {
        **created,
        "role_profiles": {"tester": deep_id},
        "require_challenger": True,
    })
    assert updated["role_profiles"] == {"tester": deep_id}
    assert updated["require_challenger"] == 1


def test_builtin_swarm_profile_name_is_protected(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    built_in = next(item for item in swarm.list_profiles() if item["name"] == "Development")

    try:
        swarm.update_profile(built_in["id"], {**built_in, "name": "Renamed Development"})
    except ValueError as exc:
        assert "cannot be changed" in str(exc)
    else:
        raise AssertionError("Built-in Swarm profile names should be protected")


def test_coordinator_spawns_recovery_and_retargets_reviewer(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=4, max_concurrency=2)
    with connect() as conn:
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Development'").fetchone()["id"])
        conn.execute("UPDATE swarm_runs SET profile_id=? WHERE id=?", (profile_id, swarm_id))

    failed = task_queue.enqueue(
        project_id, session_id, "Broken backend task", "break",
        swarm_id=swarm_id, agent_role="backend", task_kind="backend", source_kind="swarm_specialist",
    )
    completed = task_queue.enqueue(
        project_id, session_id, "Completed research", "research",
        swarm_id=swarm_id, agent_role="researcher", task_kind="researcher", source_kind="swarm_specialist",
    )
    reviewer = task_queue.enqueue(
        project_id, session_id, "Review", "review",
        swarm_id=swarm_id, agent_role="reviewer", task_kind="reviewer", source_kind="swarm_reviewer",
        depends_on=[failed["id"], completed["id"]], priority=300,
    )

    with connect() as conn:
        conn.execute("UPDATE background_tasks SET status='failed',error='boom',completed_at=? WHERE id=?", (now(), failed["id"]))
        conn.execute("UPDATE background_tasks SET status='completed',result='useful finding',completed_at=? WHERE id=?", (now(), completed["id"]))

    monkeypatch.setattr(
        swarm_coordinator,
        "_recovery_decision",
        lambda run, profile, failed_items, completed_items: {
            "action": "spawn",
            "role": "backend",
            "title": "Recovery backend",
            "prompt": "Repair the failed backend work using completed research.",
            "reason": "A bounded recovery is available.",
        },
    )

    swarm_coordinator._reconcile(swarm_id)

    agents = swarm.list_agents(swarm_id)
    recovery = next(item for item in agents if item["source_kind"] == "swarm_recovery")
    reviewer_row = next(item for item in agents if item["id"] == reviewer["id"])
    reviewer_deps = reviewer_row["depends_on"]
    if isinstance(reviewer_deps, str):
        import json
        reviewer_deps = json.loads(reviewer_deps)

    assert recovery["agent_role"] == "backend"
    assert recovery["id"] in reviewer_deps
    assert completed["id"] in reviewer_deps
    assert failed["id"] not in reviewer_deps
    assert reviewer_row["status"] == "queued"


def test_verification_waits_while_failed_swarm_dependency_can_be_recovered(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=3, max_concurrency=1)
    failed = task_queue.enqueue(
        project_id, session_id, "Failed", "fail",
        swarm_id=swarm_id, source_kind="swarm_specialist", agent_role="backend", task_kind="backend", priority=10,
    )
    reviewer = task_queue.enqueue(
        project_id, session_id, "Review", "review",
        swarm_id=swarm_id, source_kind="swarm_reviewer", agent_role="reviewer", task_kind="reviewer",
        depends_on=[failed["id"]], priority=300,
    )
    with connect() as conn:
        conn.execute("UPDATE background_tasks SET status='failed',error='boom',completed_at=? WHERE id=?", (now(), failed["id"]))

    assert task_queue._claim_next() is None
    assert task_queue.get(reviewer["id"])["status"] == "queued"
