from __future__ import annotations

import json
import re
from typing import Any

import httpx

from ..config import settings
from . import task_queue, workspace, conversation_runtime as runtime
from .context_engine import format_context
from .repository_index import ranked_context
from .terminal import requires_approval, run as run_command


TOOLS = [
    {"type": "function", "function": {"name": "get_project_tree", "description": "List the repository tree", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a UTF-8 repository file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "search_code", "description": "Search filenames and text", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Write or propose a complete UTF-8 file change. In a background task, write directly to the isolated task worktree. In interactive chat, propose the change for user review. Use only when the user asks for changes.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "run_command", "description": "Run a bash command in the project", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
]
TOOLS[1]["function"]["parameters"]["properties"].update({"start_line": {"type": "integer", "minimum": 1}, "line_count": {"type": "integer", "minimum": 1, "maximum": 1000}})
for tool_name, description, properties in [
    ("apply_patch", "Replace one unique text block in a file. Read the file first. Background edits apply in the worktree; interactive edits are proposed for review.", {"path": {"type":"string"}, "old_text": {"type":"string"}, "new_text": {"type":"string"}}),
    ("ask_user", "Ask a necessary clarification and wait for the answer before continuing.", {"question": {"type":"string"}}),
    ("remember_preference", "Save an explicit user request to remember a preference or decision. Do not infer personal facts or save secrets.", {"preference": {"type":"string"}}),
    ("update_plan", "Show or revise a short plan for a multi-step task.", {"steps": {"type":"array", "items": {"type":"string"}}}),
]:
    TOOLS.append({"type":"function", "function": {"name":tool_name, "description":description,
        "parameters": {"type":"object", "properties":properties, "required":list(properties), "additionalProperties":False}}})



class BudgetExhausted(RuntimeError):
    pass


class AgentCancelled(RuntimeError):
    pass


def client(timeout: float | httpx.Timeout = 300) -> httpx.Client:
    return httpx.Client(base_url=settings.ollama_url.rstrip("/"), timeout=timeout)


def status() -> dict:
    try:
        with client(5) as http:
            response = http.get("/api/tags")
            response.raise_for_status()
            data = response.json()
        models = [m.get("name") or m.get("model") for m in data.get("models", [])]
        return {"connected": True, "url": settings.ollama_url, "models": models, "embedding_model": settings.ollama_embedding_model, "embedding_available": settings.ollama_embedding_model in models}
    except Exception as exc:
        return {"connected": False, "url": settings.ollama_url, "models": [], "embedding_model": settings.ollama_embedding_model, "embedding_available": False, "error": str(exc)}


def _check_cancelled() -> None:
    if task_queue.cancel_requested() or runtime.cancelled():
        raise AgentCancelled("Task cancelled")


def _interruptible_json(http, path, payload):
    import queue
    import threading
    result = queue.Queue(maxsize=1)
    def request():
        try:
            response = http.post(path, json=payload)
            response.raise_for_status()
            result.put(response.json())
        except Exception as exc:
            result.put(exc)
    threading.Thread(target=request, daemon=True).start()
    while True:
        _check_cancelled()
        try:
            value = result.get(timeout=.1)
        except queue.Empty:
            continue
        if isinstance(value, Exception):
            raise value
        return value


def embed_texts(texts: list[str], model: str | None = None) -> list[list[float]]:
    embedding_model = model or settings.ollama_embedding_model
    if not embedding_model:
        raise ValueError("No Ollama embedding model is configured")
    _check_cancelled()
    with client(httpx.Timeout(90, connect=3)) as http:
        vectors = _interruptible_json(http, "/api/embed", {"model": embedding_model, "input": texts, "truncate": True}).get("embeddings") or []
    _check_cancelled()
    if len(vectors) != len(texts):
        raise ValueError("Ollama returned an incomplete embedding response")
    return vectors


def _execute_tool(project: dict, name: str, args: dict) -> tuple[Any, dict]:
    _check_cancelled()
    if name == "get_project_tree":
        result = workspace.tree(project, max_items=350)
    elif name == "read_file":
        result = "\n".join(workspace.read_text(project, args.get("path", "")).splitlines()[args.get("start_line", 1)-1:args.get("start_line", 1)-1+args.get("line_count", 200)])
    elif name == "search_code":
        result = workspace.search(project, args.get("query", ""))
    elif name == "ask_user":
        result = runtime.ask(args["question"])
    elif name == "remember_preference":
        if not runtime.current_id():
            raise ValueError("Memory requires an active conversation")
        from ..database import connect
        session_id = runtime.get(runtime.current_id())["session_id"]
        with connect() as conn:
            existing = conn.execute("SELECT memory FROM sessions WHERE id=?", (session_id,)).fetchone()["memory"]
            value = (existing + "\n" + args["preference"]).strip()
            if len(value) > 8000:
                raise ValueError("Memory is full. Ask the user to edit the saved context.")
            conn.execute("UPDATE sessions SET memory=? WHERE id=?", (value, session_id))
        result = {"remembered": args["preference"]}
        runtime.emit("memory", result)
    elif name == "update_plan":
        result = {"steps": args["steps"]}
        runtime.emit("plan", result)
    elif name == "apply_patch":
        before = workspace.read_text(project, args["path"])
        old = args["old_text"]
        if not old or before.count(old) != 1:
            raise ValueError("Patch context must match exactly once. Read the file again and provide unique context.")
        return _execute_tool(project, "write_file", {"path": args["path"], "content": before.replace(old, args["new_text"], 1)})
    elif name == "write_file":
        path = args.get("path", "")
        after = args.get("content", "")
        task_id = task_queue.current_task_id()
        if task_id:
            if not task_queue.current_worktree_path():
                raise ValueError("Background task file writes require an isolated Git worktree; the main project was left unchanged")
            before, after, diff = workspace.write_text(project, path, after)
            result = {
                "path": path,
                "diff": diff,
                "before": before,
                "after": after,
                "status": "applied",
                "task_id": task_id,
                "workspace": "task_worktree",
            }
        else:
            try:
                before = workspace.read_text(project, path)
            except Exception as exc:
                if getattr(exc, "status_code", None) != 404:
                    raise
                before = ""
            import difflib
            diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=f"a/{path}", tofile=f"b/{path}"))
            result = {"path": path, "diff": diff, "before": before, "after": after, "status": "proposed"}
    elif name == "run_command":
        command = args.get("command", "")
        if task_queue.current_task_id() and not task_queue.current_worktree_path():
            raise ValueError("Background commands require an isolated Git worktree")
        if runtime.current_id():
            result = runtime.command(project, command)
            return result, {"tool": name, "arguments": args, "summary": summarize(name, result), "result": result}
        result = {"command": command, "output": "Awaiting approval", "exit_code": -1, "status": "pending"} if requires_approval(project, command) else {**run_command(project, command), "status": "completed"}
    else:
        result = {"error": f"Unknown tool: {name}"}
    activity_name = "task_write_file" if name == "write_file" and isinstance(result, dict) and result.get("status") == "applied" else name
    activity_result = result
    if activity_name == "task_write_file":
        activity_result = {key: result.get(key) for key in ("path", "status", "task_id", "workspace")}
    activity = {"tool": activity_name, "arguments": args, "summary": summarize(name, result), "result": activity_result}
    return result, activity


def execute_tool(project: dict, name: str, args: dict) -> tuple[Any, dict]:
    try:
        args = validate_arguments(name, args)
        return _execute_tool(project, name, args)
    except AgentCancelled:
        raise
    except Exception as exc:
        result = {"error": str(exc), "recoverable": True}
        return result, {"tool": name, "arguments": args, "summary": f"Tool failed: {exc}", "result": result}


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
        if result.get("status") == "applied":
            return f"Wrote {result.get('path')} in the isolated task workspace"
        return f"Proposed {result.get('path')} for review"
    if name == "run_command":
        return "Awaiting command approval" if result.get("status") == "pending" else f"Exited with code {result.get('exit_code')}"
    return "Complete"


def _stream_chat(http: httpx.Client, payload: dict) -> dict:
    import queue
    import threading
    # Keep Stop responsive even while Ollama is loading a model or emitting no bytes.
    received = queue.Queue(maxsize=128)
    stopped = threading.Event()
    response_holder = []
    def deliver(value):
        while not stopped.is_set():
            try:
                received.put(value, timeout=.1)
                return
            except queue.Full:
                continue
    def read():
        try:
            with http.stream("POST", "/api/chat", json={**payload, "stream": True}) as response:
                response_holder.append(response)
                response.raise_for_status()
                for line in response.iter_lines():
                    if stopped.is_set():
                        break
                    if line:
                        deliver(json.loads(line))
            deliver(None)
        except Exception as exc:
            deliver(exc)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    content_parts = []
    tool_calls = []
    pending = ""
    import time
    last_emit = time.monotonic()
    try:
        while True:
            _check_cancelled()
            try:
                chunk = received.get(timeout=.1)
            except queue.Empty:
                continue
            if chunk is None:
                break
            if isinstance(chunk, Exception):
                raise chunk
            if chunk.get("error"):
                raise ValueError(str(chunk["error"]))
            message = chunk.get("message") or {}
            text = message.get("content") or ""
            content_parts.append(text)
            pending += text
            if pending and (time.monotonic() - last_emit > .05 or chunk.get("done")):
                runtime.emit("text_delta", {"text": pending})
                pending = ""
                last_emit = time.monotonic()
            tool_calls.extend(message.get("tool_calls") or [])
            if chunk.get("done"):
                break
    finally:
        if pending:
            runtime.emit("text_delta", {"text": pending})
        stopped.set()
        for response in response_holder:
            response.close()
        reader.join(timeout=.2)
    _check_cancelled()
    return {"role": "assistant", "content": "".join(content_parts), "tool_calls": tool_calls}


def chat(project: dict, history: list[dict], model: str | None = None, max_steps: int | None = None, session_summary: str = "") -> tuple[str, list[dict]]:
    request = next((message.get("content", "") for message in reversed(history) if message.get("role") == "user"), "")
    runtime.emit("progress", {"message": "Preparing repository context"})
    intelligence = workspace.repository_intelligence(project)
    intelligence["symbols"] = intelligence.get("symbols", [])[:40]
    embedding_model = project.get("profile_embedding_model") or settings.ollama_embedding_model
    selected_context = ranked_context(project, request, embedder=lambda texts: embed_texts(texts, embedding_model), embedding_model=embedding_model, max_files=project.get("profile_context_files") or 8, max_chars=project.get("profile_context_chars") or 32000)
    task_context = ""
    if task_queue.current_task_id():
        task_context = (
            "\n\nBackground task mode: you are working inside an isolated Git worktree. "
            "When changes are requested, use write_file to apply them directly in this task worktree. "
            "You may edit multiple files and run appropriate checks. Do not merely describe edits that should be made."
        )
    system = (
        "You are Olladex, a thoughtful conversational coding collaborator. "
        "For greetings, discussion and questions, respond naturally; do not interpret every message as an instruction to edit. "
        "When action is requested, state your intended approach briefly, then use tools. "
        "Between meaningful groups of actions, explain what you learned and what comes next. "
        "Use concise user-facing explanations, not hidden reasoning or a running monologue. "
        "Ask a focused question with ask_user when an answer materially affects the outcome; otherwise use reasonable judgment. "
        "Incorporate steering messages while preserving the original objective. Never claim success if checks failed or approval is pending. "
        "Finish with the outcome, relevant verification and remaining limitations. Work only inside the selected repository. "
        "Use tools to inspect evidence before answering. Keep the user informed in concise language. "
        "Do not invent file contents or command results. When asked to change code, make focused edits, run appropriate checks, and summarize changes.\n\n"
        + "\n\nOriginal conversation objective:\n" + next((m["content"] for m in history if m.get("role") == "user"), request)[:4000]
        + "\n\n" + workspace.project_summary(project)
        + ("\n\nProject instructions:\n" + project.get("instructions", "") if project.get("instructions", "").strip() else "")
        + "\n\nRepository intelligence:\n" + json.dumps(intelligence, default=str)[:20_000]
        + ("\n\nPersistent session summary:\n" + session_summary if session_summary else "")
        + "\n\nAutomatically ranked repository context:\n" + format_context(selected_context)
        + task_context
    )
    context_tokens = project.get("profile_context_tokens") or settings.context_tokens
    resumed = runtime.resume_messages()
    messages: list[dict] = resumed or [{"role": "system", "content": system}, *history]
    if resumed:
        messages.append({"role": "user", "content": request})
    activities: list[dict] = []
    tool_attempts: dict[str, int] = {}
    with client() as http:
        for _ in range(max_steps or project.get("profile_max_steps") or 8):
            _check_cancelled()
            messages.extend(runtime.consume_inputs())
            messages = fit_context(messages, context_tokens)
            runtime.checkpoint(messages)
            runtime.emit("assistant_start", {})
            message = _stream_chat(http, {
                "model": model or project.get("profile_chat_model") or project.get("model") or settings.ollama_model,
                "messages": messages,
                "tools": TOOLS,
                "options": {"num_ctx": context_tokens, "temperature": project.get("profile_temperature") if project.get("profile_temperature") is not None else 0.2},
            })
            messages.append(message)
            runtime.checkpoint(messages)
            runtime.emit("assistant_end", {"content": message.get("content", "")})
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                steering = runtime.consume_inputs()
                if steering:
                    messages.extend(steering)
                    continue
                return message.get("content", ""), activities
            for call in tool_calls:
                _check_cancelled()
                function = call.get("function", {})
                name = function.get("name", "")
                args = function.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                runtime.emit("tool_started", {"tool": name, "arguments": args})
                fingerprint = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
                tool_attempts[fingerprint] = tool_attempts.get(fingerprint, 0) + 1
                if tool_attempts[fingerprint] > 2:
                    result = {"error": "Repeated identical tool call blocked. Inspect the previous result and choose a different action.", "recoverable": True}
                    activity = {"tool": name, "arguments": args, "summary": "Repeated tool call blocked", "result": result}
                else:
                    result, activity = execute_tool(project, name, args)
                session_id = getattr(runtime._local, "session_id", None)
                if session_id is not None and runtime.current_id():
                    from ..main import persist_activity
                    persist_activity(project, session_id, activity)
                    activity["_persisted"] = True
                    if activity.get("tool") == "write_file" and result.get("status") == "proposed":
                        result = runtime.wait_for_change(project, result)
                        activity["result"] = result
                        activity["summary"] = f"{result['path']} {result['status']} after review"
                runtime.emit("tool_result", activity)
                activities.append(activity)
                messages.append({"role": "tool", "tool_name": name, "content": json.dumps(bounded_result(result), default=str)})
                runtime.checkpoint(messages)
    runtime.state("budget_exhausted")
    return "I reached the tool-step limit. The work is saved; review it and continue when ready.", activities


# Strict server-side validation: model-provided schemas are hints, not enforcement.
def validate_arguments(name, args):
    from pydantic import BaseModel, ConfigDict, Field
    class Strict(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
    class Read(Strict):
        path: str = Field(min_length=1)
        start_line: int = Field(default=1, ge=1)
        line_count: int = Field(default=200, ge=1, le=1000)
    class Write(Strict):
        path: str = Field(min_length=1)
        content: str = Field(max_length=2_000_000)
    class Patch(Strict):
        path: str = Field(min_length=1)
        old_text: str = Field(min_length=1, max_length=100_000)
        new_text: str = Field(max_length=100_000)
    class Command(Strict):
        command: str = Field(min_length=1, max_length=4000)
    class Search(Strict):
        query: str = Field(min_length=1, max_length=1000)
    class Question(Strict):
        question: str = Field(min_length=1, max_length=4000)
    class Preference(Strict):
        preference: str = Field(min_length=1, max_length=1000)
    class Plan(Strict):
        steps: list[str] = Field(min_length=1, max_length=20)
    schema = {"get_project_tree": Strict, "read_file": Read, "write_file": Write,
              "apply_patch": Patch, "run_command": Command, "search_code": Search,
              "ask_user": Question, "update_plan": Plan, "remember_preference": Preference}.get(name)
    if schema is None:
        raise ValueError(f"Unknown tool: {name}")
    return schema.model_validate(args).model_dump()


def bounded_result(result, limit=12000):
    encoded = json.dumps(result, default=str)
    if len(encoded) <= limit:
        return result
    return {"truncated": True, "excerpt": encoded[:limit], "instruction": "Use line-range reads or narrower searches for more detail."}


def fit_context(messages, context_tokens):
    # Conservative estimate (2 characters/token), with output/tool-schema reserve.
    budget = max(4000, (context_tokens - 4096) * 2)
    output = json.loads(json.dumps(messages))
    for message in output:
        for call in message.get("tool_calls") or []:
            arguments = call.get("function", {}).get("arguments", {})
            if isinstance(arguments, dict):
                for key, value in arguments.items():
                    if isinstance(value, str) and len(value) > 2000:
                        arguments[key] = value[:2000] + "\n[Earlier tool input compacted; read the file for current contents.]"
    while len(json.dumps(output)) > budget and len(output) > 3:
        # Evict complete assistant/tool groups, never orphan a tool response.
        end = 2
        while end < len(output) and output[end].get("role") == "tool":
            end += 1
        if end == len(output):
            break
        del output[1:end]
    if len(json.dumps(output)) > budget:
        output = [{**m, "content": str(m.get("content", ""))[:max(1000, budget // max(1, len(output)))]} for m in output]
    return output
