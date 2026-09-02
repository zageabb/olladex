from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.app.config import settings
from backend.app.services import integration, worktrees


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return completed.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Olladex Test")
    _git(repo, "config", "user.email", "olladex-test@example.invalid")
    _git(repo, "branch", "-M", "main")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def _task_branch(project: dict, task_id: int, filename: str, content: str) -> dict:
    isolated = worktrees.create_for_task(project, task_id)
    root = Path(isolated["path"])
    (root / filename).write_text(content, encoding="utf-8")
    worktrees.commit_all(project, isolated["path"], f"Task {task_id}")
    return isolated


def test_preflight_detects_overlapping_files(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    project = {"id": 21, "path": str(repo), "git_author_name": "Olladex Test", "git_author_email": "olladex-test@example.invalid"}
    first = _task_branch(project, 1, "shared.txt", "one\n")
    second = _task_branch(project, 2, "shared.txt", "two\n")

    result = integration.preflight(project, [first["branch"], second["branch"]], "main")

    assert result["overlaps"] == [{"path": "shared.txt", "branches": [first["branch"], second["branch"]]}]


def test_create_integration_worktree_combines_non_conflicting_branches(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    project = {"id": 22, "path": str(repo), "git_author_name": "Olladex Test", "git_author_email": "olladex-test@example.invalid"}
    first = _task_branch(project, 3, "backend.txt", "backend\n")
    second = _task_branch(project, 4, "frontend.txt", "frontend\n")

    result = integration.create(project, 99, [first["branch"], second["branch"]], "main")
    root = Path(result["path"])

    assert result["branch"] == "olladex/integration-99"
    assert (root / "backend.txt").read_text(encoding="utf-8") == "backend\n"
    assert (root / "frontend.txt").read_text(encoding="utf-8") == "frontend\n"
    assert len(result["applied"]) == 2

    checks = integration.run_checks(project, result["path"], "test -f backend.txt && test -f frontend.txt")
    assert checks["passed"] is True

    integration.remove(project, result["path"], result["branch"], force=True)


def test_create_integration_aborts_on_cherry_pick_conflict(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    project = {"id": 23, "path": str(repo), "git_author_name": "Olladex Test", "git_author_email": "olladex-test@example.invalid"}
    first = _task_branch(project, 5, "README.md", "first\n")
    second = _task_branch(project, 6, "README.md", "second\n")

    with pytest.raises(ValueError, match="Integration conflict"):
        integration.create(project, 100, [first["branch"], second["branch"]], "main")

    integration_root = settings.data_root / "integrations" / str(project["id"]) / "lead-100"
    assert integration_root.exists()
    assert _git(integration_root, "status", "--porcelain") == ""
