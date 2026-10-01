from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from backend.app import swarm_routes
from backend.app.config import settings
from backend.app.database import connect, init_db, now
from backend.app.services import conversation_runtime, git, swarm, task_queue, worktrees


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


def _seed_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    init_db()
    conversation_runtime.init()
    repo = tmp_path / "repo"
    repo.mkdir()
    stamp = now()
    with connect() as conn:
        project_id = int(conn.execute(
            "INSERT INTO projects(name,path,model,git_author_name,git_author_email,created_at,last_opened_at) VALUES(?,?,?,?,?,?,?)",
            ("Recovery Test", str(repo), "qwen3:14b", "Olladex Test", "olladex-test@example.invalid", stamp, stamp),
        ).lastrowid)
        session_id = int(conn.execute(
            "INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (project_id, "Recovery", stamp, stamp),
        ).lastrowid)
        profile_id = int(conn.execute("SELECT id FROM swarm_profiles WHERE name='Development'").fetchone()["id"])
        swarm_id = int(conn.execute(
            "INSERT INTO swarm_runs(project_id,session_id,title,objective,status,profile_id,max_agents,max_concurrency,created_at,started_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (project_id, session_id, "Recovery", "Recover safely", "running", profile_id, 8, 3, stamp, stamp),
        ).lastrowid)
    project = swarm_routes._project(project_id)
    git.initialize_local_repository(project)
    return project, session_id, swarm_id, repo


def _exhausted_task(project, session_id, swarm_id):
    task = task_queue.enqueue(
        int(project["id"]),
        session_id,
        "Recover me",
        "Implement recovery.py and validate it.",
        swarm_id=swarm_id,
        source_kind="swarm_specialist",
        agent_role="backend",
        task_kind="backend",
    )
    isolated = worktrees.create_for_task(project, task["id"])
    task_queue.set_worktree(task["id"], isolated["path"], isolated["branch"])
    stamp = now()
    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET status='budget_exhausted',error='tool budget exhausted',completed_at=? WHERE id=?",
            (stamp, task["id"]),
        )
        run_id = int(conn.execute(
            "INSERT INTO agent_runs(session_id,task_id,status,checkpoint,cancel_requested,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (
                session_id,
                task["id"],
                "budget_exhausted",
                '[{"role":"user","content":"Implement recovery.py"},{"role":"assistant","content":"Working"}]',
                0,
                stamp,
                stamp,
            ),
        ).lastrowid)
    return task_queue.get(task["id"]), run_id


def test_resume_budget_exhausted_task_reuses_identity_checkpoint_worktree_and_branch(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    task, prior_run_id = _exhausted_task(project, session_id, swarm_id)
    worktree = Path(task["worktree_path"])
    dirty = worktree / "recovery.py"
    dirty.write_text("value = 1\n", encoding="utf-8")

    launched = {}
    monkeypatch.setattr(
        conversation_runtime,
        "launch",
        lambda session_id, content, resume_id=None, recovery_metadata=None: launched.update(
            {
                "session_id": session_id,
                "content": content,
                "resume_id": resume_id,
                "metadata": recovery_metadata,
            }
        ) or {"id": 8001, "session_id": session_id, "task_id": task["id"], "status": "running"},
    )

    result = task_queue.resume_task(task["id"], fresh_budget=37)

    assert result["task_id"] == task["id"]
    assert result["session_id"] == session_id
    assert result["prior_run_id"] == prior_run_id
    assert result["run_id"] == 8001
    assert result["checkpoint_restored"] is True
    assert result["fresh_budget"] == 37
    assert result["worktree_path"] == task["worktree_path"]
    assert result["worktree_branch"] == task["worktree_branch"]
    assert result["dirty_work_preserved"] is True
    assert dirty.read_text(encoding="utf-8") == "value = 1\n"
    assert launched["resume_id"] == prior_run_id
    assert launched["session_id"] == session_id
    assert launched["metadata"]["starting_head"] == _git(worktree, "rev-parse", "HEAD")
    assert "Continue the existing task from its saved checkpoint and worktree" in launched["content"]
    assert "Implement recovery.py and validate it." in launched["content"]

    resumed_task = task_queue.get(task["id"])
    assert resumed_task["budget_override"] == 37
    assert resumed_task["recovery_attempt"] == 1
    assert resumed_task["worktree_path"] == task["worktree_path"]
    assert resumed_task["worktree_branch"] == task["worktree_branch"]
    assert swarm.get_run(swarm_id)["status"] == "recovering"


def test_resume_rejects_duplicate_when_task_has_active_run(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    task, _ = _exhausted_task(project, session_id, swarm_id)
    stamp = now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO agent_runs(session_id,task_id,status,checkpoint,cancel_requested,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (session_id, task["id"], "running", "[]", 0, stamp, stamp),
        )

    with pytest.raises(ValueError, match="active run"):
        task_queue.resume_task(task["id"], fresh_budget=20)


def test_missing_worktree_existing_branch_requires_explicit_recreation(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    task, prior_run_id = _exhausted_task(project, session_id, swarm_id)
    original_path = Path(task["worktree_path"])
    original_branch = task["worktree_branch"]
    root = Path(project["path"])
    _git(root, "worktree", "remove", str(original_path))
    assert not original_path.exists()
    assert _git(root, "show-ref", "--verify", f"refs/heads/{original_branch}")

    with pytest.raises(ValueError, match="branch still exists"):
        task_queue.resume_task(task["id"], fresh_budget=20)

    monkeypatch.setattr(
        conversation_runtime,
        "launch",
        lambda session_id, content, resume_id=None, recovery_metadata=None: {
            "id": 8100,
            "session_id": session_id,
            "task_id": task["id"],
            "status": "running",
        },
    )
    result = task_queue.resume_task(
        task["id"],
        fresh_budget=20,
        recreate_missing_worktree=True,
    )

    assert result["prior_run_id"] == prior_run_id
    assert result["worktree_branch"] == original_branch
    assert Path(result["worktree_path"]).is_dir()
    assert _git(Path(result["worktree_path"]), "branch", "--show-current") == original_branch


def test_dependency_failure_is_structured_and_chain_can_be_retried_topologically(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    root, _ = _exhausted_task(project, session_id, swarm_id)
    child = task_queue.enqueue(
        int(project["id"]),
        session_id,
        "Reviewer",
        "Review root",
        swarm_id=swarm_id,
        source_kind="swarm_specialist",
        agent_role="tester",
        task_kind="tester",
        depends_on=[root["id"]],
        priority=120,
    )
    grandchild = task_queue.enqueue(
        int(project["id"]),
        session_id,
        "Consolidate",
        "Consolidate after review",
        swarm_id=swarm_id,
        source_kind="swarm_specialist",
        agent_role="documentation",
        task_kind="documentation",
        depends_on=[child["id"]],
        priority=140,
    )

    # Budget exhaustion is recoverable: descendants remain queued while the
    # Coordinator decides whether to resume the prerequisite.
    assert task_queue._claim_next() is None
    assert task_queue.get(child["id"])["status"] == "queued"
    assert task_queue.get(grandchild["id"])["status"] == "queued"

    # Once recovery is explicitly abandoned/declined, the prerequisite becomes
    # a real failure and structured dependency failure propagation applies.
    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET status='failed',error='Additional budget declined',completed_at=? WHERE id=?",
            (now(), root["id"]),
        )

    assert task_queue._claim_next() is None
    child_state = task_queue.get(child["id"])
    grandchild_state = task_queue.get(grandchild["id"])
    assert child_state["status"] == "dependency_failed"
    assert child_state["blocking_dependency_ids"] == [root["id"]]
    assert grandchild_state["status"] == "dependency_failed"
    assert grandchild_state["blocking_dependency_ids"] == [child["id"]]

    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET status='completed',result='Recovered with evidence',error='',completed_at=? WHERE id=?",
            (now(), root["id"]),
        )

    retry = task_queue.retry_blocked_dependants(root["id"], full_chain=True)

    assert retry["retried_task_ids"] == [child["id"], grandchild["id"]]
    assert task_queue.get(child["id"])["status"] == "queued"
    assert task_queue.get(grandchild["id"])["status"] == "queued"

    # Topology is preserved: child can claim first, grandchild remains queued.
    claimed = task_queue._claim_next()
    assert claimed["id"] == child["id"]
    assert task_queue.get(grandchild["id"])["status"] == "queued"


def test_completed_recovery_automatically_requeues_blocked_dependency_chain(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    root, _ = _exhausted_task(project, session_id, swarm_id)
    child = task_queue.enqueue(
        int(project["id"]), session_id, "Child", "after root",
        swarm_id=swarm_id, source_kind="swarm_specialist",
        agent_role="tester", task_kind="tester", depends_on=[root["id"]],
    )
    grandchild = task_queue.enqueue(
        int(project["id"]), session_id, "Grandchild", "after child",
        swarm_id=swarm_id, source_kind="swarm_specialist",
        agent_role="documentation", task_kind="documentation", depends_on=[child["id"]],
    )
    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET status='failed',error='declined',completed_at=? WHERE id=?",
            (now(), root["id"]),
        )
    assert task_queue._claim_next() is None
    assert task_queue.get(child["id"])["status"] == "dependency_failed"
    assert task_queue.get(grandchild["id"])["status"] == "dependency_failed"

    with connect() as conn:
        conn.execute(
            "UPDATE background_tasks SET status='completed',recovery_attempt=1,result='Recovered',error='',completed_at=? WHERE id=?",
            (now(), root["id"]),
        )

    result = task_queue.auto_retry_recovered_dependants(root["id"])

    assert result["retried_task_ids"] == [child["id"], grandchild["id"]]
    assert task_queue.get(child["id"])["status"] == "queued"
    assert task_queue.get(grandchild["id"])["status"] == "queued"
    assert swarm.get_run(swarm_id)["status"] == "recovering"
    events = swarm.coordinator_events(swarm_id)
    assert any(
        item["kind"] == "dependency_retry_started"
        and child["id"] in item["payload"]["retried_task_ids"]
        and grandchild["id"] in item["payload"]["retried_task_ids"]
        for item in events
    )


def test_normal_completion_does_not_auto_retry_dependency_failures(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    root = task_queue.enqueue(
        int(project["id"]), session_id, "Normal", "normal task",
        swarm_id=swarm_id, source_kind="swarm_specialist",
        agent_role="backend", task_kind="backend",
    )
    child = task_queue.enqueue(
        int(project["id"]), session_id, "Blocked", "blocked",
        swarm_id=swarm_id, source_kind="swarm_specialist",
        agent_role="tester", task_kind="tester", depends_on=[root["id"]],
    )
    with connect() as conn:
        conn.execute("UPDATE background_tasks SET status='completed',completed_at=? WHERE id=?", (now(), root["id"]))
        conn.execute(
            "UPDATE background_tasks SET status='dependency_failed',blocking_dependency_ids=?,completed_at=? WHERE id=?",
            (f"[{root['id']}]", now(), child["id"]),
        )

    result = task_queue.auto_retry_recovered_dependants(root["id"])

    assert result["retried_task_ids"] == []
    assert task_queue.get(child["id"])["status"] == "dependency_failed"


def test_board_blocks_integration_while_recovery_is_unresolved(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    task, _ = _exhausted_task(project, session_id, swarm_id)

    board = swarm.board_snapshot(swarm_id)

    assert board["summary"]["recovery_available"] is True
    assert board["summary"]["integration_ready"] is False
    blocker = next(item for item in board["summary"]["recovery_blockers"] if item["task_id"] == task["id"])
    assert blocker["status"] == "budget_exhausted"
    assert "needs recovery" in " ".join(board["summary"]["integration_blockers"])


def test_recovery_info_reports_fresh_budget_and_checkpoint(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    task, prior_run_id = _exhausted_task(project, session_id, swarm_id)
    with connect() as conn:
        profile_id = conn.execute("SELECT profile_id FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()["profile_id"]
        conn.execute(
            "UPDATE swarm_profiles SET agent_tool_budget=30,resumed_task_tool_budget=44,max_recovery_attempts=3 WHERE id=?",
            (profile_id,),
        )

    info = task_queue.recovery_info(task["id"])

    assert info["prior_run_id"] == prior_run_id
    assert info["checkpoint_available"] is True
    assert info["checkpoint_bytes"] > 0
    assert info["worktree_available"] is True
    assert info["branch_available"] is True
    assert info["previous_budget"] == 30
    assert info["resumed_budget"] == 44
    assert info["max_recovery_attempts"] == 3
    assert info["can_resume"] is True


def test_recovery_limit_disables_resume_and_blocks_more_automatic_recovery(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    task, prior_run_id = _exhausted_task(project, session_id, swarm_id)
    with connect() as conn:
        profile_id = conn.execute(
            "SELECT profile_id FROM swarm_runs WHERE id=?",
            (swarm_id,),
        ).fetchone()["profile_id"]
        conn.execute(
            "UPDATE swarm_profiles SET max_recovery_attempts=2 WHERE id=?",
            (profile_id,),
        )
        conn.execute(
            "UPDATE background_tasks SET recovery_attempt=2 WHERE id=?",
            (task["id"],),
        )

    info = task_queue.recovery_info(task["id"])

    assert info["prior_run_id"] == prior_run_id
    assert info["recovery_attempt"] == 2
    assert info["max_recovery_attempts"] == 2
    assert info["recovery_limit_reached"] is True
    assert info["can_resume"] is False

    with pytest.raises(ValueError, match="maximum recovery attempts"):
        task_queue.resume_task(task["id"], fresh_budget=20)

    board = swarm.board_snapshot(swarm_id)
    assert any(
        blocker["task_id"] == task["id"]
        and blocker["recovery"]["recovery_limit_reached"] is True
        for blocker in board["summary"]["recovery_blockers"]
    )
    assert f"#{task['id']} recovery limit reached" in board["summary"]["integration_blockers"]


def test_user_can_explicitly_override_recovery_limit_for_one_more_attempt(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    task, prior_run_id = _exhausted_task(project, session_id, swarm_id)
    with connect() as conn:
        profile_id = conn.execute(
            "SELECT profile_id FROM swarm_runs WHERE id=?",
            (swarm_id,),
        ).fetchone()["profile_id"]
        conn.execute("UPDATE swarm_profiles SET max_recovery_attempts=1 WHERE id=?", (profile_id,))
        conn.execute("UPDATE background_tasks SET recovery_attempt=1 WHERE id=?", (task["id"],))

    launched = {}
    monkeypatch.setattr(
        conversation_runtime,
        "launch",
        lambda session_id, content, resume_id=None, recovery_metadata=None: launched.update(
            {"session_id": session_id, "resume_id": resume_id, "metadata": recovery_metadata}
        ) or {"id": 8200, "session_id": session_id, "task_id": task["id"], "status": "running"},
    )

    with pytest.raises(ValueError, match="maximum recovery attempts"):
        task_queue.resume_task(task["id"], fresh_budget=20)

    resumed = task_queue.resume_task(
        task["id"],
        fresh_budget=20,
        override_recovery_limit=True,
    )

    assert resumed["prior_run_id"] == prior_run_id
    assert task_queue.get(task["id"])["recovery_attempt"] == 2
    assert launched["metadata"]["recovery_attempt"] == 2


def test_user_can_abandon_recovery_and_pending_budget_request_is_closed(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    task, prior_run_id = _exhausted_task(project, session_id, swarm_id)
    request = swarm.ensure_budget_request(
        swarm_id,
        scope="agent",
        task_id=task["id"],
        run_id=prior_run_id,
        requested_amount=25,
        reason="Need one more attempt",
    )

    abandoned = task_queue.abandon_recovery(task["id"])

    assert abandoned["status"] == "failed"
    assert "abandoned" in abandoned["error"].lower()
    pending = swarm.budget_requests(swarm_id, pending_only=True)
    assert not [item for item in pending if item["id"] == request["id"]]
    decided = next(item for item in swarm.budget_requests(swarm_id) if item["id"] == request["id"])
    assert decided["status"] == "declined"
    assert decided["decided_by"] == "user"


def test_coding_swarm_task_empty_noop_becomes_recoverable_no_progress(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    task = task_queue.enqueue(
        int(project["id"]),
        session_id,
        "Implement missing feature",
        "Change the code and run validation.",
        swarm_id=swarm_id,
        source_kind="swarm_specialist",
        agent_role="backend",
        task_kind="backend",
    )
    monkeypatch.setattr(task_queue, "_handler", lambda task: "")

    assert task_queue.run_once() is True

    state = task_queue.get(task["id"])
    assert state["status"] == "no_progress"
    assert "without a committed or working-tree change" in state["no_progress_reason"].lower()
    assert swarm.get_run(swarm_id)["status"] == "recovery_available"
    evidence = state["completion_evidence"]
    if isinstance(evidence, str):
        import json
        evidence = json.loads(evidence)
    assert evidence["required"] is True
    assert evidence["ok"] is False
    assert evidence["head_changed"] is False
    assert evidence["diff_files"] == []
    assert evidence["write_tools"] == []
    assert evidence["validation_commands"] == []


def test_coding_swarm_task_with_generic_success_message_but_no_changes_is_no_progress(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    task = task_queue.enqueue(
        int(project["id"]),
        session_id,
        "Implement missing feature",
        "Change the code and run validation.",
        swarm_id=swarm_id,
        source_kind="swarm_specialist",
        agent_role="backend",
        task_kind="backend",
    )
    monkeypatch.setattr(task_queue, "_handler", lambda task: "Implemented successfully.")

    assert task_queue.run_once() is True

    state = task_queue.get(task["id"])
    assert state["status"] == "no_progress"
    assert "without a committed or working-tree change" in state["no_progress_reason"].lower()
    evidence = state["completion_evidence"]
    if isinstance(evidence, str):
        import json
        evidence = json.loads(evidence)
    assert evidence["response_nonempty"] is True
    assert evidence["meaningful_change"] is False
    assert evidence["ok"] is False


def test_coding_swarm_task_with_workspace_change_can_complete(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    task = task_queue.enqueue(
        int(project["id"]),
        session_id,
        "Implement real feature",
        "Change the code.",
        swarm_id=swarm_id,
        source_kind="swarm_specialist",
        agent_role="backend",
        task_kind="backend",
    )

    def handler(claimed):
        target = Path(claimed["worktree_path"]) / "feature.py"
        target.write_text("value = 1\n", encoding="utf-8")
        return ""

    monkeypatch.setattr(task_queue, "_handler", handler)

    assert task_queue.run_once() is True

    state = task_queue.get(task["id"])
    assert state["status"] == "completed"
    assert state["worktree_branch"]
    assert _git(Path(state["worktree_path"]), "show", "--name-only", "--pretty=format:", "HEAD") == "feature.py"
    evidence = state["completion_evidence"]
    if isinstance(evidence, str):
        import json
        evidence = json.loads(evidence)
    assert evidence["ending_head"] == _git(Path(state["worktree_path"]), "rev-parse", "HEAD")
    assert evidence["auto_commit_sha"] == evidence["ending_head"]


def _wait_for(predicate, timeout: float = 3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for recovery state")


def test_no_progress_resumed_run_stays_recoverable_and_preserves_checkpoint(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    task, prior_run_id = _exhausted_task(project, session_id, swarm_id)
    with connect() as conn:
        prior_checkpoint = conn.execute(
            "SELECT checkpoint FROM agent_runs WHERE id=?",
            (prior_run_id,),
        ).fetchone()["checkpoint"]

    monkeypatch.setattr(
        "backend.app.main.run_session_agent",
        lambda session_id, content: {
            "id": 1,
            "role": "assistant",
            "content": "",
            "activities": [],
            "created_at": now(),
        },
    )

    resumed = task_queue.resume_task(task["id"], fresh_budget=20)
    run_id = resumed["run_id"]
    _wait_for(lambda: conversation_runtime.get(run_id)["status"] == "no_progress")

    state = task_queue.get(task["id"])
    assert state["status"] == "no_progress"
    assert "no meaningful" in state["no_progress_reason"].lower() or "empty final response" in state["no_progress_reason"].lower()
    assert swarm.get_run(swarm_id)["status"] == "recovery_available"

    info = task_queue.recovery_info(task["id"])
    assert info["can_resume"] is True
    assert info["prior_run_id"] == run_id
    assert info["checkpoint_available"] is True

    with connect() as conn:
        old_checkpoint = conn.execute("SELECT checkpoint FROM agent_runs WHERE id=?", (prior_run_id,)).fetchone()["checkpoint"]
    assert old_checkpoint == prior_checkpoint
    _wait_for(lambda: run_id not in conversation_runtime._threads)


def test_failed_resume_startup_preserves_previous_recovery_state(tmp_path, monkeypatch):
    project, session_id, swarm_id, _ = _seed_repo(tmp_path, monkeypatch)
    task, prior_run_id = _exhausted_task(project, session_id, swarm_id)
    before = task_queue.get(task["id"])
    with connect() as conn:
        checkpoint = conn.execute("SELECT checkpoint FROM agent_runs WHERE id=?", (prior_run_id,)).fetchone()["checkpoint"]

    monkeypatch.setattr(
        conversation_runtime,
        "launch",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("could not create resumed run")),
    )

    with pytest.raises(RuntimeError, match="could not create resumed run"):
        task_queue.resume_task(task["id"], fresh_budget=55)

    after = task_queue.get(task["id"])
    assert after["status"] == "budget_exhausted"
    assert after["error"] == before["error"]
    assert after["recovery_attempt"] == before["recovery_attempt"]
    assert after["budget_override"] == before["budget_override"]
    assert swarm.get_run(swarm_id)["status"] == "running"
    with connect() as conn:
        retained = conn.execute("SELECT checkpoint FROM agent_runs WHERE id=?", (prior_run_id,)).fetchone()["checkpoint"]
    assert retained == checkpoint
