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
        r"(?ims)^##\s+Current objective\s*$\s*(.+?)(?=^#{2,3}\s+|\Z)",
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


def _selected_item(state: dict, requested_key: str = "") -> dict:
    requested_key = str(requested_key or "").strip()
    if requested_key:
        return next(
            (item for item in state.get("items") or [] if item.get("key") == requested_key),
            {},
        )
    current = state.get("current_item")
    if current:
        return current
    items = list(state.get("items") or [])
    if not items:
        return {}
    return min(
        items,
        key=lambda item: (
            PRIORITY_ORDER.get(str(item.get("priority") or "MEDIUM"), 1),
            STATUS_ORDER.get(str(item.get("status") or "COMPLETE"), 9),
            items.index(item),
        ),
    )


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


def action_report(project: dict, action: str) -> dict:
    from . import git

    action = str(action or "").strip().lower().lstrip("/")
    resolved = resolve_action(project, action)
    current = resolved.get("current_item") or {}
    response = {
        **resolved,
        "git": git.summary(project),
        "execution": {
            "mode": resolved.get("mode") or "plan",
            "objective": current.get("title") or resolved.get("current_objective") or "",
            "dev_item": current.get("key") or "",
        },
    }
    if action in {"verify", "evidence"}:
        response["evidence"] = evidence_report(project)
    elif action == "ci":
        response["ci"] = ci_report(project)
    elif action == "review":
        response["review"] = review_report(project)
    elif action == "recover":
        response["recovery"] = recovery_report(project)
    elif action == "merge":
        response["merge"] = merge_report(project)
    elif action == "sync-state":
        response["sync"] = sync_development(project)
        refreshed = snapshot(project)
        response["current_objective"] = refreshed.get("current_objective") or ""
        response["current_item"] = refreshed.get("current_item")
    return response


def format_action_report(report: dict) -> str:
    action = str(report.get("action") or "status")
    current = report.get("current_item") or {}
    git_state = report.get("git") or {}
    lines = [
        f"Development action: /{action}",
        f"Objective: {report.get('current_objective') or 'Not declared'}",
    ]
    if current:
        lines.append(
            f"Current item: {current.get('key')} — {current.get('title')} "
            f"({current.get('status')}, {current.get('priority')})"
        )
        total = int(current.get("criteria_total") or 0)
        if total:
            lines.append(
                f"Acceptance criteria: {int(current.get('criteria_completed') or 0)}/{total}"
            )
    lines.append(
        f"Git: {git_state.get('branch') or 'unknown branch'}"
        + (" · clean" if not _meaningful_git_changes(git_state) else " · changes present")
    )
    if report.get("evidence"):
        evidence = report["evidence"]
        lines.append(f"Verification: {evidence.get('result') or 'INCOMPLETE'}")
        validation = evidence.get("validation") or {}
        lines.append(
            f"Tasks: {validation.get('active_tasks', 0)} active · "
            f"{validation.get('incomplete_tasks', 0)} incomplete/failed"
        )
    if report.get("ci"):
        ci = report["ci"]
        lines.append(f"CI: {ci.get('status') or 'unknown'}")
        if ci.get("reason"):
            lines.append(f"CI detail: {ci['reason']}")
    if report.get("review"):
        review = report["review"]
        blockers = review.get("blockers") or []
        lines.append(
            "Review: ready" if review.get("ready_for_release_review")
            else f"Review: blocked ({'; '.join(blockers) if blockers else 'evidence incomplete'})"
        )
    if report.get("recovery"):
        recovery = report["recovery"]
        lines.append(f"Recovery: {recovery.get('count', 0)} stopped/recoverable task(s)")
        if recovery.get("requires_root_cause"):
            lines.append(
                "Root-cause analysis required for: "
                + ", ".join(f"#{item}" for item in recovery["requires_root_cause"])
            )
    if report.get("merge"):
        merge = report["merge"]
        lines.append("Merge gate: ready" if merge.get("ready") else "Merge gate: blocked")
        for blocker in merge.get("blockers") or []:
            lines.append(f"- {blocker}")
    if report.get("sync"):
        sync = report["sync"]
        lines.append(f"State sync: {sync.get('reason') or ('updated' if sync.get('changed') else 'unchanged')}")
    if report.get("execution_started"):
        execution = report["execution_started"]
        if execution.get("kind") == "advanced_orchestration":
            lines.append(f"Execution started: Advanced orchestration #{execution.get('swarm_id') or 0}")
        elif execution.get("kind") == "merge":
            commit = str(execution.get("commit") or "")
            lines.append(
                "Execution started: merge"
                + (f" · {commit[:12]}" if commit else "")
            )
    if report.get("execution_error"):
        lines.append(f"Execution blocked: {report['execution_error']}")
    return "\n".join(lines)


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


def _meaningful_git_changes(git_state: dict) -> list[dict]:
    return [
        item for item in (git_state.get("changes") or [])
        if not str(item.get("path") or "").startswith(".olladex/")
        and str(item.get("path") or "") != ".olladex"
    ]


def _criteria_require_ci(criteria: list[dict]) -> bool:
    return any(
        re.search(r"\b(?:CI|continuous integration|GitHub Actions)\b", str(item.get("text") or ""), re.I)
        for item in criteria
    )


def _criteria_require_delivery(criteria: list[dict]) -> bool:
    return any(
        re.search(
            r"\b(?:merge|merged|post[- ]merge|intended branch|promotion|promoted|delivery)\b",
            str(item.get("text") or ""),
            re.I,
        )
        for item in criteria
    )


def evidence_report(project: dict, item_key: str = "") -> dict:
    from ..database import connect
    from . import git

    state = snapshot(project)
    requested_key = str(item_key or "").strip()
    current = _selected_item(state, requested_key)
    effective_key = requested_key or str(current.get("key") or "")
    with connect() as conn:
        linked_swarm = None
        if effective_key:
            linked_swarm = conn.execute(
                "SELECT * FROM swarm_runs WHERE project_id=? AND development_item_key=? ORDER BY id DESC LIMIT 1",
                (project["id"], effective_key),
            ).fetchone()
        if linked_swarm:
            tasks = [
                dict(row) for row in conn.execute(
                    "SELECT id,title,status,source_kind,agent_role,completion_evidence,worktree_branch,completed_at "
                    "FROM background_tasks WHERE swarm_id=? ORDER BY id",
                    (linked_swarm["id"],),
                )
            ]
            swarms = [dict(linked_swarm)]
        else:
            tasks = [
                dict(row) for row in conn.execute(
                    "SELECT id,title,status,source_kind,agent_role,completion_evidence,worktree_branch,completed_at "
                    "FROM background_tasks WHERE project_id=? ORDER BY id DESC LIMIT 50",
                    (project["id"],),
                )
            ]
            swarms = [
                dict(row) for row in conn.execute(
                    "SELECT * FROM swarm_runs WHERE project_id=? ORDER BY id DESC LIMIT 20",
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
    repository_clean = not bool(_meaningful_git_changes(git_state))

    ci_required = _criteria_require_ci(criteria)
    ci = ci_report(project) if ci_required else None
    ci_verified = not ci_required or bool(ci and ci.get("status") == "passed")

    delivery_required = _criteria_require_delivery(criteria)
    delivery_complete = not delivery_required
    if delivery_required and effective_key and latest_swarm:
        delivery_complete = (
            latest_swarm.get("status") == "completed"
            and bool(str(latest_swarm.get("promoted_commit") or "").strip())
        )
    elif delivery_required:
        delivery_complete = str(git_state.get("branch") or "") == "main"

    evidence_complete = bool(
        current
        and criteria_complete
        and no_active_work
        and no_known_incomplete
        and repository_clean
        and ci_verified
        and delivery_complete
    )
    result = "VERIFIED COMPLETE" if evidence_complete else "INCOMPLETE"

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
            "ci_required": ci_required,
            "ci_verified": ci_verified,
            "ci": ci,
            "delivery_required": delivery_required,
            "delivery_complete": delivery_complete,
        },
        "acceptance": {
            "criteria_completed": current.get("criteria_completed", 0) if current else 0,
            "criteria_total": current.get("criteria_total", 0) if current else 0,
            "all_declared_criteria_complete": criteria_complete,
            "ledger_status": current.get("status") if current else "",
            "ledger_matches_evidence": bool(
                current
                and (
                    (evidence_complete and declared_complete)
                    or (not evidence_complete and not declared_complete)
                )
            ),
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
        try:
            checks = github_service.commit_checks(project)
        except ValueError as exc:
            return {
                "status": "unavailable",
                "branch": branch,
                "pull_request": None,
                "checks": [],
                "reason": str(exc),
            }
        normalized: list[dict] = []
        failing = pending = 0
        for item in checks:
            name = str(item.get("name") or "check")
            status_value = str(item.get("status") or "").upper()
            conclusion = str(item.get("conclusion") or "").upper()
            effective = conclusion or status_value
            if effective in {"FAILURE", "FAILED", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}:
                failing += 1
            elif effective not in {"SUCCESS", "PASSED", "NEUTRAL", "SKIPPED"}:
                pending += 1
            normalized.append({
                "name": name,
                "conclusion": conclusion,
                "status": status_value,
                "url": str(item.get("url") or ""),
            })
        status = "failed" if failing else "pending" if pending or not normalized else "passed"
        return {
            "status": status,
            "branch": branch,
            "pull_request": None,
            "checks": normalized,
            "failing": failing,
            "pending": pending,
            "reason": "" if normalized else "No GitHub checks are recorded for the current commit.",
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
    from ..database import connect
    from . import git, integration

    state = snapshot(project)
    current = state.get("current_item") or {}
    evidence = evidence_report(project, current.get("key") or "")
    git_state = git.summary(project)

    linked_swarm = None
    if current:
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM swarm_runs WHERE project_id=? AND development_item_key=? ORDER BY id DESC LIMIT 1",
                (project["id"], current.get("key") or ""),
            ).fetchone()
        linked_swarm = dict(row) if row else None

    diff = ""
    diff_source = "working_tree"
    if linked_swarm and linked_swarm.get("integration_path"):
        try:
            integration_state = integration.summary(project, str(linked_swarm["integration_path"]), "main")
            diff = str(integration_state.get("diff") or "")
            diff_source = "integration"
        except ValueError:
            diff = ""
    if not diff:
        code, branch_diff = git._git(project, "diff", "main...HEAD", "--", ".")
        if code == 0:
            diff = branch_diff[-750000:]
            diff_source = "branch"
        else:
            diff = git.diff(project)
            diff_source = "working_tree"

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
        "diff_source": diff_source,
        "diff_present": bool(diff.strip()),
        "linked_swarm": linked_swarm,
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
    from ..database import connect

    state = snapshot(project)
    review = review_report(project)
    ci = ci_report(project)
    current = state.get("current_item") or {}
    git_state = review["git"]
    blockers = [
        item for item in review["blockers"]
        if "acceptance criterion" not in item
    ]
    if _meaningful_git_changes(git_state):
        blockers.append("Working tree contains uncommitted changes")

    remote_present = bool(git_state.get("remotes"))
    warnings: list[str] = []
    if ci.get("pull_request"):
        if ci["status"] == "failed":
            blockers.append("CI has failing checks")
        elif ci["status"] != "passed":
            blockers.append("CI is not verified as passed")
    elif remote_present and ci["status"] == "unavailable":
        warnings.append("GitHub CI could not be inspected; no PR-specific CI gate was applied")

    criteria = current.get("criteria") or []
    post_merge_pattern = re.compile(
        r"\b(?:merge|merged|post[- ]merge|intended branch|development state update|development\.md is updated)\b",
        re.I,
    )
    pre_merge_unchecked = [
        item.get("text") or ""
        for item in criteria
        if not item.get("complete") and not post_merge_pattern.search(str(item.get("text") or ""))
    ]
    if pre_merge_unchecked:
        blockers.append(
            f"{len(pre_merge_unchecked)} pre-merge acceptance criterion/criteria remain unchecked"
        )

    linked_swarm = None
    if current:
        with connect() as conn:
            row = conn.execute(
                "SELECT id,title,status,integration_check_status,promotion_status,promoted_commit "
                "FROM swarm_runs WHERE project_id=? AND development_item_key=? ORDER BY id DESC LIMIT 1",
                (project["id"], current.get("key") or ""),
            ).fetchone()
        linked_swarm = dict(row) if row else None
    if linked_swarm:
        if linked_swarm.get("status") != "ready_to_promote":
            blockers.append(
                f"Advanced orchestration #{linked_swarm['id']} is {linked_swarm.get('status')}, not ready to promote"
            )
        if linked_swarm.get("integration_check_status") != "passed":
            blockers.append("Combined integration checks have not passed")

    return {
        "ready": not blockers,
        "target_branch": "main",
        "current_branch": git_state.get("branch") or "",
        "blockers": list(dict.fromkeys(blockers)),
        "review": review,
        "ci": ci,
        "linked_swarm": linked_swarm,
        "pre_merge_unchecked": pre_merge_unchecked,
        "warnings": warnings,
    }


def sync_development(project: dict, item_key: str = "") -> dict:
    from datetime import UTC, datetime

    state = snapshot(project)
    requested_key = str(item_key or "").strip()
    current = _selected_item(state, requested_key)
    if not state["development_present"]:
        raise ValueError("DEVELOPMENT.md is not present")
    if not current:
        return {"changed": False, "reason": "No matching development item is available to synchronise", "current_item": None}

    report = evidence_report(project, requested_key)
    markdown = state["development_markdown"]
    today = datetime.now(UTC).date().isoformat()
    updated = re.sub(
        r"(?m)^Last reviewed:\s*.*$",
        f"Last reviewed: {today}",
        markdown,
        count=1,
    )

    target_status = current["status"]
    if report["result"] == "VERIFIED COMPLETE":
        target_status = "COMPLETE"
    elif current["status"] == "COMPLETE":
        target_status = "IN PROGRESS"
    elif current["status"] == "PLANNED" and (
        report["implementation"]["recent_completed_tasks"] > 0
        or report["validation"]["active_tasks"] > 0
        or report["validation"]["latest_swarm"]
    ):
        target_status = "IN PROGRESS"

    if target_status != current["status"]:
        display = {
            "COMPLETE": "✅ COMPLETE  ",
            "IN PROGRESS": "🔨 IN PROGRESS  ",
            "PLANNED": "🔵 PLANNED  ",
            "BLOCKED": "🚫 BLOCKED  ",
            "AWAITING ACCEPTANCE": "⏳ AWAITING ACCEPTANCE  ",
            "DEFERRED": "💤 DEFERRED  ",
        }[target_status]
        pattern = (
            rf"(?ms)(^###\s+{re.escape(current['key'])}\s+[—-]\s+.*?$.*?^Status:\s*)[^\n]+"
        )
        updated = re.sub(pattern, rf"\1{display}", updated, count=1)

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
        "target_status": target_status,
        "evidence": report,
        "reason": "DEVELOPMENT.md reconciled from repository evidence" if changed else "DEVELOPMENT.md already matches repository evidence",
    }



def finalize_post_merge_state(
    project: dict,
    item_key: str,
    *,
    target_branch: str,
    promoted_commit: str,
) -> dict:
    from . import git

    item_key = str(item_key or "").strip()
    if not item_key:
        return {
            "verified": False,
            "state_sync_commit": "",
            "final_head": "",
            "reason": "No linked development item was recorded for this orchestration run.",
        }

    before = git.summary(project)
    if before.get("branch") != target_branch:
        raise ValueError(
            f"Post-merge verification requires target branch '{target_branch}' in the configured project worktree"
        )
    meaningful_before = _meaningful_git_changes(before)
    if meaningful_before:
        raise ValueError("Post-merge development-state sync requires a clean target worktree")

    code, _ = git._git(project, "merge-base", "--is-ancestor", promoted_commit, "HEAD")
    if code != 0:
        raise ValueError("Target branch does not contain the promoted integration commit")

    sync = sync_development(project, item_key)
    state_sync_commit = ""
    if sync["changed"]:
        after_sync = git.summary(project)
        unexpected = [
            item for item in _meaningful_git_changes(after_sync)
            if str(item.get("path") or "") != "DEVELOPMENT.md"
        ]
        if unexpected:
            raise ValueError(
                "Post-merge sync produced unexpected repository changes: "
                + ", ".join(str(item.get("path") or "") for item in unexpected)
            )
        git.stage(project, ["DEVELOPMENT.md"])
        committed = git.commit(project, f"docs: sync {item_key} development evidence")
        state_sync_commit = str(committed.get("sha") or "")

    final = git.summary(project)
    if _meaningful_git_changes(final):
        raise ValueError("Target worktree is not clean after development-state synchronisation")
    code, final_head = git._git(project, "rev-parse", "HEAD")
    if code:
        raise ValueError(final_head.strip() or "Could not resolve post-merge target HEAD")
    code, _ = git._git(project, "merge-base", "--is-ancestor", promoted_commit, "HEAD")
    if code != 0:
        raise ValueError("Promoted integration commit is missing after development-state synchronisation")

    evidence = evidence_report(project, item_key)
    return {
        "verified": True,
        "target_branch": target_branch,
        "promoted_commit": promoted_commit,
        "state_sync_commit": state_sync_commit,
        "final_head": final_head.strip(),
        "development_result": evidence["result"],
        "evidence": evidence,
        "sync": sync,
    }
