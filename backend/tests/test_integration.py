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


def test_swarm_integration_uses_distinct_namespace(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    project = {"id": 24, "path": str(repo), "git_author_name": "Olladex Test", "git_author_email": "olladex-test@example.invalid"}
    first = _task_branch(project, 7, "swarm.txt", "swarm\n")

    result = integration.create(project, 7, [first["branch"]], "main", namespace="swarm")
    root = Path(result["path"])

    assert result["branch"] == "olladex/integration-swarm-7"
    assert root.name == "swarm-7"
    assert (root / "swarm.txt").read_text(encoding="utf-8") == "swarm\n"

    integration.remove(project, result["path"], result["branch"], force=True)


def test_local_promotion_fast_forwards_existing_main_worktree_and_exposes_files(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    project = {"id": 31, "path": str(repo), "git_author_name": "Olladex Test", "git_author_email": "olladex-test@example.invalid"}
    task = _task_branch(project, 31, "main.py", "print('hello')\n")
    result = integration.create(project, 31, [task["branch"]], "main", namespace="swarm")

    # main is already checked out in the configured project worktree; promotion must
    # not attempt to check it out anywhere else.
    assert _git(repo, "branch", "--show-current") == "main"
    promoted = integration.promote_to_main(project, result["path"], "main")

    assert promoted["main_path"] == str(repo.resolve())
    assert promoted["main_commit"] == promoted["integration_commit"]
    assert _git(repo, "branch", "--show-current") == "main"
    assert _git(repo, "rev-parse", "HEAD") == promoted["integration_commit"]
    assert (repo / "main.py").read_text(encoding="utf-8") == "print('hello')\n"
    assert Path(result["path"]).exists()
    assert _git(repo, "show-ref", "--verify", f"refs/heads/{result['branch']}")


def test_local_promotion_works_without_any_remote(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    project = {"id": 32, "path": str(repo), "git_author_name": "Olladex Test", "git_author_email": "olladex-test@example.invalid"}
    task = _task_branch(project, 32, "local.txt", "local only\n")
    result = integration.create(project, 32, [task["branch"]], "main", namespace="swarm")

    assert _git(repo, "remote") == ""
    promoted = integration.promote_to_main(project, result["path"], "main")

    assert promoted["main_commit"] == _git(repo, "rev-parse", "HEAD")
    assert (repo / "local.txt").exists()


def test_dirty_main_blocks_promotion_without_deleting_work(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    project = {"id": 33, "path": str(repo), "git_author_name": "Olladex Test", "git_author_email": "olladex-test@example.invalid"}
    task = _task_branch(project, 33, "feature.txt", "feature\n")
    result = integration.create(project, 33, [task["branch"]], "main", namespace="swarm")
    before = _git(repo, "rev-parse", "HEAD")
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(ValueError, match="dirty"):
        integration.promote_to_main(project, result["path"], "main")

    assert _git(repo, "rev-parse", "HEAD") == before
    assert Path(result["path"]).exists()
    assert _git(repo, "show-ref", "--verify", f"refs/heads/{result['branch']}")
    assert (repo / "dirty.txt").exists()


def test_divergent_main_blocks_ff_only_promotion_without_reset_or_cleanup(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    project = {"id": 34, "path": str(repo), "git_author_name": "Olladex Test", "git_author_email": "olladex-test@example.invalid"}
    task = _task_branch(project, 34, "feature.txt", "feature\n")
    result = integration.create(project, 34, [task["branch"]], "main", namespace="swarm")
    integration_head = _git(Path(result["path"]), "rev-parse", "HEAD")

    (repo / "main-only.txt").write_text("main diverged\n", encoding="utf-8")
    _git(repo, "add", "main-only.txt")
    _git(repo, "commit", "-m", "main diverged")
    divergent_head = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="diverged"):
        integration.promote_to_main(project, result["path"], "main")

    assert _git(repo, "rev-parse", "HEAD") == divergent_head
    assert _git(Path(result["path"]), "rev-parse", "HEAD") == integration_head
    assert Path(result["path"]).exists()
    assert _git(repo, "show-ref", "--verify", f"refs/heads/{result['branch']}")
    # No force reset/branch deletion/worktree deletion occurred.
    assert (repo / "main-only.txt").exists()
    assert (Path(result["path"]) / "feature.txt").exists()


def test_expected_deliverables_block_success_when_objective_evidence_is_missing(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    project = {"id": 35, "path": str(repo), "git_author_name": "Olladex Test", "git_author_email": "olladex-test@example.invalid"}
    task = _task_branch(project, 35, "other.py", "print('not enough')\n")
    result = integration.create(project, 35, [task["branch"]], "main", namespace="swarm")

    evidence = integration.validate_deliverables(
        project,
        result["path"],
        "Build main.py with tests, JSON persistence and backups.",
    )

    assert evidence["ok"] is False
    assert "main.py" in evidence["missing"]
    assert "tests" in evidence["missing"]
    assert "backup support" in evidence["missing"]
    assert "JSON persistence" in evidence["missing"]


def test_blocked_promotion_never_resets_deletes_branches_or_removes_worktrees(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    project = {"id": 36, "path": str(repo), "git_author_name": "Olladex Test", "git_author_email": "olladex-test@example.invalid"}
    task = _task_branch(project, 36, "feature.txt", "feature\n")
    result = integration.create(project, 36, [task["branch"]], "main", namespace="swarm")
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    original_git = worktrees._git
    calls: list[tuple[str, ...]] = []

    def recording_git(root, *args, **kwargs):
        calls.append(tuple(args))
        return original_git(root, *args, **kwargs)

    monkeypatch.setattr(worktrees, "_git", recording_git)

    with pytest.raises(ValueError, match="dirty"):
        integration.promote_to_main(project, result["path"], "main")

    forbidden = []
    for args in calls:
        if not args:
            continue
        if args[0] in {"reset", "clean"}:
            forbidden.append(args)
        if args[0] == "worktree" and len(args) > 1 and args[1] == "remove":
            forbidden.append(args)
        if args[0] == "branch" and any(flag in args[1:3] for flag in ("-d", "-D")):
            forbidden.append(args)
    assert forbidden == []
    assert Path(result["path"]).exists()
    assert _git(repo, "show-ref", "--verify", f"refs/heads/{result['branch']}")
