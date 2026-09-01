from __future__ import annotations

import json
from collections import Counter


def build(messages: list[dict]) -> str:
    if not messages:
        return ""
    user_tasks: list[str] = []
    outcomes: list[str] = []
    tools: Counter[str] = Counter()
    paths: list[str] = []
    for message in messages[-30:]:
        content = " ".join((message.get("content") or "").split())
        if message.get("role") == "user" and content:
            user_tasks.append(content[:260])
        elif message.get("role") == "assistant" and content:
            outcomes.append(content[:260])
        activities = message.get("activities") or []
        if isinstance(activities, str):
            try:
                activities = json.loads(activities)
            except json.JSONDecodeError:
                activities = []
        for activity in activities:
            tools[activity.get("tool", "unknown")] += 1
            result = activity.get("result") or {}
            if isinstance(result, dict) and result.get("path"):
                paths.append(str(result["path"]))
    sections = []
    if user_tasks:
        sections.append("Recent tasks:\n" + "\n".join(f"- {item}" for item in user_tasks[-6:]))
    if outcomes:
        sections.append("Recent outcomes:\n" + "\n".join(f"- {item}" for item in outcomes[-4:]))
    if tools:
        sections.append("Tool activity: " + ", ".join(f"{name} ×{count}" for name, count in tools.most_common()))
    if paths:
        sections.append("Files discussed or changed: " + ", ".join(dict.fromkeys(paths[-12:])))
    return "\n\n".join(sections)[:12_000]

