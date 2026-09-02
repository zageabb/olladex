from __future__ import annotations

import json

from ..config import settings
from . import ollama, workspace


ALLOWED_ROLES = {"worker", "frontend", "backend", "tester", "reviewer", "researcher"}


def decompose(project: dict, objective: str, max_tasks: int = 6) -> list[dict]:
    if not objective.strip():
        raise ValueError("Lead objective is required")
    max_tasks = max(2, min(int(max_tasks or 6), 10))
    intelligence = workspace.repository_intelligence(project)
    prompt = f"""You are the lead software-engineering coordinator for Olladex.
Break the objective into 2-{max_tasks} focused specialist tasks that can execute in parallel where safe.
Return JSON only with this exact shape:
{{"tasks":[{{"title":"...","role":"backend|frontend|tester|reviewer|researcher|worker","prompt":"...","depends_on":[0,1]}}]}}
Rules:
- depends_on contains zero-based indexes of earlier tasks only.
- keep tasks narrowly scoped and implementation-ready.
- create explicit test/review work when useful.
- do not create a final consolidation task; Olladex adds that automatically.

Objective:\n{objective.strip()}\n\nRepository intelligence:\n{json.dumps(intelligence, default=str)[:16000]}"""
    model = project.get("profile_chat_model") or project.get("model") or settings.ollama_model
    with ollama.client(120) as http:
        response = http.post("/api/chat", json={
            "model": model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": "Return valid JSON only. You are planning work, not executing it."},
                {"role": "user", "content": prompt},
            ],
            "options": {"temperature": 0.1},
        })
        response.raise_for_status()
        raw = (response.json().get("message") or {}).get("content") or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Lead planner returned invalid JSON") from exc
    items = data.get("tasks") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("Lead planner did not return any specialist tasks")

    result: list[dict] = []
    source_to_result: dict[int, int] = {}
    for source_index, item in enumerate(items[:max_tasks]):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or f"Specialist task {source_index + 1}").strip()[:256]
        role = str(item.get("role") or "worker").strip().lower()
        if role not in ALLOWED_ROLES:
            role = "worker"
        task_prompt = str(item.get("prompt") or "").strip()
        if not task_prompt:
            continue
        dependencies: list[int] = []
        for dependency in item.get("depends_on") or []:
            try:
                dependency_source_index = int(dependency)
            except (TypeError, ValueError):
                continue
            mapped = source_to_result.get(dependency_source_index)
            if mapped is not None:
                dependencies.append(mapped)
        result_index = len(result)
        source_to_result[source_index] = result_index
        result.append({"title": title, "role": role, "prompt": task_prompt, "depends_on": sorted(set(dependencies))})
    if len(result) < 2:
        raise ValueError("Lead planner must produce at least two actionable specialist tasks")
    return result
