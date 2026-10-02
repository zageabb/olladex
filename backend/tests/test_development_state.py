from pathlib import Path
import subprocess

from backend.app.services import development_state


def _project(tmp_path: Path) -> dict:
    return {"id": 1, "name": "demo", "path": str(tmp_path)}


def test_parse_development_selects_high_priority_incomplete_item():
    markdown = """# Development Status

## Current objective

Ship verified development state.

### DEV-001 — Later work

Status: 🔵 PLANNED
Priority: Medium

Requirement:
Later.

### DEV-002 — Current work

Status: 🔨 IN PROGRESS
Priority: High

Requirement:
Now.

Completion criteria:
- [x] Parser exists.
- [ ] Objective is verified.

### DEV-003 — Done work

Status: ✅ COMPLETE
Priority: High
"""
    state = development_state.parse_development(markdown)

    assert state["current_objective"] == "Ship verified development state."
    assert state["current_item"]["key"] == "DEV-002"
    assert state["current_item"]["status"] == "IN PROGRESS"
    assert state["current_item"]["priority"] == "HIGH"
    assert state["current_item"]["criteria_completed"] == 1
    assert state["current_item"]["criteria_total"] == 2


def test_snapshot_reads_agents_and_development_from_repository(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# AGENTS.md\nUse repository evidence.\n", encoding="utf-8")
    (tmp_path / "DEVELOPMENT.md").write_text(
        """# Development Status

## Current objective

Continue objective.

### DEV-010 — Build state reader

Status: 🔨 IN PROGRESS
Priority: High

Requirement:
Read both files automatically.
""",
        encoding="utf-8",
    )

    state = development_state.snapshot(_project(tmp_path))

    assert state["agents_present"] is True
    assert state["development_present"] is True
    assert state["current_objective"] == "Continue objective."
    assert state["current_item"]["key"] == "DEV-010"


def test_orchestration_context_still_declares_mode_when_state_files_are_absent(tmp_path):
    context = development_state.orchestration_context(_project(tmp_path))
    assert "Development mode: build" in context
    assert "Repository agent contract" not in context


def test_resolve_action_returns_structured_repository_state(tmp_path):
    (tmp_path / "DEVELOPMENT.md").write_text(
        """## Current objective

Objective from repository.

### DEV-100 — Verify it

Status: 🔵 PLANNED
Priority: High
""",
        encoding="utf-8",
    )

    action = development_state.resolve_action(_project(tmp_path), "/continue")

    assert action["action"] == "continue"
    assert action["current_objective"] == "Objective from repository."
    assert action["current_item"]["key"] == "DEV-100"


def test_development_mode_is_explicit_and_injected_into_context(tmp_path):
    project = _project(tmp_path)
    project["development_mode"] = "autonomous"
    context = development_state.orchestration_context(project)

    assert "Development mode: autonomous" in context
    assert "Continue until the objective is verified complete" in context


def test_invalid_development_mode_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        development_state.normalise_mode("reckless")



def test_all_structured_development_actions_have_execution_modes(tmp_path):
    actions = {
        "status": "plan",
        "continue": "autonomous",
        "verify": "verify",
        "evidence": "verify",
        "ci": "verify",
        "review": "verify",
        "recover": "recover",
        "next": "plan",
        "merge": "release",
        "sync-state": "plan",
    }
    for action, mode in actions.items():
        resolved = development_state.resolve_action(_project(tmp_path), action)
        assert resolved["action"] == action
        assert resolved["mode"] == mode


def test_ci_report_matches_current_branch_pull_request(tmp_path, monkeypatch):
    from backend.app.services import git as git_service
    from backend.app.services import github as github_service

    monkeypatch.setattr(git_service, "summary", lambda project: {"branch": "feature/test"})
    monkeypatch.setattr(
        github_service,
        "status",
        lambda project: {"available": True, "authenticated": True, "repository": "owner/repo", "error": ""},
    )
    monkeypatch.setattr(
        github_service,
        "pull_requests",
        lambda project, state="open": [{
            "number": 7,
            "title": "Feature",
            "url": "https://example.invalid/pull/7",
            "headRefName": "feature/test",
            "isDraft": False,
            "reviewDecision": "APPROVED",
            "statusCheckRollup": [
                {"name": "Backend", "conclusion": "SUCCESS"},
                {"name": "Frontend", "conclusion": "SUCCESS"},
            ],
        }],
    )

    report = development_state.ci_report(_project(tmp_path))

    assert report["status"] == "passed"
    assert report["pull_request"]["number"] == 7
    assert len(report["checks"]) == 2


def test_sync_development_records_repository_evidence_without_claiming_completion(tmp_path, monkeypatch):
    path = tmp_path / "DEVELOPMENT.md"
    path.write_text(
        """# Development Status
Last reviewed: 2026-01-01

## Current objective

Build persistent state.

### DEV-100 — Persistent state

Status: 🔵 PLANNED
Priority: High

Completion criteria:
- [x] Parser exists.
- [ ] CI is verified.

## Maintenance rule

Keep this current.
""",
        encoding="utf-8",
    )
    project = _project(tmp_path)
    monkeypatch.setattr(
        development_state,
        "evidence_report",
        lambda project: {
            "result": "INCOMPLETE",
            "implementation": {
                "git_branch": "feature/test",
                "working_tree_clean": True,
                "recent_completed_tasks": 2,
            },
            "validation": {
                "active_tasks": 0,
                "incomplete_tasks": 0,
                "latest_swarm": {"id": 4, "status": "running"},
            },
            "acceptance": {
                "criteria_completed": 1,
                "criteria_total": 2,
            },
        },
    )

    result = development_state.sync_development(project)
    updated = path.read_text(encoding="utf-8")

    assert result["changed"] is True
    assert "Status: 🔨 IN PROGRESS" in updated
    assert "OLLADEX:EVIDENCE:DEV-100:START" in updated
    assert "Verification result: INCOMPLETE" in updated
    assert "Status: ✅ COMPLETE" not in updated

    second = development_state.sync_development(project)
    assert updated == path.read_text(encoding="utf-8")
    assert second["changed"] is False



def test_finalize_post_merge_state_commits_only_synced_development_evidence(tmp_path, monkeypatch):
    project = {
        "id": 1,
        "name": "demo",
        "path": str(tmp_path),
        "git_author_name": "Olladex Test",
        "git_author_email": "olladex-test@example.invalid",
    }
    (tmp_path / "DEVELOPMENT.md").write_text("# Development Status\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "add", "DEVELOPMENT.md"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "baseline"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    promoted = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    def sync(project_arg, item_key):
        (tmp_path / "DEVELOPMENT.md").write_text(
            "# Development Status\n\nRepository evidence snapshot\n",
            encoding="utf-8",
        )
        return {"changed": True, "current_item": {"key": item_key}, "evidence": {"result": "VERIFIED COMPLETE"}}

    monkeypatch.setattr(development_state, "sync_development", sync)
    monkeypatch.setattr(
        development_state,
        "evidence_report",
        lambda project_arg, item_key="": {"result": "VERIFIED COMPLETE"},
    )

    result = development_state.finalize_post_merge_state(
        project,
        "DEV-100",
        target_branch="main",
        promoted_commit=promoted,
    )

    assert result["verified"] is True
    assert result["state_sync_commit"]
    assert result["final_head"] == result["state_sync_commit"]
    assert result["final_head"] != promoted
    assert result["development_result"] == "VERIFIED COMPLETE"
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status == ""
