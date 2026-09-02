from __future__ import annotations

import subprocess
from pathlib import Path

from backend.app.config import settings
from backend.app.services import worktrees


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_create_and_remove_task_worktree(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Olladex Test")
    _git(repo, "config", "user.email", "olladex-test@example.invalid")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")

    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    project = {"id": 7, "path": str(repo)}

    isolated = worktrees.create_for_task(project, 42)
    task_root = Path(isolated["path"])
    assert task_root.is_dir()
    assert isolated["branch"] == "olladex/task-42"

    (task_root / "README.md").write_text("isolated\n", encoding="utf-8")
    assert (repo / "README.md").read_text(encoding="utf-8") == "base\n"

    removed = worktrees.remove(project, isolated["path"], isolated["branch"], force=True)
    assert removed["removed"] is True
    assert not task_root.exists()
