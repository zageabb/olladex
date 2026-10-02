from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import workspace


STATUS_ORDER = {
    "BLOCKED": 0,
    "IN PROGRESS": 1,
    "PLANNED": 2,
    "AWAITING ACCEPTANCE": 3,
    "DEFERRED": 4,
    "COMPLETE": 9,
}
PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
DEVELOPMENT_MODES = {
    "explore": "Discuss ideas and architecture without changing code.",
    "plan": "Inspect repository evidence and update development state without implementation.",
    "build": "Implement the current objective and validate the changed behaviour.",
    "autonomous": "Continue until the objective is verified complete or a genuine stop condition is reached.",
    "verify": "Independently inspect implementation, validation and acceptance evidence.",
    "recover": "Perform root-cause analysis and resume stalled or failed work from repository evidence.",
    "release": "Run pre-merge review, delivery checks and post-merge verification.",
}


def normalise_mode(value: str) -> str:
    mode = str(value or "build").strip().lower()
    if mode not in DEVELOPMENT_MODES:
        raise ValueError(f"Unsupported development mode: {value}")
    return mode


@dataclass(frozen=True)
class DevelopmentItem:
    key: str
    title: str
    status: str
    priority: str
    body: str
    criteria: tuple[dict, ...]

    def as_dict(self) -> dict:
        completed = sum(1 for item in self.criteria if item["complete"])
        return {
            "key": self.key,
            "title": self.title,
            "status": self.status,
            "priority": self.priority,
            "body": self.body,
            "criteria": list(self.criteria),
            "criteria_completed": completed,
            "criteria_total": len(self.criteria),
        }


def _optional_text(project: dict, name: str) -> str:
    try:
        return workspace.read_text(project, name)
    except Exception:
        return ""


def _field(body: str, name: str, default: str = "") -> str:
    match = re.search(rf"(?im)^\s*{re.escape(name)}\s*:\s*(.+?)\s*$", body)
    return match.group(1).strip() if match else default


def _normalise_status(value: str) -> str:
    upper = value.upper()
    for status in STATUS_ORDER:
        if status in upper:
            return status
    return "PLANNED"


def _normalise_priority(value: str) -> str:
    upper = value.upper()
    for priority in PRIORITY_ORDER:
        if priority in upper:
            return priority
    return "MEDIUM"


def parse_development(markdown: str) -> dict:
    objective_match = re.search(
        r"(?ims)^##\s+Current objective\s*$\s*(.+?)(?=^##\s+|\Z)",
        markdown,
    )
    objective = objective_match.group(1).strip() if objective_match else ""

    item_matches = list(re.finditer(r"(?m)^###\s+(DEV-[A-Z0-9_-]+)\s+[—-]\s+(.+?)\s*$", markdown))
    items: list[DevelopmentItem] = []
    for index, match in enumerate(item_matches):
        start = match.end()
        end = item_matches[index + 1].start() if index + 1 < len(item_matches) else len(markdown)
        body = markdown[start:end].strip()
        criteria = tuple(
            {
                "complete": marker.strip().lower() == "x",
                "text": text.strip(),
            }
            for marker, text in re.findall(r"(?m)^\s*-\s*\[([ xX])\]\s+(.+?)\s*$", body)
        )
        items.append(
            DevelopmentItem(
                key=match.group(1).strip(),
                title=match.group(2).strip(),
                status=_normalise_status(_field(body, "Status", "PLANNED")),
                priority=_normalise_priority(_field(body, "Priority", "MEDIUM")),
                body=body,
                criteria=criteria,
            )
        )

    incomplete = [item for item in items if item.status != "COMPLETE"]
    current = min(
        incomplete,
        key=lambda item: (
            PRIORITY_ORDER.get(item.priority, 1),
            STATUS_ORDER.get(item.status, 5),
            items.index(item),
        ),
        default=None,
    )
    return {
        "current_objective": objective,
        "items": [item.as_dict() for item in items],
        "current_item": current.as_dict() if current else None,
    }


def snapshot(project: dict) -> dict:
    agents = _optional_text(project, "AGENTS.md")
    development = _optional_text(project, "DEVELOPMENT.md")
    parsed = parse_development(development) if development else {
        "current_objective": "",
        "items": [],
        "current_item": None,
    }
    return {
        "agents_present": bool(agents),
        "development_present": bool(development),
        "agents_markdown": agents,
        "development_markdown": development,
        **parsed,
    }


def orchestration_context(project: dict, *, max_chars: int = 14000) -> str:
    state = snapshot(project)
    parts: list[str] = []
    if state["agents_present"]:
        parts.append("Repository agent contract (AGENTS.md):\n" + state["agents_markdown"])
    if state["development_present"]:
        current = state.get("current_item") or {}
        concise = [
            "Repository development state (DEVELOPMENT.md):",
            f"Current objective: {state.get('current_objective') or 'not declared'}",
        ]
        if current:
            concise.append(
                f"Highest-priority incomplete item: {current.get('key')} — {current.get('title')} "
                f"[{current.get('status')}, {current.get('priority')}]"
            )
            concise.append(current.get("body") or "")
        parts.append("\n".join(concise))
    mode = normalise_mode(project.get("development_mode") or "build")
    parts.append(
        "Development mode: "
        + mode
        + "\nMode contract: "
        + DEVELOPMENT_MODES[mode]
    )
    if not parts:
        return ""
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[Development context truncated]"
    return text


def resolve_action(project: dict, action: str) -> dict:
    state = snapshot(project)
    action = action.strip().lower().lstrip("/")
    current = state.get("current_item")
    if action in {"status", "next", "continue", "verify", "evidence", "sync-state"}:
        return {
            "action": action,
            "current_objective": state.get("current_objective") or "",
            "current_item": current,
            "agents_present": state["agents_present"],
            "development_present": state["development_present"],
        }
    raise ValueError(f"Unsupported development action: {action}")
