import subprocess

from backend.app.services import git


def project(path):
    return {"id": 1, "name": "Git", "path": str(path), "model": "test", "git_author_name": "Test User", "git_author_email": "test@example.com"}


def test_controlled_git_stage_commit_and_branch(tmp_path):
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    state = git.stage(project(tmp_path), ["README.md"])
    assert state["changes"][0]["staged"] is True
    unstaged = git.unstage(project(tmp_path), ["README.md"])
    assert unstaged["changes"][0]["staged"] is False
    git.stage(project(tmp_path), ["README.md"])
    committed = git.commit(project(tmp_path), "Initial test commit")
    assert len(committed["sha"]) == 40
    branched = git.create_branch(project(tmp_path), "feature/context", checkout=True)
    assert branched["branch"] == "feature/context"
    switched = git.checkout(project(tmp_path), "main")
    assert switched["branch"] == "main"


def test_remote_operation_is_prepared_before_execution(tmp_path):
    repository = tmp_path / "repository"
    remote = tmp_path / "remote.git"
    repository.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, capture_output=True)
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repository, check=True)
    (repository / "README.md").write_text("# Remote test\n", encoding="utf-8")
    git.stage(project(repository), ["README.md"])
    git.commit(project(repository), "Initial remote test")
    prepared = git.remote_operation(project(repository), "push", "origin", "main")
    assert prepared["command"] == "git push origin HEAD:main"
    result = git.execute_remote_operation(project(repository), prepared)
    assert result["summary"]["upstream"] == ""
    assert subprocess.run(["git", "show-ref", "--verify", "refs/heads/main"], cwd=remote, capture_output=True).returncode == 0
