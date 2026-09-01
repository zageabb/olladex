from backend.app.services.session_summary import build


def test_session_summary_retains_tasks_tools_and_paths():
    messages = [
        {"role": "user", "content": "Add a health endpoint"},
        {"role": "assistant", "content": "I prepared the endpoint for review.", "activities": [{"tool": "write_file", "result": {"path": "routes/health.py"}}]},
    ]
    summary = build(messages)
    assert "Add a health endpoint" in summary
    assert "write_file ×1" in summary
    assert "routes/health.py" in summary

