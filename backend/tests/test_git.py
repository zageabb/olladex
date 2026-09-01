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
