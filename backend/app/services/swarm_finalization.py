from __future__ import annotations

import json
from pathlib import Path

from ..database import connect
from . import integration, worktrees


FAILED_TASK_STATUSES = {"failed", "budget_exhausted", "cancelled", "interrupted", "dependency_failed", "no_progress", "incomplete"}
NO_CHANGE_ROLES = {"researcher", "tester"}
VERIFICATION_KINDS = {"reviewer", "challenger"}


def _run(swarm_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
    if not row:
        raise ValueError("Swarm not found")
    return dict(row)


def _tasks(swarm_id: int) -> list[dict]:
    with connect() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM background_tasks WHERE swarm_id=? ORDER BY priority,id",
            (swarm_id,),
        )]


def _recovered_failure_ids(tasks: list[dict]) -> set[int]:
    recovered: set[int] = set()
    for task in tasks:
        if task.get("source_kind") != "swarm_recovery" or task.get("status") != "completed":
            continue
        source_ref = str(task.get("source_ref") or "")
        marker = ":failed:"
        if marker not in source_ref:
            continue
        for value in source_ref.split(marker, 1)[1].split(","):
            try:
                recovered.add(int(value))
            except (TypeError, ValueError):
                continue
    return recovered


def reviewer_report(swarm_id: int) -> dict:
    tasks = _tasks(swarm_id)
    reviewer = next((item for item in tasks if item.get("task_kind") == "reviewer"), None)
    with connect() as conn:
        profile = conn.execute(
            "SELECT sp.require_reviewer FROM swarm_runs sr "
            "LEFT JOIN swarm_profiles sp ON sp.id=sr.profile_id WHERE sr.id=?",
            (swarm_id,),
        ).fetchone()
    required = bool(profile and profile["require_reviewer"])
    if not reviewer:
        if required:
            raise ValueError("Required reviewer task is missing")
        return {"required": False, "task_id": None, "report": ""}
    if reviewer.get("status") != "completed":
        raise ValueError("Reviewer has not completed successfully")
    report = str(reviewer.get("result") or "").strip()
    if len(report) < 40:
        raise ValueError("Reviewer final report is empty or too short to support finalization")
    return {"required": required, "task_id": int(reviewer["id"]), "report": report}


def _dependency_ids(task: dict) -> list[int]:
    value = task.get("depends_on")
    if isinstance(value, list):
        return [int(item) for item in value if int(item) > 0]
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [int(item) for item in parsed if int(item) > 0]


def _unique_task_changes(task: dict, tasks_by_id: dict[int, dict], base: str) -> dict:
    path = str(task.get("worktree_path") or "").strip()
    branch = str(task.get("worktree_branch") or "").strip()
    if not path or not branch:
        return {"commits": [], "files": []}
    exclude_refs = [base]
    for dependency_id in _dependency_ids(task):
        dependency = tasks_by_id.get(dependency_id)
        dependency_branch = str((dependency or {}).get("worktree_branch") or "").strip()
        if dependency_branch and dependency_branch not in exclude_refs:
            exclude_refs.append(dependency_branch)
    args = ["rev-list", branch, "--not", *exclude_refs]
    code, output = worktrees._git(Path(path), *args)
    if code:
        raise ValueError(output.strip() or f"Could not inspect unique commits for task #{task['id']}")
    commits = [line.strip() for line in output.splitlines() if line.strip()]
    files: list[str] = []
    for sha in commits:
        code, changed = worktrees._git(
            Path(path),
            "show", "--pretty=format:", "--name-only", sha, "--",
        )
        if code:
            raise ValueError(changed.strip() or f"Could not inspect commit {sha[:12]} for task #{task['id']}")
        for item in changed.splitlines():
            item = item.strip()
            if item and item not in files:
                files.append(item)
    return {"commits": commits, "files": files}


def specialist_evidence(swarm_id: int, project: dict, base: str = "main") -> dict:
    tasks = _tasks(swarm_id)
    specialists = [item for item in tasks if item.get("task_kind") not in VERIFICATION_KINDS]
    tasks_by_id = {int(item["id"]): item for item in tasks}
    recovered_ids = _recovered_failure_ids(tasks)
    unresolved = [
        item for item in specialists
        if item.get("status") in FAILED_TASK_STATUSES and int(item["id"]) not in recovered_ids
    ]
    if unresolved:
        raise ValueError(
            "Specialist failure remains unresolved: "
            + ", ".join(f"#{item['id']} {item['title']}" for item in unresolved)
        )

    active = [
        item for item in specialists
        if item.get("status") in {"queued", "running", "waiting_for_input", "waiting_for_approval"}
    ]
    if active:
        raise ValueError("Specialist work is still active")

    branches: list[str] = []
    changed_by_task: dict[int, list[str]] = {}
    evidence: list[dict] = []
    for task in specialists:
        if task.get("status") != "completed":
            if int(task["id"]) in recovered_ids:
                continue
            raise ValueError(f"Specialist task #{task['id']} is not completed")

        branch = str(task.get("worktree_branch") or "").strip()
        path = str(task.get("worktree_path") or "").strip()
        if not branch or not path:
            raise ValueError(f"Completed specialist task #{task['id']} has no managed worktree branch")
        state = worktrees.summary(project, path, base)
        if state.get("changes"):
            raise ValueError(f"Specialist task #{task['id']} still has uncommitted worktree changes")
        changed = integration.changed_files(project, branch, base)
        unique = _unique_task_changes(task, tasks_by_id, base)
        changed_by_task[int(task["id"])] = unique["files"]

        completion_evidence = {}
        try:
            completion_evidence = json.loads(str(task.get("completion_evidence") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            completion_evidence = {}
        recorded_head = str(completion_evidence.get("ending_head") or "").strip()
        if completion_evidence.get("required") and recorded_head:
            current_head = str(state.get("head") or "").strip()
            if current_head and current_head != recorded_head:
                raise ValueError(
                    f"Specialist task #{task['id']} branch changed after task completion "
                    f"({recorded_head[:12]} -> {current_head[:12]}). Reviewer evidence is stale; "
                    "rerun the specialist/reviewer flow before integration."
                )

        if task.get("source_kind") == "swarm_recovery" and not unique["files"]:
            raise ValueError(f"Recovery task #{task['id']} completed without a meaningful committed diff")
        role = str(task.get("task_kind") or task.get("agent_role") or "worker")
        if role not in NO_CHANGE_ROLES and task.get("source_kind") in {
            "swarm_specialist", "swarm_recovery", "swarm_followup", "swarm_help"
        } and not unique["files"]:
            raise ValueError(f"Implementation task #{task['id']} completed without committed changes")

        if changed and branch not in branches:
            branches.append(branch)
        evidence.append({
            "task_id": int(task["id"]),
            "title": task.get("title") or "",
            "role": role,
            "branch": branch,
            "head": state.get("head") or "",
            "changed_files": changed,
            "unique_changed_files": unique["files"],
            "unique_commits": unique["commits"],
            "recovery": task.get("source_kind") == "swarm_recovery",
        })

    if not branches:
        raise ValueError("No committed specialist changes are available for integration")
    return {
        "branches": branches,
        "tasks": evidence,
        "changed_by_task": changed_by_task,
        "recovered_failure_ids": sorted(recovered_ids),
    }


def review_gate(swarm_id: int, project: dict, base: str = "main") -> dict:
    run = _run(swarm_id)
    report = reviewer_report(swarm_id)
    specialist = specialist_evidence(swarm_id, project, base)
    return {
        "swarm_id": swarm_id,
        "objective": run.get("objective") or "",
        "reviewer": report,
        "specialists": specialist,
    }


def prepare_integration(swarm_id: int, project: dict, base: str = "main") -> dict:
    evidence = review_gate(swarm_id, project, base)
    result = integration.create(
        project,
        swarm_id,
        evidence["specialists"]["branches"],
        base,
        namespace="swarm",
    )
    return {**result, "evidence": evidence}


def promotion_gate(swarm_id: int, project: dict, base: str = "main") -> dict:
    run = _run(swarm_id)
    evidence = review_gate(swarm_id, project, base)
    if run.get("integration_check_status") != "passed":
        raise ValueError("Configured combined checks have not passed")
    path = str(run.get("integration_path") or "").strip()
    if not path:
        raise ValueError("Integration worktree has not been prepared")

    try:
        source_heads = json.loads(str(run.get("integration_source_heads") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        source_heads = {}

    stale_sources: list[str] = []
    for task in evidence["specialists"]["tasks"]:
        branch = str(task.get("branch") or "").strip()
        if not branch:
            continue
        recorded_head = str(source_heads.get(branch) or "").strip()
        current_head = str(task.get("head") or "").strip()
        if recorded_head and current_head and recorded_head != current_head:
            stale_sources.append(
                f"#{task['task_id']} {branch} {recorded_head[:12]} -> {current_head[:12]}"
            )

    if stale_sources:
        raise ValueError(
            "Integration branch is stale because specialist branch heads changed after integration was prepared: "
            + ", ".join(stale_sources)
            + ". Rebuild the integration branch and rerun combined checks."
        )

    ready = integration.verify_integration_ready(
        project,
        path,
        str(run.get("objective") or ""),
    )
    return {
        "swarm_id": swarm_id,
        "reviewer": evidence["reviewer"],
        "specialists": evidence["specialists"],
        "integration": ready,
    }


def promoted_deliverables(swarm_id: int, project: dict) -> dict:
    run = _run(swarm_id)
    return integration.validate_deliverables(
        project,
        str(project["path"]),
        str(run.get("objective") or ""),
    )
