from __future__ import annotations

import subprocess

from backend.app.config import settings
from backend.app.services import worktrees


def _git(root, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
    return completed.stdout.strip()


def test_dependent_worktree_inherits_committed_specialist_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Olladex Test")
    _git(repo, "config", "user.email", "olladex-test@example.invalid")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")

    project = {
        "id": 1,
        "name": "Dependency handoff",
        "path": str(repo),
        "git_author_name": "Olladex Test",
        "git_author_email": "olladex-test@example.invalid",
    }

    first = worktrees.create_for_task(project, 1)
    first_project = worktrees.task_project(project, first["path"])
    first_file = worktrees.project_root(first_project) / "TASK_TEST.md"
    first_file.write_text("created by task one\n", encoding="utf-8")
    committed = worktrees.commit_all(project, first["path"], "create task test")
    assert committed["sha"]

    second = worktrees.create_for_task(project, 2)
    handoff = worktrees.inherit_branches(project, second["path"], [first["branch"]])
    second_project = worktrees.task_project(project, second["path"])
    inherited = worktrees.project_root(second_project) / "TASK_TEST.md"

    assert inherited.read_text(encoding="utf-8") == "created by task one\n"
    assert handoff["branch"] == second["branch"]
    assert first["branch"] != second["branch"]
    assert not (repo / "TASK_TEST.md").exists()
