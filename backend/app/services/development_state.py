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

DEVELOPMENT_ACTIONS = {
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
    if action in DEVELOPMENT_ACTIONS:
        return {
            "action": action,
            "mode": DEVELOPMENT_ACTIONS[action],
            "current_objective": state.get("current_objective") or "",
            "current_item": current,
            "agents_present": state["agents_present"],
            "development_present": state["development_present"],
        }
    raise ValueError(f"Unsupported development action: {action}")


def evidence_report(project: dict) -> dict:
    from ..database import connect
    from . import git

    state = snapshot(project)
    current = state.get("current_item") or {}
    with connect() as conn:
        tasks = [
            dict(row) for row in conn.execute(
                "SELECT id,title,status,source_kind,agent_role,completion_evidence,worktree_branch,completed_at "
                "FROM background_tasks WHERE project_id=? ORDER BY id DESC LIMIT 50",
                (project["id"],),
            )
        ]
        swarms = [
            dict(row) for row in conn.execute(
                "SELECT id,title,status,integration_branch,integration_check_status,promotion_status,promoted_commit,completed_at "
                "FROM swarm_runs WHERE project_id=? ORDER BY id DESC LIMIT 20",
                (project["id"],),
            )
        ]

    active_statuses = {"queued", "running", "waiting_for_input", "waiting_for_approval", "coordinating"}
    incomplete_statuses = {"budget_exhausted", "interrupted", "no_progress", "incomplete", "dependency_failed", "failed"}
    task_summary = {
        "total": len(tasks),
        "active": sum(1 for item in tasks if item["status"] in active_statuses),
        "incomplete": sum(1 for item in tasks if item["status"] in incomplete_statuses),
        "completed": sum(1 for item in tasks if item["status"] == "completed"),
    }
    latest_swarm = swarms[0] if swarms else None
    git_state = git.summary(project)
    criteria = current.get("criteria") or []
    criteria_complete = bool(criteria) and all(bool(item.get("complete")) for item in criteria)
    declared_complete = current.get("status") == "COMPLETE" if current else True
    no_active_work = task_summary["active"] == 0
    no_known_incomplete = task_summary["incomplete"] == 0
    repository_clean = not bool(git_state.get("changes"))

    result = "VERIFIED COMPLETE" if (
        current
        and declared_complete
        and criteria_complete
        and no_active_work
        and no_known_incomplete
        and repository_clean
    ) else "INCOMPLETE"

    return {
        "result": result,
        "current_objective": state.get("current_objective") or "",
        "current_item": current or None,
        "implementation": {
            "repository_state_present": state["development_present"] and state["agents_present"],
            "git_branch": git_state.get("branch") or "",
            "working_tree_clean": repository_clean,
            "recent_completed_tasks": task_summary["completed"],
        },
        "validation": {
            "active_tasks": task_summary["active"],
            "incomplete_tasks": task_summary["incomplete"],
            "latest_swarm": latest_swarm,
        },
        "acceptance": {
            "criteria_completed": current.get("criteria_completed", 0) if current else 0,
            "criteria_total": current.get("criteria_total", 0) if current else 0,
            "all_declared_criteria_complete": criteria_complete,
            "ledger_status": current.get("status") if current else "",
        },
        "tasks": tasks,
        "swarms": swarms,
    }



def ci_report(project: dict) -> dict:
    from . import git
    from . import github as github_service

    git_state = git.summary(project)
    branch = str(git_state.get("branch") or "")
    connection = github_service.status(project)
    if not connection.get("available") or not connection.get("authenticated"):
        return {
            "status": "unavailable",
            "branch": branch,
            "pull_request": None,
            "checks": [],
            "reason": connection.get("error") or "GitHub CLI is unavailable or unauthenticated.",
        }
    try:
        pull_requests = github_service.pull_requests(project, "open")
    except ValueError as exc:
        return {
            "status": "unavailable",
            "branch": branch,
            "pull_request": None,
            "checks": [],
            "reason": str(exc),
        }
    pull_request = next(
        (item for item in pull_requests if str(item.get("headRefName") or "") == branch),
        None,
    )
    if not pull_request:
        return {
            "status": "no_pull_request",
            "branch": branch,
            "pull_request": None,
            "checks": [],
            "reason": "No open pull request matches the current branch.",
        }
    checks = list(pull_request.get("statusCheckRollup") or [])
    normalized: list[dict] = []
    failing = pending = 0
    for item in checks:
        name = str(item.get("name") or item.get("context") or item.get("workflowName") or "check")
        conclusion = str(item.get("conclusion") or item.get("state") or item.get("status") or "").upper()
        if conclusion in {"FAILURE", "FAILED", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}:
            failing += 1
        elif conclusion not in {"SUCCESS", "PASSED", "NEUTRAL", "SKIPPED"}:
            pending += 1
        normalized.append({"name": name, "conclusion": conclusion})
    status = "failed" if failing else "pending" if pending or not checks else "passed"
    return {
        "status": status,
        "branch": branch,
        "pull_request": {
            "number": pull_request.get("number"),
            "title": pull_request.get("title") or "",
            "url": pull_request.get("url") or "",
            "is_draft": bool(pull_request.get("isDraft")),
            "review_decision": pull_request.get("reviewDecision") or "",
        },
        "checks": normalized,
        "failing": failing,
        "pending": pending,
        "reason": "",
    }


def review_report(project: dict) -> dict:
    from . import git

    state = snapshot(project)
    evidence = evidence_report(project)
    git_state = git.summary(project)
    diff = git.diff(project)
    blockers: list[str] = []
    if evidence["validation"]["active_tasks"]:
        blockers.append(f"{evidence['validation']['active_tasks']} development task(s) are still active")
    if evidence["validation"]["incomplete_tasks"]:
        blockers.append(f"{evidence['validation']['incomplete_tasks']} development task(s) remain incomplete or failed")
    current = state.get("current_item") or {}
    if current and current.get("criteria_total") and current.get("criteria_completed") != current.get("criteria_total"):
        blockers.append(
            f"{current.get('criteria_total', 0) - current.get('criteria_completed', 0)} acceptance criterion/criteria remain unchecked"
        )
    return {
        "current_item": current or None,
        "git": git_state,
        "diff": diff,
        "diff_present": bool(diff.strip()),
        "blockers": blockers,
        "ready_for_release_review": not blockers and not bool(git_state.get("changes")),
        "evidence": evidence,
    }


def recovery_report(project: dict) -> dict:
    from ..database import connect

    with connect() as conn:
        rows = [
            dict(row) for row in conn.execute(
                "SELECT id,title,status,recovery_attempt,root_cause_analysis,"
                "worktree_branch,current_activity,error FROM background_tasks "
                "WHERE project_id=? AND status IN ('budget_exhausted','interrupted','no_progress','incomplete','dependency_failed','failed') "
                "ORDER BY id DESC LIMIT 50",
                (project["id"],),
            )
        ]
    for item in rows:
        attempt = int(item.get("recovery_attempt") or 0)
        item["root_cause_required"] = attempt >= 2 and not bool(str(item.get("root_cause_analysis") or "").strip())
        item["root_cause_recorded"] = bool(str(item.get("root_cause_analysis") or "").strip())
    return {
        "count": len(rows),
        "recoverable": rows,
        "requires_root_cause": [item["id"] for item in rows if item["root_cause_required"]],
    }


def merge_report(project: dict) -> dict:
    state = snapshot(project)
    review = review_report(project)
    ci = ci_report(project)
    current = state.get("current_item") or {}
    blockers = list(review["blockers"])
    git_state = review["git"]
    if git_state.get("changes"):
        blockers.append("Working tree contains uncommitted changes")
    if ci["status"] == "failed":
        blockers.append("CI has failing checks")
    elif ci["status"] in {"pending", "unavailable"}:
        blockers.append("CI is not verified as passed")
    if current and current.get("status") != "COMPLETE":
        blockers.append(f"{current.get('key')} is still marked {current.get('status')}")
    return {
        "ready": not blockers,
        "target_branch": "main",
        "current_branch": git_state.get("branch") or "",
        "blockers": list(dict.fromkeys(blockers)),
        "review": review,
        "ci": ci,
    }


def sync_development(project: dict) -> dict:
    from datetime import UTC, datetime

    state = snapshot(project)
    current = state.get("current_item")
    if not state["development_present"]:
        raise ValueError("DEVELOPMENT.md is not present")
    if not current:
        return {"changed": False, "reason": "No incomplete development item is available to synchronise", "current_item": None}

    report = evidence_report(project)
    markdown = state["development_markdown"]
    today = datetime.now(UTC).date().isoformat()
    updated = re.sub(
        r"(?m)^Last reviewed:\s*.*$",
        f"Last reviewed: {today}",
        markdown,
        count=1,
    )

    if current["status"] == "PLANNED" and (
        report["implementation"]["recent_completed_tasks"] > 0
        or report["validation"]["active_tasks"] > 0
        or report["validation"]["latest_swarm"]
    ):
        pattern = (
            rf"(?ms)(^###\s+{re.escape(current['key'])}\s+[—-]\s+.*?$.*?^Status:\s*)[^\n]+"
        )
        updated = re.sub(pattern, rf"\1🔨 IN PROGRESS  ", updated, count=1)

    marker_start = f"<!-- OLLADEX:EVIDENCE:{current['key']}:START -->"
    marker_end = f"<!-- OLLADEX:EVIDENCE:{current['key']}:END -->"
    sync_block = (
        f"{marker_start}\n"
        "Repository evidence snapshot (managed by Olladex):\n"
        f"- Git branch: `{report['implementation']['git_branch'] or 'unknown'}`\n"
        f"- Working tree clean: {'yes' if report['implementation']['working_tree_clean'] else 'no'}\n"
        f"- Recent completed tasks: {report['implementation']['recent_completed_tasks']}\n"
        f"- Active tasks: {report['validation']['active_tasks']}\n"
        f"- Incomplete/failed tasks: {report['validation']['incomplete_tasks']}\n"
        f"- Acceptance criteria checked: {report['acceptance']['criteria_completed']}/{report['acceptance']['criteria_total']}\n"
        f"- Verification result: {report['result']}\n"
        f"{marker_end}"
    )
    if marker_start in updated and marker_end in updated:
        updated = re.sub(
            re.escape(marker_start) + r".*?" + re.escape(marker_end),
            sync_block,
            updated,
            count=1,
            flags=re.S,
        )
    else:
        item_pattern = rf"(?ms)(^###\s+{re.escape(current['key'])}\s+[—-]\s+.*?)(?=^###\s+DEV-|^##\s+|\Z)"
        match = re.search(item_pattern, updated)
        if not match:
            raise ValueError(f"Could not locate {current['key']} in DEVELOPMENT.md")
        item_text = match.group(1).rstrip()
        replacement = item_text + "\n\n" + sync_block + "\n\n"
        updated = updated[:match.start(1)] + replacement + updated[match.end(1):]

    changed = updated != markdown
    if changed:
        workspace.write_text(project, "DEVELOPMENT.md", updated)
    return {
        "changed": changed,
        "current_item": current,
        "evidence": report,
        "reason": "DEVELOPMENT.md reconciled from repository evidence" if changed else "DEVELOPMENT.md already matches repository evidence",
    }
