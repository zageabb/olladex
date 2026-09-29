from backend.app.services import ollama, task_queue
from backend.app.services.ollama import execute_tool


def test_tool_failures_are_recoverable_observations(tmp_path):
    project = {"id": 1, "name": "Tools", "path": str(tmp_path), "model": "test"}
    result, activity = execute_tool(project, "read_file", {"path": "../outside.txt"})
    assert result["recoverable"] is True
    assert "escapes" in result["error"]
    assert activity["tool"] == "read_file"


def test_oversized_read_is_capped_without_a_failed_tool_call(tmp_path):
    target = tmp_path / "large.txt"
    target.write_text("".join(f"line {number}\n" for number in range(1, 1201)), encoding="utf-8")
    project = {"id": 1, "name": "Tools", "path": str(tmp_path), "model": "test"}

    result, activity = execute_tool(project, "read_file", {"path": "large.txt", "line_count": 2000})

    assert len(result.splitlines()) == 1000
    assert result.splitlines()[-1] == "line 1000"
    assert activity["arguments"]["line_count"] == 1000
    assert activity["warnings"] == ["Requested 2,000 lines; capped at the 1,000-line maximum"]
    assert "Tool failed" not in activity["summary"]


def test_validation_errors_are_concise_and_do_not_expose_pydantic_urls(tmp_path):
    project = {"id": 1, "name": "Tools", "path": str(tmp_path), "model": "test"}

    result, activity = execute_tool(project, "read_file", {"path": "app.py", "start_line": -5})

    assert result["recoverable"] is True
    assert result["error"].startswith("Invalid read_file arguments")
    assert "start_line" in result["error"]
    assert "pydantic.dev" not in result["error"]
    assert "pydantic.dev" not in activity["summary"]


def test_read_tool_description_states_the_line_limit():
    read_tool = next(tool for tool in ollama.TOOLS if tool["function"]["name"] == "read_file")

    assert "1,000 lines" in read_tool["function"]["description"]


def test_interactive_write_file_remains_a_reviewable_proposal(tmp_path):
    target = tmp_path / "app.txt"
    target.write_text("before\n", encoding="utf-8")
    project = {"id": 1, "name": "Tools", "path": str(tmp_path), "model": "test"}

    result, activity = execute_tool(project, "write_file", {"path": "app.txt", "content": "after\n"})

    assert target.read_text(encoding="utf-8") == "before\n"
    assert result["status"] == "proposed"
    assert activity["tool"] == "write_file"
    assert "Proposed app.txt" in activity["summary"]


def test_background_task_write_file_updates_only_the_isolated_worktree(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    worktree_root = tmp_path / "task-worktree"
    project_root.mkdir()
    worktree_root.mkdir()
    (project_root / "app.txt").write_text("main copy\n", encoding="utf-8")
    (worktree_root / "app.txt").write_text("task copy\n", encoding="utf-8")
    project = {"id": 1, "name": "Tools", "path": str(project_root), "model": "test"}

    monkeypatch.setattr(task_queue, "cancel_requested", lambda: False)
    monkeypatch.setattr(task_queue, "current_task_id", lambda: 42)
    monkeypatch.setattr(task_queue, "current_worktree_path", lambda: str(worktree_root))

    result, activity = execute_tool(project, "write_file", {"path": "app.txt", "content": "changed by task\n"})

    assert (project_root / "app.txt").read_text(encoding="utf-8") == "main copy\n"
    assert (worktree_root / "app.txt").read_text(encoding="utf-8") == "changed by task\n"
    assert result["status"] == "applied"
    assert result["workspace"] == "task_worktree"
    assert result["task_id"] == 42
    assert activity["tool"] == "task_write_file"
    assert "isolated task workspace" in activity["summary"]
    assert activity["result"] == {"path": "app.txt", "status": "applied", "task_id": 42, "workspace": "task_worktree"}


def test_background_task_write_is_blocked_without_an_isolated_worktree(tmp_path, monkeypatch):
    target = tmp_path / "app.txt"
    target.write_text("main copy\n", encoding="utf-8")
    project = {"id": 1, "name": "Tools", "path": str(tmp_path), "model": "test"}

    monkeypatch.setattr(task_queue, "cancel_requested", lambda: False)
    monkeypatch.setattr(task_queue, "current_task_id", lambda: 99)
    monkeypatch.setattr(task_queue, "current_worktree_path", lambda: "")

    result, activity = execute_tool(project, "write_file", {"path": "app.txt", "content": "unsafe change\n"})

    assert target.read_text(encoding="utf-8") == "main copy\n"
    assert result["recoverable"] is True
    assert "isolated Git worktree" in result["error"]
    assert activity["tool"] == "write_file"


def test_swarm_blackboard_tools_are_strictly_validated():
    finding = ollama.validate_arguments("swarm_publish_finding", {"content": "Evidence", "key": "auth"})
    assert finding == {"content": "Evidence", "key": "auth"}

    read = ollama.validate_arguments("swarm_read_blackboard", {"category": "risk"})
    assert read == {"category": "risk"}

    handoff = ollama.validate_arguments("swarm_publish_handoff", {"content": "Done", "key": "final"})
    assert handoff == {"content": "Done", "key": "final"}

    help_request = ollama.validate_arguments("swarm_request_help", {"content": "Need an independent tester", "key": "tests"})
    assert help_request == {"content": "Need an independent tester", "key": "tests"}


def test_update_progress_persists_step_based_percentage(tmp_path, monkeypatch):
    project = {"id": 1, "name": "Tools", "path": str(tmp_path), "model": "test"}
    persisted = {}
    emitted = []

    monkeypatch.setattr(task_queue, "cancel_requested", lambda: False)
    monkeypatch.setattr(task_queue, "current_task_id", lambda: 42)
    monkeypatch.setattr(task_queue, "set_progress", lambda task_id, progress, activity="": persisted.update({
        "task_id": task_id, "progress": progress, "activity": activity
    }))
    monkeypatch.setattr(ollama.runtime, "cancelled", lambda: False)
    monkeypatch.setattr(ollama.runtime, "emit", lambda kind, payload: emitted.append((kind, payload)))

    result, activity = execute_tool(project, "update_progress", {
        "completed_steps": 2,
        "total_steps": 4,
        "current_step": "Run regression tests",
    })

    assert result["progress"] == 50
    assert persisted == {"task_id": 42, "progress": 50, "activity": "Run regression tests"}
    assert ("progress", result) in emitted
    assert activity["tool"] == "update_progress"


def test_update_progress_rejects_invalid_step_counts(tmp_path, monkeypatch):
    project = {"id": 1, "name": "Tools", "path": str(tmp_path), "model": "test"}
    monkeypatch.setattr(task_queue, "cancel_requested", lambda: False)
    monkeypatch.setattr(ollama.runtime, "cancelled", lambda: False)

    result, activity = execute_tool(project, "update_progress", {
        "completed_steps": 5,
        "total_steps": 4,
        "current_step": "Impossible",
    })

    assert result["recoverable"] is True
    assert "completed_steps" in result["error"]
    assert activity["tool"] == "update_progress"


def test_swarm_reviewer_cannot_mutate_git_for_integration(tmp_path, monkeypatch):
    project = {"id": 1, "name": "Tools", "path": str(tmp_path), "model": "test"}
    monkeypatch.setattr(task_queue, "cancel_requested", lambda: False)
    monkeypatch.setattr(
        task_queue,
        "current_task",
        lambda: {
            "id": 77,
            "task_kind": "reviewer",
            "source_kind": "swarm_reviewer",
        },
    )
    monkeypatch.setattr(task_queue, "current_task_id", lambda: 77)
    monkeypatch.setattr(task_queue, "current_worktree_path", lambda: str(tmp_path))
    monkeypatch.setattr(ollama.runtime, "current_id", lambda: None)
    monkeypatch.setattr(ollama.runtime, "cancelled", lambda: False)

    for command in [
        "git checkout main",
        "git switch main",
        "git merge olladex/task-1",
        "git cherry-pick deadbeef",
        "git reset --hard HEAD~1",
        "git worktree remove /tmp/other",
    ]:
        result, activity = execute_tool(project, "run_command", {"command": command})
        assert result["recoverable"] is True
        assert "may inspect Git but may not mutate" in result["error"]
        assert activity["tool"] == "run_command"


def test_swarm_reviewer_can_inspect_git(tmp_path, monkeypatch):
    project = {"id": 1, "name": "Tools", "path": str(tmp_path), "model": "test"}
    monkeypatch.setattr(task_queue, "cancel_requested", lambda: False)
    monkeypatch.setattr(
        task_queue,
        "current_task",
        lambda: {
            "id": 78,
            "task_kind": "reviewer",
            "source_kind": "swarm_reviewer",
        },
    )
    monkeypatch.setattr(task_queue, "current_task_id", lambda: 78)
    monkeypatch.setattr(task_queue, "current_worktree_path", lambda: str(tmp_path))
    monkeypatch.setattr(ollama.runtime, "current_id", lambda: None)
    monkeypatch.setattr(ollama.runtime, "cancelled", lambda: False)
    monkeypatch.setattr(ollama, "run_command", lambda project, command: {"command": command, "output": "clean", "exit_code": 0})

    result, _ = execute_tool(project, "run_command", {"command": "git status --short"})

    assert result["exit_code"] == 0
    assert result["output"] == "clean"
