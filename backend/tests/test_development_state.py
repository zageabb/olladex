from pathlib import Path

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
