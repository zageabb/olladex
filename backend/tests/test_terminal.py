from backend.app.services.terminal import blocked, requires_approval, run


def project(path, mode="assisted"):
    return {"id": 1, "name": "Terminal", "path": str(path), "model": "test", "approval_mode": mode}


def test_approval_modes(tmp_path):
    assert requires_approval(project(tmp_path, "review"), "pytest -q")
    assert not requires_approval(project(tmp_path, "assisted"), "pytest -q")
    assert requires_approval(project(tmp_path, "assisted"), "pip install package")
    assert not requires_approval(project(tmp_path, "autonomous"), "pip install package")


def test_terminal_runs_in_project_and_blocks_destruction(tmp_path):
    result = run(project(tmp_path), "pwd")
    assert result["exit_code"] == 0
    assert str(tmp_path) in result["output"]
    assert blocked("rm -rf /")
    assert run(project(tmp_path), "rm -rf /")["exit_code"] == 126

