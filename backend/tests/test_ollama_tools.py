from backend.app.services.ollama import execute_tool


def test_tool_failures_are_recoverable_observations(tmp_path):
    project = {"id": 1, "name": "Tools", "path": str(tmp_path), "model": "test"}
    result, activity = execute_tool(project, "read_file", {"path": "../outside.txt"})
    assert result["recoverable"] is True
    assert "escapes" in result["error"]
    assert activity["tool"] == "read_file"
