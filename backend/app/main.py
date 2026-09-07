from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
import secrets
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import settings
from .database import connect, decode_json, init_db, now, rows
from .schemas import BackgroundTaskRequest, ChangeApplyRequest, ChatRequest, CommandRequest, FileWriteRequest, GitBranchRequest, GitCheckoutRequest, GitCommitRequest, GitHubPullRequestRequest, GitPathsRequest, GitRemoteOperationRequest, ModelProfileRequest, OfficeCreateRequest, ProjectCreate, ProjectSettingsRequest, SessionCreate, TerminalInputRequest, TerminalResizeRequest
from .services import changes as change_service
from .services import git, office, ollama, repository_index, task_queue, terminal, terminal_jobs, windows_pty, workspace
from .services import github as github_service
from .services.session_summary import build as build_session_summary


from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    startup()
    try:
        yield
    finally:
        shutdown()

app = FastAPI(title="Olladex API", version=__version__, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def authenticate(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        allowed = [value.strip() for value in settings.cors_origins.split(",")]
        if origin and origin not in allowed:
            return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
        if request.method != "OPTIONS" and settings.api_token and not secrets.compare_digest(
            request.headers.get("authorization", ""), "Bearer " + settings.api_token
        ):
            return JSONResponse({"detail": "Connect using your Olladex API token"}, status_code=401)
    return await call_next(request)


def startup() -> None:
    init_db()
    from .services import conversation_runtime
    conversation_runtime.init()
    task_queue.start(process_background_task)


def shutdown() -> None:
    from .services import conversation_runtime
    conversation_runtime.shutdown()
    terminal_jobs.shutdown()
    task_queue.stop()


def get_project(project_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT p.*,mp.name AS profile_name,mp.chat_model AS profile_chat_model,mp.embedding_model AS profile_embedding_model,mp.temperature AS profile_temperature,mp.max_steps AS profile_max_steps,mp.context_files AS profile_context_files,mp.context_chars AS profile_context_chars,mp.context_tokens AS profile_context_tokens FROM projects p LEFT JOIN model_profiles mp ON mp.id=p.model_profile_id WHERE p.id=?", (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found")
    return dict(row)


def get_change(change_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM file_changes WHERE id=?", (change_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Change not found")
    return dict(row)


def get_command(run_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM command_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Command run not found")
    return dict(row)


def get_git_operation(operation_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM git_operations WHERE id=?", (operation_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Git operation not found")
    return dict(row)


def get_github_operation(operation_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM github_operations WHERE id=?", (operation_id,)).fetchone()
    if not row:
        raise HTTPException(404, "GitHub operation not found")
    return dict(row)


@app.get("/health")
def health():
    return {"status": "ok", "name": "Olladex", "version": __version__}


@app.get("/api/status")
def api_status():
    return {"version": __version__, "ollama": ollama.status(), "shell": terminal.shell_command("")[0], "terminal_backend": windows_pty.backend_name()}


@app.get("/api/projects")
def list_projects():
    with connect() as conn:
        return rows(conn.execute("SELECT p.*,mp.name AS profile_name,mp.chat_model AS profile_chat_model,mp.embedding_model AS profile_embedding_model,mp.temperature AS profile_temperature,mp.max_steps AS profile_max_steps,mp.context_files AS profile_context_files,mp.context_chars AS profile_context_chars,mp.context_tokens AS profile_context_tokens FROM projects p LEFT JOIN model_profiles mp ON mp.id=p.model_profile_id ORDER BY p.last_opened_at DESC"))


@app.post("/api/projects")
def create_project(body: ProjectCreate):
    path = Path(body.path).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(400, "Choose an existing local directory")
    stamp = now()
    with connect() as conn:
        existing = conn.execute("SELECT * FROM projects WHERE path=?", (str(path),)).fetchone()
        if existing:
            conn.execute("UPDATE projects SET last_opened_at=? WHERE id=?", (stamp, existing["id"]))
            project_id = existing["id"]
        else:
            default_profile = conn.execute("SELECT id FROM model_profiles WHERE name='Balanced local'").fetchone()
            cursor = conn.execute("INSERT INTO projects(name,path,model,model_profile_id,created_at,last_opened_at) VALUES(?,?,?,?,?,?)", (body.name or path.name, str(path), body.model or settings.ollama_model, default_profile["id"] if default_profile else None, stamp, stamp))
            project_id = cursor.lastrowid
            conn.execute("INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)", (project_id, "Welcome to Olladex", stamp, stamp))
    return get_project(project_id)


@app.get("/api/projects/{project_id}/settings")
def project_settings(project_id: int):
    return get_project(project_id)


@app.patch("/api/projects/{project_id}/settings")
def update_project_settings(project_id: int, body: ProjectSettingsRequest):
    get_project(project_id)
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return get_project(project_id)
    assignments = ",".join(f"{name}=?" for name in updates)
    with connect() as conn:
        if updates.get("model_profile_id") is not None and not conn.execute("SELECT id FROM model_profiles WHERE id=?", (updates["model_profile_id"],)).fetchone():
            raise HTTPException(400, "Model profile not found")
        conn.execute(f"UPDATE projects SET {assignments} WHERE id=?", (*updates.values(), project_id))
    return get_project(project_id)


@app.get("/api/model-profiles")
def model_profiles():
    with connect() as conn:
        return rows(conn.execute("SELECT * FROM model_profiles ORDER BY name"))


@app.post("/api/model-profiles")
def create_model_profile(body: ModelProfileRequest):
    stamp = now()
    try:
        with connect() as conn:
            cursor = conn.execute("INSERT INTO model_profiles(name,chat_model,embedding_model,temperature,max_steps,context_files,context_chars,context_tokens,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (body.name, body.chat_model, body.embedding_model, body.temperature, body.max_steps, body.context_files, body.context_chars, body.context_tokens, stamp, stamp))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "A model profile with that name already exists") from exc
    with connect() as conn:
        return dict(conn.execute("SELECT * FROM model_profiles WHERE id=?", (cursor.lastrowid,)).fetchone())


@app.put("/api/model-profiles/{profile_id}")
def update_model_profile(profile_id: int, body: ModelProfileRequest):
    try:
        with connect() as conn:
            current = conn.execute("SELECT id,name,is_builtin FROM model_profiles WHERE id=?", (profile_id,)).fetchone()
            if not current:
                raise HTTPException(404, "Model profile not found")
            if current["is_builtin"] and body.name != current["name"]:
                raise HTTPException(409, "Built-in model profile names cannot be changed")
            conn.execute(
                "UPDATE model_profiles SET name=?,chat_model=?,embedding_model=?,temperature=?,max_steps=?,context_files=?,context_chars=?,context_tokens=?,updated_at=? WHERE id=?",
                (body.name, body.chat_model, body.embedding_model, body.temperature, body.max_steps, body.context_files, body.context_chars, body.context_tokens, now(), profile_id),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "A model profile with that name already exists") from exc
    with connect() as conn:
        return dict(conn.execute("SELECT * FROM model_profiles WHERE id=?", (profile_id,)).fetchone())


@app.delete("/api/model-profiles/{profile_id}")
def delete_model_profile(profile_id: int):
    with connect() as conn:
        profile = conn.execute("SELECT * FROM model_profiles WHERE id=?", (profile_id,)).fetchone()
        if not profile:
            raise HTTPException(404, "Model profile not found")
        if profile["is_builtin"]:
            raise HTTPException(409, "Built-in model profiles cannot be deleted")
        conn.execute("DELETE FROM model_profiles WHERE id=?", (profile_id,))
    return {"id": profile_id, "status": "deleted"}


@app.get("/api/projects/{project_id}/intelligence")
def project_intelligence(project_id: int):
    return workspace.repository_intelligence(get_project(project_id))


@app.get("/api/projects/{project_id}/index")
def repository_index_status(project_id: int):
    return repository_index.status(get_project(project_id))


@app.post("/api/projects/{project_id}/index")
def refresh_repository_index(project_id: int):
    project = get_project(project_id)
    embedding_model = project.get("profile_embedding_model") or settings.ollama_embedding_model
    return repository_index.refresh(project, embedder=lambda texts: ollama.embed_texts(texts, embedding_model), embedding_model=embedding_model)


@app.get("/api/projects/{project_id}/context-preview")
def context_preview(project_id: int, q: str):
    project = get_project(project_id)
    embedding_model = project.get("profile_embedding_model") or settings.ollama_embedding_model
    return repository_index.ranked_context(project, q, embedder=lambda texts: ollama.embed_texts(texts, embedding_model), embedding_model=embedding_model, max_files=project.get("profile_context_files") or 8, max_chars=project.get("profile_context_chars") or 32000)


@app.get("/api/projects/{project_id}/tree")
def get_tree(project_id: int):
    return workspace.tree(get_project(project_id))


@app.get("/api/projects/{project_id}/files")
def read_file(project_id: int, path: str = Query(...)):
    return {"path": path, "content": workspace.read_text(get_project(project_id), path)}


@app.put("/api/projects/{project_id}/files")
def write_file(project_id: int, path: str, body: FileWriteRequest):
    project = get_project(project_id)
    if body.expected_content is not None:
        target = workspace.safe_path(project, path)
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != body.expected_content:
            raise HTTPException(409, "The file changed on disk. Reload before saving.")
    before, after, diff = workspace.write_text(project, path, body.content)
    hunks = change_service.build_hunks(before, after)
    stamp = now()
    with connect() as conn:
        cursor = conn.execute("INSERT INTO file_changes(project_id,session_id,path,before_content,after_content,diff,hunks,applied_content,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (project_id, body.session_id, path, before, after, diff, json.dumps(hunks), after, "applied", stamp, stamp))
    return {"id": cursor.lastrowid, "path": path, "diff": diff}


@app.get("/api/projects/{project_id}/search")
def search_files(project_id: int, q: str):
    return workspace.search(get_project(project_id), q)


@app.get("/api/projects/{project_id}/sessions")
def list_sessions(project_id: int):
    get_project(project_id)
    with connect() as conn:
        return rows(conn.execute("SELECT * FROM sessions WHERE project_id=? ORDER BY updated_at DESC", (project_id,)))


@app.post("/api/projects/{project_id}/sessions")
def create_session(project_id: int, body: SessionCreate):
    get_project(project_id)
    stamp = now()
    with connect() as conn:
        cursor = conn.execute("INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)", (project_id, body.title, stamp, stamp))
    return {"id": cursor.lastrowid, "project_id": project_id, "title": body.title, "summary": "", "last_summarized_message_id": 0, "created_at": stamp, "updated_at": stamp}


@app.get("/api/projects/{project_id}/tasks")
def background_tasks(project_id: int):
    get_project(project_id)
    return task_queue.list_for_project(project_id)


@app.post("/api/projects/{project_id}/tasks")
def create_background_task(project_id: int, body: BackgroundTaskRequest):
    get_project(project_id)
    stamp = now()
    title = body.title or body.prompt.strip().splitlines()[0][:100]
    with connect() as conn:
        if body.session_id:
            session = conn.execute("SELECT id FROM sessions WHERE id=? AND project_id=?", (body.session_id, project_id)).fetchone()
            if not session:
                raise HTTPException(404, "Session not found in this project")
            session_id = body.session_id
        else:
            cursor = conn.execute("INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)", (project_id, title, stamp, stamp))
            session_id = cursor.lastrowid
    return task_queue.enqueue(project_id, session_id, title, body.prompt, body.source_kind, body.source_ref)


@app.get("/api/tasks/{task_id}")
def background_task(task_id: int):
    task = task_queue.get(task_id)
    if not task:
        raise HTTPException(404, "Background task not found")
    return task


@app.delete("/api/tasks/{task_id}")
def cancel_background_task(task_id: int):
    task = task_queue.cancel(task_id)
    if not task:
        raise HTTPException(404, "Background task not found")
    return task


@app.get("/api/sessions/{session_id}/messages")
def list_messages(session_id: int):
    with connect() as conn:
        result = rows(conn.execute("SELECT * FROM messages WHERE session_id=? ORDER BY id", (session_id,)))
    for item in result:
        item["activities"] = decode_json(item.get("activities"))
    return result


def persist_activity(project, session_id, activity):
    stamp = now()
    with connect() as conn:
        if activity.get("tool") == "write_file" and isinstance(activity.get("result"), dict) and activity["result"].get("status") == "proposed":
            result = activity["result"]
            hunks = change_service.build_hunks(result.get("before", ""), result.get("after", ""))
            change_cursor = conn.execute(
                "INSERT INTO file_changes(project_id,session_id,path,before_content,after_content,diff,hunks,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (project["id"], session_id, result.get("path", ""), result.get("before", ""), result.get("after", ""), result.get("diff", ""), json.dumps(hunks), "proposed", stamp, stamp),
            )
            conn.execute("UPDATE file_changes SET workspace_path=? WHERE id=?", (str(workspace.project_root(project)), change_cursor.lastrowid))
            result["change_id"] = change_cursor.lastrowid
            result["hunks"] = hunks
            result.pop("before", None)
            result.pop("after", None)
        if activity.get("tool") == "run_command" and isinstance(activity.get("result"), dict) and not activity["result"].get("command_run_id"):
            result = activity["result"]
            command_cursor = conn.execute(
                "INSERT INTO command_runs(project_id,command,output,exit_code,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (project["id"], result.get("command", ""), result.get("output", ""), result.get("exit_code", -1), result.get("status", "completed"), stamp, stamp),
            )
            result["command_run_id"] = command_cursor.lastrowid


def run_session_agent(session_id: int, content: str) -> dict:
    from .services import conversation_runtime
    conversation_runtime.emit("user_message", {"content": content})
    with connect() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            raise ValueError("Session not found")
        history = rows(conn.execute("SELECT role,content FROM messages WHERE session_id=? ORDER BY id", (session_id,)))
        if not history and session["title"] in {"New chat", "New task"}:
            title = " ".join(content.split())[:72]
            conn.execute("UPDATE sessions SET title=? WHERE id=?", (title, session_id))
        conn.execute("INSERT INTO messages(session_id,role,content,created_at,run_id) VALUES(?,?,?,?,?)", (session_id, "user", content, now(), conversation_runtime.current_id()))
    project = get_project(session["project_id"])
    from .services import conversation_runtime
    conversation_runtime._local.session_id = session_id
    answer, activities = ollama.chat(project, [*history, {"role": "user", "content": content}], session_summary=(session["summary"] or "") + "\n\nUser-managed preferences and decisions:\n" + (session["memory"] or ""))
    for activity in activities:
        if not activity.pop("_persisted", False):
            persist_activity(project, session_id, activity)
    stamp = now()
    with connect() as conn:
        cursor = conn.execute("INSERT INTO messages(session_id,role,content,activities,created_at,run_id) VALUES(?,?,?,?,?,?)", (session_id, "assistant", answer, json.dumps(activities, default=str), stamp, conversation_runtime.current_id()))
        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (stamp, session_id))
        last_message_id = cursor.lastrowid
        summary_messages = rows(conn.execute("SELECT role,content,activities FROM messages WHERE session_id=? ORDER BY id", (session_id,)))
        summary = build_session_summary(summary_messages)
        conn.execute("UPDATE sessions SET summary=?,last_summarized_message_id=? WHERE id=?", (summary, last_message_id, session_id))
    return {"id": cursor.lastrowid, "role": "assistant", "content": answer, "activities": activities, "created_at": stamp}


def process_background_task(task: dict) -> str:
    from .services import conversation_runtime as runtime
    run_id = runtime.create(task["session_id"], task["id"])
    with runtime.bind(run_id):
        try:
            result = run_session_agent(task["session_id"], task["prompt"])
            runtime.emit("final", result)
            if runtime.get(run_id)["status"] == "running":
                runtime.state("completed")
            elif runtime.get(run_id)["status"] == "budget_exhausted":
                raise ollama.BudgetExhausted(result["content"])
            return result["content"]
        except Exception as exc:
            runtime.state("cancelled" if isinstance(exc, ollama.AgentCancelled) else "budget_exhausted" if isinstance(exc, ollama.BudgetExhausted) else "failed")
            raise


@app.post("/api/sessions/{session_id}/messages")
def chat_message(session_id: int, body: ChatRequest):
    try:
        from .services import conversation_runtime as runtime
        run_id = runtime.create(session_id)
        with runtime.bind(run_id):
            try:
                result = run_session_agent(session_id, body.content)
                if runtime.get(run_id)["status"] == "running":
                    runtime.state("completed")
                return result
            except Exception:
                runtime.state("failed")
                raise
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Ollama request failed: {exc}") from exc


@app.get("/api/projects/{project_id}/changes")
def changes(project_id: int):
    get_project(project_id)
    with connect() as conn:
        result = rows(conn.execute("SELECT id,path,diff,hunks,status,created_at,updated_at FROM file_changes WHERE project_id=? ORDER BY id DESC LIMIT 100", (project_id,)))
    for item in result:
        item["hunks"] = decode_json(item.get("hunks"))
    return result


@app.post("/api/projects/{project_id}/changes/{change_id}/apply")
def apply_change(project_id: int, change_id: int, body: ChangeApplyRequest):
    project = get_project(project_id)
    change = get_change(change_id)
    if change["project_id"] != project_id:
        raise HTTPException(404, "Change not found in this project")
    content = change_service.apply(project, change, body.hunk_indexes)
    stamp = now()
    with connect() as conn:
        conn.execute("UPDATE file_changes SET status='applied',applied_content=?,updated_at=? WHERE id=?", (content, stamp, change_id))
    return {"id": change_id, "status": "applied", "path": change["path"], "applied_hunks": body.hunk_indexes}


@app.post("/api/projects/{project_id}/changes/{change_id}/reject")
def reject_change(project_id: int, change_id: int):
    change = get_change(change_id)
    if change["project_id"] != project_id:
        raise HTTPException(404, "Change not found in this project")
    if change["status"] != "proposed":
        raise HTTPException(409, "Only proposed changes can be rejected")
    with connect() as conn:
        conn.execute("UPDATE file_changes SET status='rejected',updated_at=? WHERE id=?", (now(), change_id))
    return {"id": change_id, "status": "rejected"}


@app.post("/api/projects/{project_id}/changes/{change_id}/revert")
def revert_change(project_id: int, change_id: int):
    project = get_project(project_id)
    change = get_change(change_id)
    if change["project_id"] != project_id:
        raise HTTPException(404, "Change not found in this project")
    change_service.revert(project, change)
    with connect() as conn:
        conn.execute("UPDATE file_changes SET status='reverted',updated_at=? WHERE id=?", (now(), change_id))
    return {"id": change_id, "status": "reverted", "path": change["path"]}


@app.get("/api/projects/{project_id}/git")
def git_summary(project_id: int):
    return git.summary(get_project(project_id))


@app.get("/api/projects/{project_id}/git/diff")
def git_diff(project_id: int):
    return {"diff": git.diff(get_project(project_id))}


@app.post("/api/projects/{project_id}/git/stage")
def git_stage(project_id: int, body: GitPathsRequest):
    try:
        return git.stage(get_project(project_id), body.paths)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/projects/{project_id}/git/unstage")
def git_unstage(project_id: int, body: GitPathsRequest):
    try:
        return git.unstage(get_project(project_id), body.paths)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/projects/{project_id}/git/branches")
def git_create_branch(project_id: int, body: GitBranchRequest):
    try:
        return git.create_branch(get_project(project_id), body.name, body.checkout)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/projects/{project_id}/git/checkout")
def git_checkout(project_id: int, body: GitCheckoutRequest):
    try:
        return git.checkout(get_project(project_id), body.name)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/projects/{project_id}/git/commit")
def git_commit(project_id: int, body: GitCommitRequest):
    try:
        return git.commit(get_project(project_id), body.message)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/projects/{project_id}/git/operations")
def git_operations(project_id: int):
    get_project(project_id)
    with connect() as conn:
        return rows(conn.execute("SELECT * FROM git_operations WHERE project_id=? ORDER BY id DESC LIMIT 20", (project_id,)))


@app.post("/api/projects/{project_id}/git/operations")
def propose_git_operation(project_id: int, body: GitRemoteOperationRequest):
    project = get_project(project_id)
    try:
        prepared = git.remote_operation(project, body.action, body.remote, body.branch)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    stamp = now()
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO git_operations(project_id,action,remote,remote_url,branch,command,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (project_id, prepared["action"], prepared["remote"], prepared["remote_url"], prepared["branch"], prepared["command"], "pending", stamp, stamp),
        )
    return get_git_operation(cursor.lastrowid)


@app.post("/api/projects/{project_id}/git/operations/{operation_id}/approve")
def approve_git_operation(project_id: int, operation_id: int):
    project = get_project(project_id)
    operation = get_git_operation(operation_id)
    if operation["project_id"] != project_id:
        raise HTTPException(404, "Git operation not found in this project")
    if operation["status"] != "pending":
        raise HTTPException(409, "Only pending Git operations can be approved")
    try:
        result = git.execute_remote_operation(project, operation)
    except ValueError as exc:
        with connect() as conn:
            conn.execute("UPDATE git_operations SET status='failed',output=?,updated_at=? WHERE id=?", (str(exc), now(), operation_id))
        raise HTTPException(409, str(exc)) from exc
    with connect() as conn:
        conn.execute("UPDATE git_operations SET status='completed',output=?,updated_at=? WHERE id=?", (result["output"], now(), operation_id))
    return {**get_git_operation(operation_id), "summary": result["summary"]}


@app.post("/api/projects/{project_id}/git/operations/{operation_id}/reject")
def reject_git_operation(project_id: int, operation_id: int):
    get_project(project_id)
    operation = get_git_operation(operation_id)
    if operation["project_id"] != project_id:
        raise HTTPException(404, "Git operation not found in this project")
    if operation["status"] != "pending":
        raise HTTPException(409, "Only pending Git operations can be rejected")
    with connect() as conn:
        conn.execute("UPDATE git_operations SET status='rejected',updated_at=? WHERE id=?", (now(), operation_id))
    return get_git_operation(operation_id)


@app.get("/api/projects/{project_id}/github")
def github_status(project_id: int):
    return github_service.status(get_project(project_id))


@app.get("/api/projects/{project_id}/github/issues")
def github_issues(project_id: int):
    try:
        return github_service.issues(get_project(project_id))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/api/projects/{project_id}/github/issues/{issue_number}/task")
def github_issue_task(project_id: int, issue_number: int):
    project = get_project(project_id)
    try:
        issue = github_service.issue(project, issue_number)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    title = f"Issue #{issue['number']}: {issue['title']}"
    prompt = f"Implement GitHub issue #{issue['number']}: {issue['title']}\n\n{issue.get('body') or 'No issue description provided.'}\n\nSource: {issue.get('url', '')}"
    stamp = now()
    with connect() as conn:
        cursor = conn.execute("INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)", (project_id, title[:200], stamp, stamp))
        session_id = cursor.lastrowid
    return task_queue.enqueue(project_id, session_id, title[:200], prompt, "github_issue", issue.get("url", ""))


@app.get("/api/projects/{project_id}/github/operations")
def github_operations(project_id: int):
    get_project(project_id)
    with connect() as conn:
        return rows(conn.execute("SELECT * FROM github_operations WHERE project_id=? ORDER BY id DESC LIMIT 20", (project_id,)))


@app.post("/api/projects/{project_id}/github/pull-requests")
def propose_github_pull_request(project_id: int, body: GitHubPullRequestRequest):
    project = get_project(project_id)
    try:
        prepared = github_service.prepare_pull_request(project, body.title, body.body, body.base)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    stamp = now()
    with connect() as conn:
        cursor = conn.execute(
            "INSERT INTO github_operations(project_id,action,repository,title,body,head,base,command,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, prepared["action"], prepared["repository"], prepared["title"], prepared["body"], prepared["head"], prepared["base"], prepared["command"], "pending", stamp, stamp),
        )
    return get_github_operation(cursor.lastrowid)


@app.post("/api/projects/{project_id}/github/operations/{operation_id}/approve")
def approve_github_operation(project_id: int, operation_id: int):
    project = get_project(project_id)
    operation = get_github_operation(operation_id)
    if operation["project_id"] != project_id:
        raise HTTPException(404, "GitHub operation not found in this project")
    if operation["status"] != "pending":
        raise HTTPException(409, "Only pending GitHub operations can be approved")
    with connect() as conn:
        claimed = conn.execute("UPDATE github_operations SET status='running',updated_at=? WHERE id=? AND status='pending'", (now(), operation_id))
        if claimed.rowcount != 1:
            raise HTTPException(409, "This GitHub operation is already being processed")
    try:
        result = github_service.execute_pull_request(project, operation)
    except ValueError as exc:
        with connect() as conn:
            conn.execute("UPDATE github_operations SET status='failed',output=?,updated_at=? WHERE id=?", (str(exc), now(), operation_id))
        raise HTTPException(409, str(exc)) from exc
    with connect() as conn:
        conn.execute("UPDATE github_operations SET status='completed',output=?,updated_at=? WHERE id=?", (result["output"], now(), operation_id))
    return {**get_github_operation(operation_id), **result}


@app.post("/api/projects/{project_id}/github/operations/{operation_id}/reject")
def reject_github_operation(project_id: int, operation_id: int):
    get_project(project_id)
    operation = get_github_operation(operation_id)
    if operation["project_id"] != project_id:
        raise HTTPException(404, "GitHub operation not found in this project")
    if operation["status"] != "pending":
        raise HTTPException(409, "Only pending GitHub operations can be rejected")
    with connect() as conn:
        conn.execute("UPDATE github_operations SET status='rejected',updated_at=? WHERE id=?", (now(), operation_id))
    return get_github_operation(operation_id)


@app.get("/api/sessions/{session_id}/summary")
def session_summary(session_id: int):
    with connect() as conn:
        session = conn.execute("SELECT id,summary,last_summarized_message_id FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not session:
        raise HTTPException(404, "Session not found")
    return dict(session)


@app.post("/api/sessions/{session_id}/summary")
def rebuild_session_summary(session_id: int):
    with connect() as conn:
        session = conn.execute("SELECT id FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            raise HTTPException(404, "Session not found")
        messages = rows(conn.execute("SELECT id,role,content,activities FROM messages WHERE session_id=? ORDER BY id", (session_id,)))
        summary = build_session_summary(messages)
        last_id = messages[-1]["id"] if messages else 0
        conn.execute("UPDATE sessions SET summary=?,last_summarized_message_id=? WHERE id=?", (summary, last_id, session_id))
    return {"id": session_id, "summary": summary, "last_summarized_message_id": last_id}


@app.get("/api/projects/{project_id}/office")
def inspect_office(project_id: int, path: str):
    try:
        return office.inspect(get_project(project_id), path)
    except ValueError as exc:
        raise HTTPException(415, str(exc)) from exc


@app.post("/api/projects/{project_id}/office")
def create_office(project_id: int, body: OfficeCreateRequest):
    try:
        return office.create(get_project(project_id), body.kind, body.path, body.title, body.content, body.data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
