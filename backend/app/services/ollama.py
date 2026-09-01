from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ..config import settings
from . import workspace
from .terminal import requires_approval, run as run_command


TOOLS = [
    {"type": "function", "function": {"name": "get_project_tree", "description": "List the repository tree", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a UTF-8 repository file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "search_code", "description": "Search filenames and text", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Propose a complete UTF-8 file change for user review. Use only when the user asks for changes.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "run_command", "description": "Run a bash command in the project", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
]


def client() -> httpx.Client:
    return httpx.Client(base_url=settings.ollama_url.rstrip("/"), timeout=300)


def status() -> dict:
    try:
        with client() as http:
            response = http.get("/api/tags")
            response.raise_for_status()
            data = response.json()
        return {"connected": True, "url": settings.ollama_url, "models": [m.get("name") or m.get("model") for m in data.get("models", [])]}
    except Exception as exc:
        return {"connected": False, "url": settings.ollama_url, "models": [], "error": str(exc)}


def execute_tool(project: dict, name: str, args: dict) -> tuple[Any, dict]:
    if name == "get_project_tree":
        result = workspace.tree(project, max_items=350)
    elif name == "read_file":
        result = workspace.read_text(project, args.get("path", ""))
    elif name == "search_code":
        result = workspace.search(project, args.get("query", ""))
    elif name == "write_file":
        path = args.get("path", "")
        try:
            before = workspace.read_text(project, path)
        except Exception:
            before = ""
        after = args.get("content", "")
        import difflib
        diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=f"a/{path}", tofile=f"b/{path}"))
        result = {"path": path, "diff": diff, "before": before, "after": after, "status": "proposed"}
    elif name == "run_command":
        command = args.get("command", "")
        result = {"command": command, "output": "Awaiting approval", "exit_code": -1, "status": "pending"} if requires_approval(project, command) else {**run_command(project, command), "status": "completed"}
    else:
        result = {"error": f"Unknown tool: {name}"}
    activity = {"tool": name, "arguments": args, "summary": summarize(name, result), "result": result}
    return result, activity


def summarize(name: str, result: Any) -> str:
    if isinstance(result, dict) and result.get("error"):
        return str(result["error"])
    if name == "read_file":
        return f"Read {len(str(result).splitlines())} lines"
    if name == "search_code":
        return f"Found {len(result)} matches"
    if name == "get_project_tree":
        return "Mapped repository"
    if name == "write_file":
        return f"Proposed {result.get('path')} for review"
    if name == "run_command":
        return "Awaiting command approval" if result.get("status") == "pending" else f"Exited with code {result.get('exit_code')}"
    return "Complete"


def chat(project: dict, history: list[dict], model: str | None = None, max_steps: int = 8) -> tuple[str, list[dict]]:
    system = (
        "You are Olladex, a careful local software-development agent. Work only inside the selected repository. "
        "Use tools to inspect evidence before answering. Keep the user informed in concise language. "
        "Do not invent file contents or command results. When asked to change code, make focused edits, run appropriate checks, and summarize changes.\n\n"
        + workspace.project_summary(project)
        + ("\n\nProject instructions:\n" + project.get("instructions", "") if project.get("instructions", "").strip() else "")
        + "\n\nRepository intelligence:\n" + json.dumps(workspace.repository_intelligence(project), default=str)[:20_000]
    )
    messages: list[dict] = [{"role": "system", "content": system}, *history[-30:]]
    activities: list[dict] = []
    with client() as http:
        for _ in range(max_steps):
            response = http.post("/api/chat", json={"model": model or project.get("model") or settings.ollama_model, "messages": messages, "tools": TOOLS, "stream": False, "options": {"temperature": 0.2}})
            response.raise_for_status()
            message = response.json().get("message", {})
            messages.append(message)
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return message.get("content", ""), activities
            for call in tool_calls:
                function = call.get("function", {})
                name = function.get("name", "")
                args = function.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                result, activity = execute_tool(project, name, args)
                activities.append(activity)
                messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, default=str)[:180_000]})
    return "I reached the tool-step limit. Review the activity and ask me to continue.", activities
