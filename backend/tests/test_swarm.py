from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import subprocess

from fastapi import HTTPException

from backend.app import swarm_routes
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


def test_coordinator_opens_review_gate_when_no_risks_remain(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=3, max_concurrency=2)
    with connect() as conn:
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Development'").fetchone()["id"])
        conn.execute("UPDATE swarm_runs SET profile_id=? WHERE id=?", (profile_id, swarm_id))

    specialist = task_queue.enqueue(
        project_id, session_id, "Done", "done",
        swarm_id=swarm_id, source_kind="swarm_specialist", agent_role="backend", task_kind="backend",
    )
    reviewer = task_queue.enqueue(
        project_id, session_id, "Review", "review",
        swarm_id=swarm_id, source_kind="swarm_reviewer", agent_role="reviewer", task_kind="reviewer",
        depends_on=[specialist["id"]], priority=300,
    )
    with connect() as conn:
        conn.execute("UPDATE background_tasks SET status='completed',result='ok',completed_at=? WHERE id=?", (now(), specialist["id"]))

    swarm_coordinator._reconcile(swarm_id)

    assert swarm.get_run(swarm_id)["status"] == "reviewing"
    claimed = task_queue._claim_next()
    assert claimed and claimed["id"] == reviewer["id"]


def test_coordinator_can_add_followup_for_blackboard_risk(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=4, max_concurrency=2)
    with connect() as conn:
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Development'").fetchone()["id"])
        conn.execute("UPDATE swarm_runs SET profile_id=? WHERE id=?", (profile_id, swarm_id))

    specialist = task_queue.enqueue(
        project_id, session_id, "Done", "done",
        swarm_id=swarm_id, source_kind="swarm_specialist", agent_role="backend", task_kind="backend",
    )
    reviewer = task_queue.enqueue(
        project_id, session_id, "Review", "review",
        swarm_id=swarm_id, source_kind="swarm_reviewer", agent_role="reviewer", task_kind="reviewer",
        depends_on=[specialist["id"]], priority=300,
    )
    with connect() as conn:
        conn.execute("UPDATE background_tasks SET status='completed',result='ok',completed_at=? WHERE id=?", (now(), specialist["id"]))
    swarm.publish(swarm_id, "risk", "Authentication edge case still lacks a regression test.", task_id=specialist["id"])

    monkeypatch.setattr(
        swarm_coordinator,
        "_followup_decision",
        lambda run, profile, completed, risks: {
            "action": "spawn",
            "role": "tester",
            "title": "Regression verification",
            "prompt": "Add and run the missing authentication regression test.",
            "reason": "The risk is concrete and testable.",
        },
    )

    swarm_coordinator._reconcile(swarm_id)

    run = swarm.get_run(swarm_id)
    followup = next(item for item in run["agents"] if item["source_kind"] == "swarm_followup")
    reviewer_row = next(item for item in run["agents"] if item["id"] == reviewer["id"])
    deps = reviewer_row["depends_on"]
    if isinstance(deps, str):
        import json
        deps = json.loads(deps)

    assert run["status"] == "running"
    assert followup["agent_role"] == "tester"
    assert followup["id"] in deps
    assert reviewer_row["status"] == "queued"


def test_task_role_profile_runtime_settings_are_exposed(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id)
    with connect() as conn:
        profile = conn.execute("SELECT * FROM model_profiles WHERE name='Fast review'").fetchone()
        profile_id = int(profile["id"])
    task = task_queue.enqueue(
        project_id,
        session_id,
        "Profiled agent",
        "work",
        swarm_id=swarm_id,
        model_profile_id=profile_id,
        assigned_model=profile["chat_model"],
        source_kind="swarm_specialist",
    )

    task_queue._local.task_id = task["id"]
    try:
        runtime = task_queue.current_model_settings()
    finally:
        task_queue._local.task_id = None

    assert runtime["chat_model"] == profile["chat_model"]
    assert runtime["temperature"] == profile["temperature"]
    assert runtime["context_files"] == profile["context_files"]
    assert runtime["agent_tool_budget"] > 0


def test_coordinator_guidance_is_persisted_and_audited(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id)

    first = swarm.steer_coordinator(swarm_id, "Do not change the public API.")
    second = swarm.steer_coordinator(swarm_id, "Prioritise regression tests.")

    assert "Do not change the public API." in second["coordinator_instructions"]
    assert "Prioritise regression tests." in second["coordinator_instructions"]

    decisions = swarm.blackboard(swarm_id, category="decision")
    assert any("Do not change the public API." in item["content"] for item in decisions)
    assert any("Prioritise regression tests." in item["content"] for item in decisions)
    activity = swarm.get_run(swarm_id)["coordinator_activity"]
    assert activity
    assert "Prioritise regression tests." in activity["content"]

    timeline = swarm.coordinator_events(swarm_id)
    assert any(item["kind"] == "guidance" and item["payload"].get("content") == "Do not change the public API." for item in timeline)
    assert any(item["kind"] == "guidance" and item["payload"].get("content") == "Prioritise regression tests." for item in timeline)


def test_recovery_keeps_reviewer_downstream_of_challenger(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=5, max_concurrency=2)
    with connect() as conn:
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Deep Development'").fetchone()["id"])
        conn.execute("UPDATE swarm_runs SET profile_id=? WHERE id=?", (profile_id, swarm_id))

    failed = task_queue.enqueue(
        project_id, session_id, "Failed backend", "fail",
        swarm_id=swarm_id, source_kind="swarm_specialist", agent_role="backend", task_kind="backend",
    )
    completed = task_queue.enqueue(
        project_id, session_id, "Research", "research",
        swarm_id=swarm_id, source_kind="swarm_specialist", agent_role="researcher", task_kind="researcher",
    )
    challenger = task_queue.enqueue(
        project_id, session_id, "Challenge", "challenge",
        swarm_id=swarm_id, source_kind="swarm_challenger", agent_role="challenger", task_kind="challenger",
        depends_on=[failed["id"], completed["id"]], priority=200,
    )
    reviewer = task_queue.enqueue(
        project_id, session_id, "Review", "review",
        swarm_id=swarm_id, source_kind="swarm_reviewer", agent_role="reviewer", task_kind="reviewer",
        depends_on=[challenger["id"]], priority=300,
    )
    with connect() as conn:
        conn.execute("UPDATE background_tasks SET status='failed',error='boom',completed_at=? WHERE id=?", (now(), failed["id"]))
        conn.execute("UPDATE background_tasks SET status='completed',result='ok',completed_at=? WHERE id=?", (now(), completed["id"]))

    monkeypatch.setattr(
        swarm_coordinator,
        "_recovery_decision",
        lambda run, profile, failed_items, completed_items: {
            "action": "spawn",
            "role": "backend",
            "title": "Recovery backend",
            "prompt": "Recover the backend work.",
            "reason": "Recoverable.",
        },
    )

    swarm_coordinator._reconcile(swarm_id)

    agents = swarm.list_agents(swarm_id)
    recovery = next(item for item in agents if item["source_kind"] == "swarm_recovery")
    challenger_row = next(item for item in agents if item["id"] == challenger["id"])
    reviewer_row = next(item for item in agents if item["id"] == reviewer["id"])

    challenger_deps = challenger_row["depends_on"]
    reviewer_deps = reviewer_row["depends_on"]
    if isinstance(challenger_deps, str):
        import json
        challenger_deps = json.loads(challenger_deps)
    if isinstance(reviewer_deps, str):
        import json
        reviewer_deps = json.loads(reviewer_deps)

    assert recovery["id"] in challenger_deps
    assert failed["id"] not in challenger_deps
    assert reviewer_deps == [challenger["id"]]


def test_dynamic_initial_budget_reserves_one_recovery_slot():
    dynamic = {
        "require_reviewer": 1,
        "require_challenger": 0,
        "dynamic_size": 1,
    }
    fixed = {
        "require_reviewer": 1,
        "require_challenger": 0,
        "dynamic_size": 0,
    }

    assert swarm.initial_specialist_budget(dynamic, 5) == 3
    assert swarm.initial_specialist_budget(fixed, 5) == 4
    assert swarm.initial_specialist_budget(dynamic, 3) == 2


def test_challenger_only_profile_completes_after_challenger(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=3, max_concurrency=2)
    with connect() as conn:
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Deep Development'").fetchone()["id"])
        conn.execute(
            "UPDATE swarm_runs SET profile_id=? WHERE id=?",
            (profile_id, swarm_id),
        )

    specialist = task_queue.enqueue(
        project_id, session_id, "Done", "done",
        swarm_id=swarm_id, source_kind="swarm_specialist", agent_role="backend", task_kind="backend",
    )
    challenger = task_queue.enqueue(
        project_id, session_id, "Challenge", "challenge",
        swarm_id=swarm_id, source_kind="swarm_challenger", agent_role="challenger", task_kind="challenger",
        depends_on=[specialist["id"]], priority=200,
    )
    with connect() as conn:
        conn.execute("UPDATE background_tasks SET status='completed',result='ok',completed_at=? WHERE id=?", (now(), specialist["id"]))
        conn.execute("UPDATE background_tasks SET status='completed',result='checked',completed_at=? WHERE id=?", (now(), challenger["id"]))

    swarm_coordinator._reconcile(swarm_id)

    assert swarm.get_run(swarm_id)["status"] == "completed"


def test_challenger_only_profile_fails_when_challenger_fails(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=3, max_concurrency=2)
    with connect() as conn:
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Deep Development'").fetchone()["id"])
        conn.execute("UPDATE swarm_runs SET profile_id=? WHERE id=?", (profile_id, swarm_id))

    specialist = task_queue.enqueue(
        project_id, session_id, "Done", "done",
        swarm_id=swarm_id, source_kind="swarm_specialist", agent_role="backend", task_kind="backend",
    )
    challenger = task_queue.enqueue(
        project_id, session_id, "Challenge", "challenge",
        swarm_id=swarm_id, source_kind="swarm_challenger", agent_role="challenger", task_kind="challenger",
        depends_on=[specialist["id"]], priority=200,
    )
    with connect() as conn:
        conn.execute("UPDATE background_tasks SET status='completed',result='ok',completed_at=? WHERE id=?", (now(), specialist["id"]))
        conn.execute("UPDATE background_tasks SET status='failed',error='boom',completed_at=? WHERE id=?", (now(), challenger["id"]))

    swarm_coordinator._reconcile(swarm_id)

    assert swarm.get_run(swarm_id)["status"] == "failed"


def test_successful_recovery_supersedes_original_failure_without_repeating(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=5, max_concurrency=2)
    with connect() as conn:
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Development'").fetchone()["id"])
        conn.execute("UPDATE swarm_runs SET profile_id=? WHERE id=?", (profile_id, swarm_id))

    failed = task_queue.enqueue(
        project_id, session_id, "Broken backend", "break",
        swarm_id=swarm_id, agent_role="backend", task_kind="backend", source_kind="swarm_specialist",
    )
    completed = task_queue.enqueue(
        project_id, session_id, "Research", "research",
        swarm_id=swarm_id, agent_role="researcher", task_kind="researcher", source_kind="swarm_specialist",
    )
    reviewer = task_queue.enqueue(
        project_id, session_id, "Review", "review",
        swarm_id=swarm_id, agent_role="reviewer", task_kind="reviewer", source_kind="swarm_reviewer",
        depends_on=[failed["id"], completed["id"]], priority=300,
    )
    with connect() as conn:
        conn.execute("UPDATE background_tasks SET status='failed',error='boom',completed_at=? WHERE id=?", (now(), failed["id"]))
        conn.execute("UPDATE background_tasks SET status='completed',result='useful',completed_at=? WHERE id=?", (now(), completed["id"]))

    monkeypatch.setattr(
        swarm_coordinator,
        "_recovery_decision",
        lambda run, profile, failed_items, completed_items: {
            "action": "spawn",
            "role": "backend",
            "title": "Recovery backend",
            "prompt": "Repair the failed backend work.",
            "reason": "Recoverable.",
        },
    )

    swarm_coordinator._reconcile(swarm_id)
    agents = swarm.list_agents(swarm_id)
    recovery = next(item for item in agents if item["source_kind"] == "swarm_recovery")
    assert (":failed:" + str(failed["id"])) in recovery["source_ref"]

    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET status='completed',result='recovered',completed_at=? WHERE id=?",
            (now(), recovery["id"]),
        )

    swarm_coordinator._reconcile(swarm_id)

    agents = swarm.list_agents(swarm_id)
    recoveries = [item for item in agents if item["source_kind"] == "swarm_recovery"]
    assert len(recoveries) == 1
    assert swarm.get_run(swarm_id)["status"] == "reviewing"
    assert task_queue.get(reviewer["id"])["status"] == "queued"


def test_verification_tasks_do_not_start_before_coordinator_opens_review(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=3, max_concurrency=2)

    specialist = task_queue.enqueue(
        project_id, session_id, "Done", "done",
        swarm_id=swarm_id, source_kind="swarm_specialist", agent_role="backend", task_kind="backend", priority=10,
    )
    reviewer = task_queue.enqueue(
        project_id, session_id, "Review", "review",
        swarm_id=swarm_id, source_kind="swarm_reviewer", agent_role="reviewer", task_kind="reviewer",
        depends_on=[specialist["id"]], priority=300,
    )
    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET status='completed',result='ok',completed_at=? WHERE id=?",
            (now(), specialist["id"]),
        )

    # Dependency is complete, but the Coordinator has not yet opened review.
    assert swarm.get_run(swarm_id)["status"] == "running"
    assert task_queue._claim_next() is None
    assert task_queue.get(reviewer["id"])["status"] == "queued"

    with connect() as conn:
        conn.execute("UPDATE swarm_runs SET status='reviewing' WHERE id=?", (swarm_id,))

    claimed = task_queue._claim_next()
    assert claimed and claimed["id"] == reviewer["id"]


def test_coordinator_status_timeline_is_append_only(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id)

    swarm.set_status(swarm_id, "reviewing")
    swarm.pause(swarm_id)
    swarm.resume(swarm_id)
    swarm.set_status(swarm_id, "completed")

    timeline = swarm.coordinator_events(swarm_id)
    statuses = [
        item["payload"].get("status")
        for item in timeline
        if item["kind"] == "status"
    ]

    assert statuses == ["reviewing", "paused", "running", "completed"]
    assert [item["id"] for item in timeline] == sorted(item["id"] for item in timeline)


def test_blackboard_supports_incremental_cursor_and_limit(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id)

    first = swarm.publish(swarm_id, "fact", "one")
    second = swarm.publish(swarm_id, "finding", "two")
    third = swarm.publish(swarm_id, "risk", "three")

    items = swarm.blackboard(swarm_id, after=first["id"], limit=1)
    assert [item["id"] for item in items] == [second["id"]]

    remaining = swarm.blackboard(swarm_id, after=second["id"], limit=10)
    assert [item["id"] for item in remaining] == [third["id"]]


def test_agent_board_exposes_persisted_progress_and_tool_usage(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id)
    task = task_queue.enqueue(
        project_id,
        session_id,
        "Measured agent",
        "work",
        swarm_id=swarm_id,
        source_kind="swarm_specialist",
        agent_role="backend",
        task_kind="backend",
    )

    task_queue.set_progress(task["id"], 40, "Running focused tests")
    run_id = conversation_runtime.create(session_id, task["id"])
    conversation_runtime.emit("tool_started", {"tool": "read_file"}, run_id)
    conversation_runtime.emit("tool_started", {"tool": "run_command"}, run_id)

    agent = next(item for item in swarm.list_agents(swarm_id) if item["id"] == task["id"])

    assert agent["progress"] == 40
    assert agent["current_activity"] in {"Running focused tests", "Using run_command"}
    assert agent["tool_usage"] == 2
    assert agent["tool_budget"] > 0


def test_coordinator_can_spawn_one_requested_helper_and_retarget_verification(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=5, max_concurrency=3)
    with connect() as conn:
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Development'").fetchone()["id"])
        conn.execute("UPDATE swarm_runs SET profile_id=? WHERE id=?", (profile_id, swarm_id))

    requester = task_queue.enqueue(
        project_id, session_id, "Backend work", "implement",
        swarm_id=swarm_id, source_kind="swarm_specialist", agent_role="backend", task_kind="backend",
    )
    reviewer = task_queue.enqueue(
        project_id, session_id, "Review", "review",
        swarm_id=swarm_id, source_kind="swarm_reviewer", agent_role="reviewer", task_kind="reviewer",
        depends_on=[requester["id"]], priority=300,
    )
    with connect() as conn:
        conn.execute("UPDATE background_tasks SET status='running',started_at=? WHERE id=?", (now(), requester["id"]))

    request = swarm.publish(
        swarm_id,
        "question",
        "Need an independent tester to reproduce the edge case in parallel.",
        task_id=requester["id"],
        key="parallel-test-help",
    )

    monkeypatch.setattr(
        swarm_coordinator,
        "_help_decision",
        lambda run, profile, help_request, requesting_agent, completed: {
            "action": "spawn",
            "role": "tester",
            "title": "Parallel regression tester",
            "prompt": "Reproduce the reported edge case and add a focused regression test if appropriate.",
            "reason": "Independent verification is useful.",
        },
    )

    swarm_coordinator._reconcile(swarm_id)

    agents = swarm.list_agents(swarm_id)
    helpers = [item for item in agents if item["source_kind"] == "swarm_help"]
    assert len(helpers) == 1
    helper = helpers[0]
    assert helper["agent_role"] == "tester"
    assert f":help:{request['id']}:" in helper["source_ref"]

    reviewer_row = next(item for item in agents if item["id"] == reviewer["id"])
    deps = reviewer_row["depends_on"]
    if isinstance(deps, str):
        import json
        deps = json.loads(deps)
    assert requester["id"] in deps
    assert helper["id"] in deps

    decisions = swarm.blackboard(swarm_id, category="decision")
    assert any(item["key"] == f"help-response-{request['id']}" for item in decisions)

    swarm_coordinator._reconcile(swarm_id)
    assert len([item for item in swarm.list_agents(swarm_id) if item["source_kind"] == "swarm_help"]) == 1


def test_help_request_is_declined_when_dynamic_swarm_is_disabled(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=4, max_concurrency=2)
    with connect() as conn:
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Development'").fetchone()["id"])
        conn.execute("UPDATE swarm_profiles SET dynamic_size=0 WHERE id=?", (profile_id,))
        conn.execute("UPDATE swarm_runs SET profile_id=? WHERE id=?", (profile_id, swarm_id))

    requester = task_queue.enqueue(
        project_id, session_id, "Backend work", "implement",
        swarm_id=swarm_id, source_kind="swarm_specialist", agent_role="backend", task_kind="backend",
    )
    with connect() as conn:
        conn.execute("UPDATE background_tasks SET status='running',started_at=? WHERE id=?", (now(), requester["id"]))

    request = swarm.publish(
        swarm_id,
        "question",
        "Need another specialist.",
        task_id=requester["id"],
        key="help",
    )

    swarm_coordinator._reconcile(swarm_id)

    assert not [item for item in swarm.list_agents(swarm_id) if item["source_kind"] == "swarm_help"]
    decisions = swarm.blackboard(swarm_id, category="decision")
    assert any(
        item["key"] == f"help-response-{request['id']}" and "dynamic swarm sizing is disabled" in item["content"]
        for item in decisions
    )


def test_broadcast_guidance_updates_queued_and_active_agents(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=4, max_concurrency=2)

    queued_session = session_id
    active_session = None
    with connect() as conn:
        active_session = int(conn.execute(
            "INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (project_id, "Active agent", now(), now()),
        ).lastrowid)

    queued = task_queue.enqueue(
        project_id, queued_session, "Queued agent", "Queued original prompt",
        swarm_id=swarm_id, source_kind="swarm_specialist", agent_role="backend", task_kind="backend",
    )
    active = task_queue.enqueue(
        project_id, active_session, "Active agent", "Active original prompt",
        swarm_id=swarm_id, source_kind="swarm_specialist", agent_role="tester", task_kind="tester",
    )
    with connect() as conn:
        conn.execute("UPDATE background_tasks SET status='running',started_at=? WHERE id=?", (now(), active["id"]))

    run_id = conversation_runtime.create(active_session, active["id"])

    result = swarm.broadcast_guidance(swarm_id, "Do not change the public API.")

    assert result["queued_tasks_updated"] == 1
    assert result["active_runs_steered"] == 1

    with connect() as conn:
        queued_prompt = conn.execute("SELECT prompt FROM background_tasks WHERE id=?", (queued["id"],)).fetchone()["prompt"]
        active_prompt = conn.execute("SELECT prompt FROM background_tasks WHERE id=?", (active["id"],)).fetchone()["prompt"]
        inputs = [row["content"] for row in conn.execute(
            "SELECT content FROM agent_inputs WHERE run_id=? ORDER BY id", (run_id,)
        )]
        instructions = conn.execute(
            "SELECT coordinator_instructions FROM swarm_runs WHERE id=?", (swarm_id,)
        ).fetchone()["coordinator_instructions"]

    assert "Do not change the public API." in queued_prompt
    assert "Do not change the public API." not in active_prompt
    assert inputs == ["Swarm-wide user guidance: Do not change the public API."]
    assert "Do not change the public API." in instructions

    timeline = swarm.coordinator_events(swarm_id)
    assert any(
        item["kind"] == "broadcast" and item["payload"].get("active_runs_steered") == 1
        for item in timeline
    )


def test_coordinator_budget_is_persistent_and_exhaustion_is_recorded_once(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id)
    with connect() as conn:
        profile_id = int(conn.execute("SELECT profile_id FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()["profile_id"])
        conn.execute("UPDATE swarm_profiles SET coordinator_tool_budget=2 WHERE id=?", (profile_id,))

    first = swarm.consume_coordinator_budget(swarm_id, "first")
    second = swarm.consume_coordinator_budget(swarm_id, "second")
    third = swarm.consume_coordinator_budget(swarm_id, "third")
    fourth = swarm.consume_coordinator_budget(swarm_id, "fourth")

    assert first == {"allowed": True, "used": 1, "budget": 2, "remaining": 1}
    assert second == {"allowed": True, "used": 2, "budget": 2, "remaining": 0}
    assert third["allowed"] is False
    assert fourth["allowed"] is False
    assert swarm.coordinator_budget(swarm_id) == {"used": 2, "budget": 2, "remaining": 0}
    assert swarm.get_run(swarm_id)["coordinator_budget"]["used"] == 2

    timeline = swarm.coordinator_events(swarm_id)
    assert len([item for item in timeline if item["kind"] == "model_call"]) == 2
    assert len([item for item in timeline if item["kind"] == "budget_exhausted"]) == 1


def test_board_snapshot_returns_stable_summary_and_incremental_streams(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=4, max_concurrency=2)

    task = task_queue.enqueue(
        project_id, session_id, "Backend", "work",
        swarm_id=swarm_id, source_kind="swarm_specialist",
        agent_role="backend", task_kind="backend",
    )
    task_queue.set_progress(task["id"], 40, "Implementing")
    run_id = conversation_runtime.create(session_id, task["id"])
    conversation_runtime.emit("progress", {"progress": 40, "current_step": "Implementing"}, run_id)
    board_item = swarm.publish(swarm_id, "finding", "Useful fact", task_id=task["id"])
    coordinator_item = swarm.emit_coordinator_event(swarm_id, "decision", {"content": "Continue"})

    snap = swarm.board_snapshot(swarm_id)

    assert snap["swarm"]["id"] == swarm_id
    assert snap["summary"]["total_agents"] == 1
    assert snap["summary"]["max_agents"] == 4
    assert snap["summary"]["max_concurrency"] == 2
    assert snap["summary"]["progress"] == 40
    assert "tool_usage" in snap["summary"]
    assert "tool_budget_capacity" in snap["summary"]
    assert "coordinator_budget" in snap["summary"]
    assert snap["events"]
    assert snap["blackboard"][0]["id"] == board_item["id"]
    assert snap["coordinator_events"][-1]["id"] == coordinator_item["id"]
    assert snap["cursors"]["event"] == snap["events"][-1]["id"]
    assert snap["cursors"]["blackboard"] == board_item["id"]
    assert snap["cursors"]["coordinator_event"] == coordinator_item["id"]

    later = swarm.board_snapshot(
        swarm_id,
        after_event=snap["cursors"]["event"],
        after_blackboard=snap["cursors"]["blackboard"],
        after_coordinator_event=snap["cursors"]["coordinator_event"],
    )
    assert later["events"] == []
    assert later["blackboard"] == []
    assert later["coordinator_events"] == []


def test_sqlite_wal_handles_parallel_swarm_writers(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id, max_agents=8, max_concurrency=4)

    errors: list[str] = []

    def writer(worker: int) -> None:
        try:
            for index in range(20):
                swarm.publish(
                    swarm_id,
                    "finding",
                    f"worker {worker} finding {index}",
                    key=f"w{worker}-{index}",
                )
                swarm.emit_coordinator_event(
                    swarm_id,
                    "test_event",
                    {"worker": worker, "index": index},
                )
        except Exception as exc:  # pragma: no cover - assertion reports details
            errors.append(f"{worker}: {exc}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(writer, range(6)))

    assert errors == []
    assert len(swarm.blackboard(swarm_id, limit=1000)) == 120
    coordinator = swarm.coordinator_events(swarm_id, limit=1000)
    assert len([item for item in coordinator if item["kind"] == "test_event"]) == 120


def test_swarm_preflight_checks_git_sqlite_models_and_limits(tmp_path, monkeypatch):
    project_id, _ = _seed(tmp_path, monkeypatch)
    with connect() as conn:
        project_path = conn.execute("SELECT path FROM projects WHERE id=?", (project_id,)).fetchone()["path"]
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Development'").fetchone()["id"])

    subprocess.run(["git", "init"], cwd=project_path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    monkeypatch.setattr(
        swarm,
        "validate_models",
        lambda profile, fallback_model='': {
            "installed": ["phi4:14b", "qwen2.5-coder:7b"],
            "assignments": {"coordinator": "phi4:14b", "backend": "qwen2.5-coder:7b"},
        },
    )

    result = swarm.preflight(project_id, profile_id, max_agents=6, max_concurrency=3)

    assert result["ready"] is True
    assert result["max_agents"] == 6
    assert result["max_concurrency"] == 3
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["sqlite_wal"]["ok"] is True
    assert checks["sqlite_busy_timeout"]["ok"] is True
    assert checks["git_repository"]["ok"] is True
    assert checks["ollama_models"]["ok"] is True
    assert checks["swarm_limits"]["ok"] is True


def test_swarm_preflight_reports_missing_local_models_without_creating_run(tmp_path, monkeypatch):
    project_id, _ = _seed(tmp_path, monkeypatch)
    with connect() as conn:
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Development'").fetchone()["id"])

    monkeypatch.setattr(swarm, "validate_models", lambda profile, fallback_model='': (_ for _ in ()).throw(ValueError("Required local Ollama model(s) are not installed: phi4:14b")))

    result = swarm.preflight(project_id, profile_id)

    assert result["ready"] is False
    model_check = next(item for item in result["checks"] if item["name"] == "ollama_models")
    assert model_check["ok"] is False
    assert "phi4:14b" in model_check["detail"]
    with connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM swarm_runs").fetchone()[0] == 0


def test_swarm_integration_push_state_is_durable_and_required_for_pr(tmp_path, monkeypatch):
    project_id, session_id = _seed(tmp_path, monkeypatch)
    swarm_id = _create_swarm(project_id, session_id)
    with connect() as conn:
        conn.execute(
            "UPDATE swarm_runs SET status='integrating',integration_path=?,integration_branch=?,integration_check_status='passed' WHERE id=?",
            (str(tmp_path / "integration"), "olladex/swarm-test-integration", swarm_id),
        )

    body = swarm_routes.SwarmIntegrationPullRequestRequest(
        title="Swarm result",
        body="Verified",
        base="main",
    )
    try:
        swarm_routes.create_swarm_integration_pull_request(swarm_id, body)
    except HTTPException as exc:
        assert exc.status_code == 409
        assert "Push the integration branch" in exc.detail
    else:
        raise AssertionError("PR creation should require a pushed integration branch")

    monkeypatch.setattr(
        swarm_routes.integration,
        "push",
        lambda project, path, remote: {"branch": "olladex/swarm-test-integration", "remote": remote},
    )
    pushed = swarm_routes.push_swarm_integration(
        swarm_id,
        swarm_routes.SwarmIntegrationPushRequest(remote="origin"),
    )
    assert pushed["branch"] == "olladex/swarm-test-integration"
    assert swarm.get_run(swarm_id)["integration_pushed"] == 1
    assert swarm.board_snapshot(swarm_id)["swarm"]["integration_pushed"] == 1

    monkeypatch.setattr(swarm_routes.integration, "integration_project", lambda project, path: project)
    monkeypatch.setattr(
        swarm_routes.github_service,
        "prepare_pull_request",
        lambda project, title, body, base: {"command": "gh pr create"},
    )
    monkeypatch.setattr(
        swarm_routes.github_service,
        "execute_pull_request",
        lambda project, prepared: {"url": "https://github.com/zageabb/olladex/pull/99"},
    )
    created = swarm_routes.create_swarm_integration_pull_request(swarm_id, body)
    assert created["pull_request_number"] == 99
    assert swarm.get_run(swarm_id)["integration_pr_number"] == 99


def test_swarm_self_test_pings_each_unique_model_once(tmp_path, monkeypatch):
    project_id, _ = _seed(tmp_path, monkeypatch)
    with connect() as conn:
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Development'").fetchone()["id"])

    monkeypatch.setattr(
        swarm,
        "validate_models",
        lambda profile, fallback_model='': {
            "installed": ["phi4:14b", "qwen2.5-coder:7b"],
            "assignments": {
                "coordinator": "phi4:14b",
                "reviewer": "phi4:14b",
                "backend": "qwen2.5-coder:7b",
                "tester": "qwen2.5-coder:7b",
            },
        },
    )

    calls: list[str] = []

    class Response:
        def __init__(self, model: str):
            self.model = model
        def raise_for_status(self):
            return None
        def json(self):
            return {"message": {"content": "OLLADEX_SWARM_OK"}}

    class Client:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def post(self, path, json):
            calls.append(json["model"])
            return Response(json["model"])

    monkeypatch.setattr(swarm.ollama, "client", lambda timeout=30: Client())

    result = swarm.self_test(project_id, profile_id)

    assert result["ready"] is True
    assert sorted(calls) == ["phi4:14b", "qwen2.5-coder:7b"]
    by_model = {item["model"]: item for item in result["models"]}
    assert by_model["phi4:14b"]["roles"] == ["coordinator", "reviewer"]
    assert by_model["qwen2.5-coder:7b"]["roles"] == ["backend", "tester"]


def test_swarm_self_test_reports_bad_model_response(tmp_path, monkeypatch):
    project_id, _ = _seed(tmp_path, monkeypatch)
    with connect() as conn:
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Development'").fetchone()["id"])

    monkeypatch.setattr(
        swarm,
        "validate_models",
        lambda profile, fallback_model='': {
            "installed": ["test-model"],
            "assignments": {"coordinator": "test-model"},
        },
    )

    class Response:
        def raise_for_status(self):
            return None
        def json(self):
            return {"message": {"content": "unexpected response"}}

    class Client:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def post(self, path, json):
            return Response()

    monkeypatch.setattr(swarm.ollama, "client", lambda timeout=30: Client())

    result = swarm.self_test(project_id, profile_id)

    assert result["ready"] is False
    assert result["models"][0]["ok"] is False
    assert result["models"][0]["response"] == "unexpected response"


def test_validate_models_applies_project_default_to_unassigned_roles(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    monkeypatch.setattr(
        swarm.ollama,
        "status",
        lambda: {"connected": True, "models": ["qwen3:14b"]},
    )

    result = swarm.validate_models(
        {
            "coordinator_profile_id": None,
            "default_worker_profile_id": None,
            "role_profiles": {},
        },
        "qwen3:14b",
    )

    assert result["assignments"]["coordinator"] == "qwen3:14b"
    assert result["assignments"]["backend"] == "qwen3:14b"
    assert result["assignments"]["tester"] == "qwen3:14b"
    assert set(result["assignments"].values()) == {"qwen3:14b"}
