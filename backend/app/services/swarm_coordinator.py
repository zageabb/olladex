from __future__ import annotations

import json
import threading
import time

from ..database import connect, now
from . import integration, ollama, swarm, swarm_finalization, task_queue

_lock = threading.Lock()
_threads: dict[int, threading.Thread] = {}
_stop = threading.Event()


def start_active() -> None:
    _stop.clear()
    with connect() as conn:
        ids = [int(row["id"]) for row in conn.execute(
            "SELECT id FROM swarm_runs WHERE status IN ('running','waiting','reviewing','paused','recovery_available','recovering') AND cancel_requested=0"
        )]
    for swarm_id in ids:
        start(swarm_id)


def start(swarm_id: int) -> None:
    _stop.clear()
    with _lock:
        thread = _threads.get(swarm_id)
        if thread and thread.is_alive():
            return
        thread = threading.Thread(target=_loop, args=(swarm_id,), name=f"olladex-swarm-coordinator-{swarm_id}", daemon=True)
        _threads[swarm_id] = thread
        thread.start()


def stop(swarm_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE swarm_runs SET cancel_requested=1 WHERE id=?", (swarm_id,))


def shutdown() -> None:
    _stop.set()
    with _lock:
        threads = list(_threads.values())
    for thread in threads:
        thread.join(timeout=2)


def _loop(swarm_id: int) -> None:
    error_count = 0
    try:
        while not _stop.is_set():
            with connect() as conn:
                row = conn.execute("SELECT * FROM swarm_runs WHERE id=?", (swarm_id,)).fetchone()
            if not row:
                return
            run = dict(row)
            if run["status"] in {"completed", "failed", "cancelled", "ready_for_integration", "integrating", "checks_failed", "ready_to_promote"} or run["cancel_requested"]:
                return
            if run["status"] == "paused":
                time.sleep(.5)
                continue

            try:
                _reconcile(swarm_id)
                error_count = 0
            except Exception as exc:
                error_count += 1
                _publish_once(
                    swarm_id,
                    "risk",
                    f"coordinator-error-{error_count}",
                    f"Coordinator monitoring error: {exc}",
                )
                if error_count >= 3:
                    swarm.set_status(swarm_id, "failed")
                    return
            time.sleep(.75)
    finally:
        with _lock:
            _threads.pop(swarm_id, None)


def _reconcile(swarm_id: int) -> None:
    run = swarm.get_run(swarm_id)
    agents = run.get("agents") or []
    if not agents:
        return

    specialists = [item for item in agents if item.get("task_kind") not in {"reviewer", "challenger"}]
    reviewer = next((item for item in agents if item.get("task_kind") == "reviewer"), None)
    challenger = next((item for item in agents if item.get("task_kind") == "challenger"), None)

    budget_exhausted = [item for item in specialists if item.get("status") == "budget_exhausted"]
    failed = [item for item in specialists if item.get("status") in {"failed", "interrupted", "no_progress", "incomplete"}]
    dependency_blocked = [item for item in specialists if item.get("status") == "dependency_failed"]
    active = [item for item in specialists if item.get("status") in {"queued", "running", "waiting_for_input", "waiting_for_approval"}]
    completed = [item for item in specialists if item.get("status") == "completed"]
    recovered_ids = _recovered_failure_ids(completed)
    unresolved_failed = [item for item in failed if int(item["id"]) not in recovered_ids]

    if budget_exhausted:
        if run.get("status") != "recovery_available":
            swarm.set_status(swarm_id, "recovery_available")
        if _consider_budget_exhaustion(run, budget_exhausted, completed):
            return

    if dependency_blocked and not active:
        if run.get("status") != "recovery_available":
            swarm.set_status(swarm_id, "recovery_available")
        _publish_once(
            swarm_id,
            "risk",
            "dependency-recovery-blocked",
            "Advanced orchestration is waiting for recovery of dependency-blocked tasks: "
            + ", ".join(f"#{item['id']}" for item in dependency_blocked),
        )
        return

    verification_budget_exhausted = [
        item for item in (challenger, reviewer)
        if item and item.get("status") == "budget_exhausted"
    ]
    if verification_budget_exhausted:
        if run.get("status") != "recovery_available":
            swarm.set_status(swarm_id, "recovery_available")
        if _consider_budget_exhaustion(run, verification_budget_exhausted, completed):
            return

    verification_blocked = [
        item for item in (reviewer, challenger)
        if item and item.get("status") == "dependency_failed"
    ]
    if verification_blocked:
        if run.get("status") != "recovery_available":
            swarm.set_status(swarm_id, "recovery_available")
        _publish_once(
            swarm_id,
            "risk",
            "verification-dependency-blocked",
            "Final verification is blocked by recovered dependencies: "
            + ", ".join(f"#{item['id']}" for item in verification_blocked),
        )
        return

    if unresolved_failed and not active:
        _consider_recovery(run, unresolved_failed, completed)
        return

    if run["status"] in {"running", "recovering"} and _consider_help_request(run, completed):
        return

    effective_specialists = [item for item in specialists if item not in failed or int(item["id"]) in recovered_ids]
    if effective_specialists and all(
        item.get("status") == "completed" or int(item["id"]) in recovered_ids
        for item in effective_specialists
    ):
        if run["status"] == "recovering":
            swarm.set_status(swarm_id, "running")
            run["status"] = "running"
        if run["status"] == "running":
            if _consider_pre_review(run, profile=swarm.get_profile(int(run["profile_id"])), completed=completed):
                return
            swarm.set_status(swarm_id, "reviewing")
            run["status"] = "reviewing"
        if challenger and challenger.get("status") in {"queued", "running", "waiting_for_input", "waiting_for_approval"}:
            return
        if challenger and challenger.get("status") in {"failed", "cancelled", "interrupted"}:
            _publish_once(swarm_id, "risk", "challenger-failed", "The challenger did not complete successfully; final verification is incomplete.")
            if not reviewer:
                swarm.set_status(swarm_id, "failed")
                return
        if reviewer and reviewer.get("status") in {"queued", "running", "waiting_for_input", "waiting_for_approval"}:
            return
        if reviewer and reviewer.get("status") in {"failed", "cancelled", "interrupted"}:
            swarm.set_status(swarm_id, "failed")
            return
        if reviewer and reviewer.get("status") == "completed":
            _prepare_finalization(run)
            return
        if challenger and not reviewer and challenger.get("status") == "completed":
            _prepare_finalization(run)
            return
        if not reviewer and not challenger:
            _prepare_finalization(run)


def _prepare_finalization(run: dict) -> None:
    swarm_id = int(run["id"])
    current = swarm.get_run(swarm_id)
    if current.get("status") in {"ready_for_integration", "integrating", "checks_failed", "ready_to_promote", "completed"}:
        return
    project = _project(int(run["project_id"]))
    try:
        evidence = swarm_finalization.review_gate(swarm_id, project, "main")
    except ValueError as exc:
        _publish_once(
            swarm_id,
            "risk",
            "finalization-evidence-failed",
            f"Finalization blocked by missing evidence: {exc}",
        )
        swarm.set_status(swarm_id, "failed")
        return

    swarm.set_status(swarm_id, "ready_for_integration")
    try:
        result = integration.create(
            project,
            swarm_id,
            evidence["specialists"]["branches"],
            "main",
            namespace="swarm",
        )
    except ValueError as exc:
        _publish_once(
            swarm_id,
            "risk",
            "integration-preparation-failed",
            f"Deterministic integration could not be prepared: {exc}. Managed worktrees were preserved for recovery.",
        )
        return

    with connect() as conn:
        conn.execute(
            "UPDATE swarm_runs SET status='integrating',integration_path=?,integration_branch=?,"
            "integration_check_command='',integration_check_status='',integration_check_output='',"
            "integration_pushed=0,integration_pr_number=0,integration_pr_url='',integration_pr_state='',"
            "promotion_status='',promoted_commit='',promotion_output='' WHERE id=?",
            (result["path"], result["branch"], swarm_id),
        )
    swarm.emit_coordinator_event(
        swarm_id,
        "integration_prepared",
        {
            "path": result["path"],
            "branch": result["branch"],
            "head": result.get("head") or "",
            "specialist_branches": evidence["specialists"]["branches"],
            "reviewer_task_id": evidence["reviewer"].get("task_id"),
        },
    )


def _consider_budget_exhaustion(run: dict, exhausted: list[dict], completed: list[dict]) -> bool:
    swarm_id = int(run["id"])
    pending = swarm.budget_requests(swarm_id, pending_only=True)

    # A pending Coordinator-budget request prevents safe automated decisions.
    # Agent-specific requests, however, must not stall unrelated exhausted
    # specialists; pick the next exhausted task that has no request of its own.
    if any(item.get("scope") == "coordinator" for item in pending):
        return True
    pending_agent_ids = {
        int(item.get("task_id") or 0)
        for item in pending
        if item.get("scope") == "agent" and item.get("task_id")
    }
    target = next(
        (item for item in exhausted if int(item["id"]) not in pending_agent_ids),
        None,
    )
    if target is None:
        return True
    task_id = int(target["id"])
    run_id = int(target.get("run_id") or 0)
    prior_auto_grants = [
        item for item in swarm.budget_requests(swarm_id)
        if int(item.get("task_id") or 0) == task_id
        and item.get("status") == "granted"
        and item.get("decided_by") == "coordinator"
    ]
    if len(prior_auto_grants) >= 2:
        swarm.ensure_budget_request(
            swarm_id,
            scope="agent",
            task_id=task_id,
            run_id=run_id or None,
            requested_amount=25,
            reason="This agent has exhausted its budget repeatedly after Coordinator extensions; user guidance is required before adding more.",
        )
        return True
    if not run_id:
        swarm.ensure_budget_request(
            swarm_id,
            scope="agent",
            task_id=task_id,
            requested_amount=10,
            reason="Agent exhausted its budget but the prior run could not be resolved for checkpoint resume.",
        )
        return True

    decision = _budget_extension_decision(run, target, completed)
    action = str(decision.get("action") or "ask_user").lower()
    amount = max(1, min(int(decision.get("amount") or 10), 100))
    reason = str(decision.get("reason") or "More budget may be needed to complete the current task.")

    if action == "wait":
        # _budget_extension_decision already created a Coordinator-budget
        # request. Do not also create an agent request: once the Coordinator
        # receives more decision budget, the next reconciliation can make the
        # agent extension decision automatically.
        return True

    if action == "grant":
        request = swarm.ensure_budget_request(
            swarm_id,
            scope="agent",
            task_id=task_id,
            run_id=run_id,
            requested_amount=amount,
            reason=reason,
        )
        try:
            swarm.decide_budget_request(int(request["id"]), accepted=True, amount=amount, decided_by="coordinator")
            swarm.publish(
                swarm_id,
                "decision",
                f"Coordinator granted agent #{task_id} +{amount} budget to continue from its saved checkpoint. {reason}",
                key=f"budget-auto-{request['id']}",
            )
        except Exception as exc:
            swarm.ensure_budget_request(
                swarm_id,
                scope="agent",
                task_id=task_id,
                run_id=run_id,
                requested_amount=amount,
                reason=f"Automatic extension could not resume the agent: {exc}",
            )
        return True

    swarm.ensure_budget_request(
        swarm_id,
        scope="agent",
        task_id=task_id,
        run_id=run_id,
        requested_amount=amount,
        reason=reason,
    )
    return True


def _budget_extension_decision(run: dict, agent: dict, completed: list[dict]) -> dict:
    swarm_id = int(run["id"])
    budget = swarm.consume_coordinator_budget(swarm_id, "agent_budget_extension")
    if not budget["allowed"]:
        swarm.ensure_budget_request(
            swarm_id,
            scope="coordinator",
            requested_amount=10,
            reason=f"Coordinator needs more decision budget to assess agent #{agent['id']}'s budget extension.",
        )
        return {"action": "wait", "amount": 10, "reason": "Coordinator decision budget is exhausted."}

    profile = swarm.get_profile(int(run["profile_id"]))
    _, model = swarm.coordinator_model(profile)
    project = _project(int(run["project_id"]))
    evidence = {
        "objective": run.get("objective") or "",
        "agent": {
            "id": agent.get("id"),
            "title": agent.get("title"),
            "role": agent.get("agent_role"),
            "progress": agent.get("progress"),
            "tool_usage": agent.get("tool_usage"),
            "tool_budget": agent.get("tool_budget"),
            "current_activity": agent.get("current_activity"),
            "error": agent.get("error"),
        },
        "completed": [
            {"id": item["id"], "title": item["title"], "role": item.get("agent_role"), "result": (item.get("result") or "")[-500:]}
            for item in completed[-8:]
        ],
    }
    prompt = (
        "Decide whether this Advanced orchestration specialist should receive a small additional tool budget. "
        "Return JSON only: {\"action\":\"grant|ask_user\",\"amount\":10|25,\"reason\":\"...\"}. "
        "Grant only when the task appears to be making concrete progress and a small extension is likely to finish it. "
        "Ask the user when evidence is ambiguous, the task may be looping, or a larger strategic decision is needed.\n\n"
        + json.dumps(evidence, default=str)[:16000]
    )
    try:
        with ollama.client(90) as http:
            response = http.post("/api/chat", json={
                "model": model or project.get("profile_chat_model") or project.get("model"),
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": "Return valid JSON only. Be conservative with budget extensions."},
                    {"role": "user", "content": prompt},
                ],
                "options": {"temperature": 0.1},
            })
            response.raise_for_status()
            data = json.loads((response.json().get("message") or {}).get("content") or "{}")
        return data if isinstance(data, dict) else {"action": "ask_user", "amount": 10, "reason": "Coordinator returned no valid budget decision."}
    except Exception as exc:
        return {"action": "ask_user", "amount": 10, "reason": f"Coordinator could not decide safely: {exc}"}


def _consider_help_request(run: dict, completed: list[dict]) -> bool:
    swarm_id = int(run["id"])
    questions = [
        item for item in swarm.blackboard(swarm_id, category="question")
        if item.get("task_id") is not None
    ]
    if not questions:
        return False

    with connect() as conn:
        answered_keys = {
            str(row["key"])
            for row in conn.execute(
                "SELECT key FROM swarm_blackboard WHERE swarm_id=? AND category='decision' AND key LIKE 'help-response-%'",
                (swarm_id,),
            )
        }
    request = next(
        (item for item in questions if f"help-response-{item['id']}" not in answered_keys),
        None,
    )
    if not request:
        return False

    response_key = f"help-response-{request['id']}"
    profile = swarm.get_profile(int(run["profile_id"]))
    if not profile.get("dynamic_size"):
        swarm.publish(
            swarm_id,
            "decision",
            "Coordinator declined the specialist help request because dynamic swarm sizing is disabled.",
            key=response_key,
        )
        return False
    if int(run["total_agents_created"] or 0) >= int(run["max_agents"] or 0):
        swarm.publish(
            swarm_id,
            "decision",
            "Coordinator declined the specialist help request because the swarm has reached its maximum agent count.",
            key=response_key,
        )
        return False

    agents = run.get("agents") or []
    requester = next((item for item in agents if int(item["id"]) == int(request["task_id"])), None)
    decision = _help_decision(run, profile, request, requester, completed)
    if str(decision.get("action") or "decline").lower() == "wait":
        return True
    if str(decision.get("action") or "decline").lower() != "spawn":
        swarm.publish(
            swarm_id,
            "decision",
            str(decision.get("reason") or "Coordinator declined the specialist help request."),
            key=response_key,
        )
        return False

    role = str(decision.get("role") or "worker").lower()
    if role not in {"worker", "frontend", "backend", "tester", "researcher", "coder", "documentation"}:
        role = "worker"
    title = str(decision.get("title") or "Requested helper specialist")[:256]
    prompt = str(decision.get("prompt") or "").strip()
    if not prompt:
        swarm.publish(
            swarm_id,
            "decision",
            "Coordinator declined the specialist help request because it did not produce a bounded helper task.",
            key=response_key,
        )
        return False

    model_profile_id, assigned_model = swarm.resolve_role(profile, role)
    session_id = _new_session(int(run["project_id"]), title)
    helper = task_queue.enqueue(
        int(run["project_id"]),
        session_id,
        title,
        _guided_prompt(run, prompt),
        source_kind="swarm_help",
        source_ref=f"swarm:{swarm_id}:help:{request['id']}:requester:{request['task_id']}",
        depends_on=[int(item["id"]) for item in completed],
        agent_role=role,
        swarm_id=swarm_id,
        model_profile_id=model_profile_id,
        assigned_model=assigned_model,
        task_kind=role,
        priority=125,
        depth=1,
    )
    swarm.publish(
        swarm_id,
        "decision",
        f"Coordinator accepted help request #{request['id']} and spawned agent #{helper['id']} ({role}).",
        key=response_key,
    )
    _append_verification_dependency(swarm_id, int(helper["id"]))
    return True


def _help_decision(run: dict, profile: dict, request: dict, requester: dict | None, completed: list[dict]) -> dict:
    budget = swarm.consume_coordinator_budget(int(run["id"]), "specialist_help")
    if not budget["allowed"]:
        swarm.ensure_budget_request(int(run["id"]), scope="coordinator", requested_amount=10, reason="Coordinator needs more budget to evaluate a specialist help request.")
        return {"action": "wait", "reason": "Coordinator budget is exhausted; waiting for a budget decision."}
    _, model = swarm.coordinator_model(profile)
    project = _project(int(run["project_id"]))
    evidence = {
        "objective": run["objective"],
        "request": {
            "id": request["id"],
            "task_id": request.get("task_id"),
            "content": request.get("content") or "",
            "key": request.get("key") or "",
        },
        "requesting_agent": {
            "id": requester.get("id"),
            "title": requester.get("title"),
            "role": requester.get("agent_role"),
            "status": requester.get("status"),
            "current_activity": requester.get("current_activity"),
        } if requester else None,
        "completed": [
            {"id": item["id"], "title": item["title"], "role": item["agent_role"], "result": (item.get("result") or "")[-600:]}
            for item in completed[-12:]
        ],
        "remaining_slots": int(run["max_agents"]) - int(run["total_agents_created"]),
        "user_guidance": run.get("coordinator_instructions") or "",
    }
    prompt = (
        "You are the persistent Coordinator for a local Olladex software-engineering swarm. "
        "A running specialist requested another specialist. Decide whether one additional bounded helper is materially useful. "
        "Return JSON only: {\"action\":\"spawn|decline\",\"role\":\"backend|frontend|tester|researcher|coder|documentation|worker\","
        "\"title\":\"...\",\"prompt\":\"...\",\"reason\":\"...\"}. "
        "Do not spawn a manager, reviewer, challenger or recursive coordinator. "
        "Prefer declining when the requesting agent can reasonably complete the work itself or the request duplicates existing work.\n\n"
        + json.dumps(evidence, default=str)[:20000]
    )
    try:
        with ollama.client(120) as http:
            response = http.post("/api/chat", json={
                "model": model or project.get("profile_chat_model") or project.get("model"),
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": "Return valid JSON only. You coordinate work but do not edit files."},
                    {"role": "user", "content": prompt},
                ],
                "options": {"temperature": 0.1},
            })
            response.raise_for_status()
            raw = (response.json().get("message") or {}).get("content") or "{}"
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"action": "decline", "reason": "Coordinator returned no valid help decision."}
    except Exception as exc:
        return {"action": "decline", "reason": f"Coordinator could not evaluate the help request: {exc}"}


def _append_verification_dependency(swarm_id: int, task_id: int) -> None:
    with connect() as conn:
        verification = [dict(row) for row in conn.execute(
            "SELECT id,task_kind,depends_on FROM background_tasks "
            "WHERE swarm_id=? AND task_kind IN ('challenger','reviewer') ORDER BY priority,id",
            (swarm_id,),
        )]
        challenger_ids = [int(row["id"]) for row in verification if row.get("task_kind") == "challenger"]
        for row in verification:
            if row.get("task_kind") == "reviewer" and challenger_ids:
                continue
            try:
                deps = [int(value) for value in json.loads(row.get("depends_on") or "[]")]
            except (json.JSONDecodeError, TypeError, ValueError):
                deps = []
            if task_id not in deps:
                deps.append(task_id)
                conn.execute(
                    "UPDATE background_tasks SET depends_on=? WHERE id=?",
                    (json.dumps(sorted(set(deps))), row["id"]),
                )


def _guided_prompt(run: dict, prompt: str) -> str:
    guidance = str(run.get("coordinator_instructions") or "").strip()
    if not guidance:
        return prompt
    return prompt + "\n\nPersistent swarm-wide user guidance:\n" + guidance


def _consider_pre_review(run: dict, profile: dict, completed: list[dict]) -> bool:
    swarm_id = int(run["id"])
    risks = swarm.blackboard(swarm_id, category="risk")
    if not risks:
        _publish_once(swarm_id, "decision", "pre-review-gate", "Coordinator found no unresolved Blackboard risks requiring another specialist and opened final verification.")
        return False
    with connect() as conn:
        already = conn.execute(
            "SELECT id FROM swarm_blackboard WHERE swarm_id=? AND key='pre-review-risk-evaluated'",
            (swarm_id,),
        ).fetchone()
    if already:
        return False
    if int(run["total_agents_created"] or 0) >= int(run["max_agents"] or 0):
        swarm.publish(
            swarm_id,
            "decision",
            "Coordinator found Blackboard risks but no spare agent capacity remains; final verification will assess them.",
            key="pre-review-risk-evaluated",
        )
        return False

    decision = _followup_decision(run, profile, completed, risks)
    if str(decision.get("action") or "proceed").lower() == "wait":
        return True
    if str(decision.get("action") or "proceed").lower() != "spawn":
        swarm.publish(
            swarm_id,
            "decision",
            str(decision.get("reason") or "Coordinator chose to proceed to final verification."),
            key="pre-review-risk-evaluated",
        )
        return False

    role = str(decision.get("role") or "tester").lower()
    if role not in {"worker", "frontend", "backend", "tester", "researcher", "coder", "documentation"}:
        role = "tester"
    title = str(decision.get("title") or "Coordinator follow-up")[:256]
    prompt = str(decision.get("prompt") or "").strip()
    if not prompt:
        swarm.publish(swarm_id, "decision", "Coordinator did not produce a usable follow-up task; proceeding to final verification.", key="pre-review-risk-evaluated")
        return False

    model_profile_id, assigned_model = swarm.resolve_role(profile, role)
    session_id = _new_session(int(run["project_id"]), title)
    task = task_queue.enqueue(
        int(run["project_id"]),
        session_id,
        title,
        _guided_prompt(run, prompt),
        source_kind="swarm_followup",
        source_ref=f"swarm:{swarm_id}:pre-review",
        depends_on=[int(item["id"]) for item in completed],
        agent_role=role,
        swarm_id=swarm_id,
        model_profile_id=model_profile_id,
        assigned_model=assigned_model,
        task_kind=role,
        priority=175,
        depth=1,
    )
    swarm.publish(
        swarm_id,
        "decision",
        f"Coordinator added follow-up agent #{task['id']} ({role}) before final verification.",
        key="pre-review-risk-evaluated",
    )
    _retarget_verification(swarm_id, task["id"])
    return True


def _followup_decision(run: dict, profile: dict, completed: list[dict], risks: list[dict]) -> dict:
    budget = swarm.consume_coordinator_budget(int(run["id"]), "pre_review_risk")
    if not budget["allowed"]:
        swarm.ensure_budget_request(int(run["id"]), scope="coordinator", requested_amount=10, reason="Coordinator needs more budget to evaluate pre-review risks.")
        return {"action": "wait", "reason": "Coordinator budget is exhausted; waiting for a budget decision."}
    _, model = swarm.coordinator_model(profile)
    project = _project(int(run["project_id"]))
    evidence = {
        "objective": run["objective"],
        "completed": [{"id":x["id"], "title":x["title"], "role":x["agent_role"], "result":x.get("result","")[-800:]} for x in completed],
        "risks": risks[-30:],
        "remaining_slots": int(run["max_agents"])-int(run["total_agents_created"]),
        "user_guidance": run.get("coordinator_instructions") or "",
    }
    prompt = (
        "You are the persistent Coordinator for a local Olladex software-engineering swarm. "
        "All current specialists completed, but the shared Blackboard contains risk entries. "
        "Decide whether one additional focused specialist is justified before challenger/reviewer verification. "
        "Return JSON only: {\"action\":\"spawn|proceed\",\"role\":\"backend|frontend|tester|researcher|coder|documentation|worker\","
        "\"title\":\"...\",\"prompt\":\"...\",\"reason\":\"...\"}. "
        "Spawn only for a concrete unresolved risk that can be checked or fixed by one bounded task. "
        "Do not create reviewers, managers, or recursive coordinators.\n\n"
        + json.dumps(evidence, default=str)[:24000]
    )
    try:
        with ollama.client(120) as http:
            response = http.post("/api/chat", json={
                "model": model or project.get("profile_chat_model") or project.get("model"),
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": "Return valid JSON only. You coordinate work but do not edit files."},
                    {"role": "user", "content": prompt},
                ],
                "options": {"temperature": 0.1},
            })
            response.raise_for_status()
            raw = (response.json().get("message") or {}).get("content") or "{}"
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"action": "proceed", "reason": "No valid follow-up decision."}
    except Exception as exc:
        return {"action": "proceed", "reason": f"Coordinator risk review could not run: {exc}. Final verification will assess the recorded risks."}


def _consider_recovery(run: dict, failed: list[dict], completed: list[dict]) -> None:
    swarm_id = int(run["id"])
    profile = swarm.get_profile(int(run["profile_id"]))
    if not profile.get("dynamic_size"):
        swarm.set_status(swarm_id, "failed")
        return
    if int(run["total_agents_created"] or 0) >= int(run["max_agents"] or 0):
        _publish_once(swarm_id, "risk", "agent-limit", "A specialist failed and the swarm has reached its configured maximum agent count.")
        swarm.set_status(swarm_id, "failed")
        return

    prior_recovery = _recovery_count(swarm_id)
    if prior_recovery >= 2:
        _publish_once(swarm_id, "risk", "recovery-limit", "The Coordinator stopped replanning after two recovery attempts.")
        swarm.set_status(swarm_id, "failed")
        return

    decision = _recovery_decision(run, profile, failed, completed)
    action = str(decision.get("action") or "fail").lower()
    if action == "defer":
        _publish_once(
            swarm_id,
            "risk",
            f"recovery-deferred-{prior_recovery}",
            str(decision.get("reason") or "Coordinator recovery planning is temporarily unavailable; the swarm will retry."),
        )
        return
    if action != "spawn":
        reason = str(decision.get("reason") or "Coordinator could not identify a safe recovery task.")
        _publish_once(swarm_id, "risk", f"recovery-stop-{prior_recovery}", reason)
        swarm.set_status(swarm_id, "failed")
        return

    role = str(decision.get("role") or "worker").lower()
    if role not in {"worker", "frontend", "backend", "tester", "researcher", "coder", "documentation"}:
        role = "worker"
    title = str(decision.get("title") or f"Recovery specialist {prior_recovery + 1}")[:256]
    prompt = str(decision.get("prompt") or "").strip()
    if not prompt:
        swarm.set_status(swarm_id, "failed")
        return

    model_profile_id, assigned_model = swarm.resolve_role(profile, role)
    session_id = _new_session(int(run["project_id"]), title)
    dependency_ids = [int(item["id"]) for item in completed]
    task = task_queue.enqueue(
        int(run["project_id"]),
        session_id,
        title,
        _guided_prompt(run, prompt),
        source_kind="swarm_recovery",
        source_ref=(
            f"swarm:{swarm_id}:recovery:{prior_recovery + 1}:failed:"
            + ",".join(str(int(item["id"])) for item in failed)
        ),
        depends_on=dependency_ids,
        agent_role=role,
        swarm_id=swarm_id,
        model_profile_id=model_profile_id,
        assigned_model=assigned_model,
        task_kind=role,
        priority=150,
        depth=1,
    )
    swarm.publish(
        swarm_id,
        "decision",
        f"Coordinator spawned recovery agent #{task['id']} ({role}) after specialist failure.",
        key=f"recovery-{prior_recovery + 1}",
    )
    _retarget_verification(swarm_id, task["id"])


def _retarget_verification(swarm_id: int, recovery_task_id: int) -> None:
    with connect() as conn:
        verification = [dict(row) for row in conn.execute(
            "SELECT id,task_kind,depends_on FROM background_tasks WHERE swarm_id=? AND task_kind IN ('challenger','reviewer') ORDER BY priority,id",
            (swarm_id,),
        )]
        challenger_ids = [int(row["id"]) for row in verification if row.get("task_kind") == "challenger"]
        for row in verification:
            if row.get("task_kind") == "reviewer" and challenger_ids:
                # Reviewer must remain downstream of the challenger. The challenger itself
                # inherits the recovery/follow-up task, so adding the recovery directly here
                # would allow reviewer and challenger to run in parallel.
                retained = challenger_ids
            else:
                try:
                    deps = [int(value) for value in json.loads(row.get("depends_on") or "[]")]
                except (json.JSONDecodeError, TypeError, ValueError):
                    deps = []
                statuses = {}
                if deps:
                    placeholders = ",".join("?" for _ in deps)
                    statuses = {
                        int(item["id"]): item["status"]
                        for item in conn.execute(
                            f"SELECT id,status FROM background_tasks WHERE id IN ({placeholders})",
                            deps,
                        )
                    }
                retained = [dep for dep in deps if statuses.get(dep) == "completed"]
                retained.append(recovery_task_id)
            conn.execute(
                "UPDATE background_tasks SET depends_on=?,status='queued',error='',completed_at='' WHERE id=?",
                (json.dumps(sorted(set(retained))), row["id"]),
            )


def _recovery_decision(run: dict, profile: dict, failed: list[dict], completed: list[dict]) -> dict:
    budget = swarm.consume_coordinator_budget(int(run["id"]), "failure_recovery")
    if not budget["allowed"]:
        swarm.ensure_budget_request(int(run["id"]), scope="coordinator", requested_amount=10, reason="Coordinator needs more budget to plan failure recovery.")
        return {"action": "defer", "reason": "Coordinator budget is exhausted; waiting for a budget decision."}
    _, model = swarm.coordinator_model(profile)
    project = _project(int(run["project_id"]))
    board = swarm.blackboard(int(run["id"]))
    evidence = {
        "objective": run["objective"],
        "failed": [{"id":x["id"], "title":x["title"], "role":x["agent_role"], "error":x.get("error",""), "result":x.get("result","")[-1200:]} for x in failed],
        "completed": [{"id":x["id"], "title":x["title"], "role":x["agent_role"], "result":x.get("result","")[-800:]} for x in completed],
        "blackboard": board[-40:],
        "remaining_slots": int(run["max_agents"])-int(run["total_agents_created"]),
        "user_guidance": run.get("coordinator_instructions") or "",
    }
    prompt = (
        "You are the persistent Coordinator for a local Olladex software-engineering swarm. "
        "A specialist failed and no normal specialist is still active. Decide whether one focused recovery specialist can safely unblock the objective. "
        "Return JSON only: {\"action\":\"spawn|fail\",\"role\":\"backend|frontend|tester|researcher|coder|documentation|worker\","
        "\"title\":\"...\",\"prompt\":\"...\",\"reason\":\"...\"}. "
        "Spawn only when the evidence supports a concrete bounded next task. Do not create managers, reviewers or recursive coordinators.\n\n"
        + json.dumps(evidence, default=str)[:24000]
    )
    try:
        with ollama.client(120) as http:
            response = http.post("/api/chat", json={
                "model": model or project.get("profile_chat_model") or project.get("model"),
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": "Return valid JSON only. You coordinate work but do not edit files."},
                    {"role": "user", "content": prompt},
                ],
                "options": {"temperature": 0.1},
            })
            response.raise_for_status()
            raw = (response.json().get("message") or {}).get("content") or "{}"
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"action": "fail", "reason": "Coordinator returned no decision."}
    except Exception as exc:
        return {"action": "defer", "reason": f"Coordinator recovery planning is temporarily unavailable: {exc}"}


def _project(project_id: int) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT p.*,mp.chat_model AS profile_chat_model FROM projects p "
            "LEFT JOIN model_profiles mp ON mp.id=p.model_profile_id WHERE p.id=?",
            (project_id,),
        ).fetchone()
    return dict(row) if row else {}


def _new_session(project_id: int, title: str) -> int:
    stamp = now()
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (project_id, title[:200], stamp, stamp),
        )
        return int(cursor.lastrowid)


def _recovered_failure_ids(completed: list[dict]) -> set[int]:
    recovered: set[int] = set()
    for item in completed:
        if item.get("source_kind") != "swarm_recovery":
            continue
        source_ref = str(item.get("source_ref") or "")
        marker = ":failed:"
        if marker not in source_ref:
            continue
        raw_ids = source_ref.split(marker, 1)[1]
        for value in raw_ids.split(","):
            try:
                recovered.add(int(value))
            except (TypeError, ValueError):
                continue
    return recovered


def _recovery_count(swarm_id: int) -> int:
    with connect() as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM background_tasks WHERE swarm_id=? AND source_kind='swarm_recovery'",
            (swarm_id,),
        ).fetchone()[0])


def _publish_once(swarm_id: int, category: str, key: str, content: str) -> None:
    with connect() as conn:
        if conn.execute("SELECT id FROM swarm_blackboard WHERE swarm_id=? AND key=?", (swarm_id, key)).fetchone():
            return
    swarm.publish(swarm_id, category, content, key=key)
