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

### DEV-003 — Done work

Status: ✅ COMPLETE
Priority: High
"""
    state = development_state.parse_development(markdown)

    assert state["current_objective"] == "Ship verified development state."
    assert state["current_item"]["key"] == "DEV-002"
    assert state["current_item"]["status"] == "IN PROGRESS"
    assert state["current_item"]["priority"] == "HIGH"


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


def test_orchestration_context_is_empty_when_state_files_are_absent(tmp_path):
    assert development_state.orchestration_context(_project(tmp_path)) == ""


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
