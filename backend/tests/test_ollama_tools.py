from backend.app.services import task_queue
from backend.app.services.ollama import execute_tool


def test_tool_failures_are_recoverable_observations(tmp_path):
    project = {"id": 1, "name": "Tools", "path": str(tmp_path), "model": "test"}
    result, activity = execute_tool(project, "read_file", {"path": "../outside.txt"})
    assert result["recoverable"] is True
    assert "escapes" in result["error"]
    assert activity["tool"] == "read_file"


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
