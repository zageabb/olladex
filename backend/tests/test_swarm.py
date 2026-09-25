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
