from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import settings
from .database import connect, decode_json, init_db, now, rows
from .schemas import ChangeApplyRequest, ChatRequest, CommandRequest, FileWriteRequest, OfficeCreateRequest, ProjectCreate, ProjectSettingsRequest, SessionCreate
from .services import changes as change_service
from .services import git, office, ollama, terminal, terminal_jobs, workspace


app = FastAPI(title="Olladex API", version=__version__)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(",")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup() -> None:
    init_db()


def get_project(project_id: int) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
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


@app.get("/health")
def health():
    return {"status": "ok", "name": "Olladex", "version": __version__}


@app.get("/api/status")
def api_status():
    return {"version": __version__, "ollama": ollama.status(), "shell": "/bin/bash"}


@app.get("/api/projects")
def list_projects():
    with connect() as conn:
        return rows(conn.execute("SELECT * FROM projects ORDER BY last_opened_at DESC"))


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
            cursor = conn.execute("INSERT INTO projects(name,path,model,created_at,last_opened_at) VALUES(?,?,?,?,?)", (body.name or path.name, str(path), body.model or settings.ollama_model, stamp, stamp))
            project_id = cursor.lastrowid
            conn.execute("INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)", (project_id, "Welcome to Olladex", stamp, stamp))
    return get_project(project_id)


@app.get("/api/projects/{project_id}/settings")
def project_settings(project_id: int):
    return get_project(project_id)


@app.patch("/api/projects/{project_id}/settings")
def update_project_settings(project_id: int, body: ProjectSettingsRequest):
    get_project(project_id)
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return get_project(project_id)
    assignments = ",".join(f"{name}=?" for name in updates)
    with connect() as conn:
        conn.execute(f"UPDATE projects SET {assignments} WHERE id=?", (*updates.values(), project_id))
    return get_project(project_id)


@app.get("/api/projects/{project_id}/intelligence")
def project_intelligence(project_id: int):
    return workspace.repository_intelligence(get_project(project_id))


@app.get("/api/projects/{project_id}/tree")
def get_tree(project_id: int):
    return workspace.tree(get_project(project_id))


@app.get("/api/projects/{project_id}/files")
def read_file(project_id: int, path: str = Query(...)):
    return {"path": path, "content": workspace.read_text(get_project(project_id), path)}


@app.put("/api/projects/{project_id}/files")
def write_file(project_id: int, path: str, body: FileWriteRequest):
    project = get_project(project_id)
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
    return {"id": cursor.lastrowid, "project_id": project_id, "title": body.title, "created_at": stamp, "updated_at": stamp}


@app.get("/api/sessions/{session_id}/messages")
def list_messages(session_id: int):
    with connect() as conn:
        result = rows(conn.execute("SELECT * FROM messages WHERE session_id=? ORDER BY id", (session_id,)))
    for item in result:
        item["activities"] = decode_json(item.get("activities"))
    return result


@app.post("/api/sessions/{session_id}/messages")
def chat_message(session_id: int, body: ChatRequest):
    with connect() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            raise HTTPException(404, "Session not found")
        history = rows(conn.execute("SELECT role,content FROM messages WHERE session_id=? ORDER BY id", (session_id,)))
        conn.execute("INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)", (session_id, "user", body.content, now()))
    project = get_project(session["project_id"])
    try:
        answer, activities = ollama.chat(project, [*history, {"role": "user", "content": body.content}])
    except Exception as exc:
        raise HTTPException(502, f"Ollama request failed: {exc}") from exc
    stamp = now()
    with connect() as conn:
        for activity in activities:
            if activity.get("tool") == "write_file" and isinstance(activity.get("result"), dict):
                result = activity["result"]
                hunks = change_service.build_hunks(result.get("before", ""), result.get("after", ""))
                change_cursor = conn.execute(
                    "INSERT INTO file_changes(project_id,session_id,path,before_content,after_content,diff,hunks,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (project["id"], session_id, result.get("path", ""), result.get("before", ""), result.get("after", ""), result.get("diff", ""), json.dumps(hunks), "proposed", stamp, stamp),
                )
                result["change_id"] = change_cursor.lastrowid
                result["hunks"] = hunks
                result.pop("before", None)
                result.pop("after", None)
            if activity.get("tool") == "run_command" and isinstance(activity.get("result"), dict):
                result = activity["result"]
                command_cursor = conn.execute(
                    "INSERT INTO command_runs(project_id,command,output,exit_code,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                    (project["id"], result.get("command", ""), result.get("output", ""), result.get("exit_code", -1), result.get("status", "completed"), stamp, stamp),
                )
                result["command_run_id"] = command_cursor.lastrowid
        cursor = conn.execute("INSERT INTO messages(session_id,role,content,activities,created_at) VALUES(?,?,?,?,?)", (session_id, "assistant", answer, json.dumps(activities, default=str), stamp))
        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (stamp, session_id))
    return {"id": cursor.lastrowid, "role": "assistant", "content": answer, "activities": activities, "created_at": stamp}


@app.post("/api/projects/{project_id}/terminal")
def run_terminal(project_id: int, body: CommandRequest):
    result = terminal.run(get_project(project_id), body.command, body.timeout_seconds)
    with connect() as conn:
        stamp = now()
        cursor = conn.execute("INSERT INTO command_runs(project_id,command,output,exit_code,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (project_id, body.command, result["output"], result["exit_code"], "completed", stamp, stamp))
    return {"id": cursor.lastrowid, "status": "completed", **result}


@app.post("/api/projects/{project_id}/terminal/start")
def start_terminal(project_id: int, body: CommandRequest):
    project = get_project(project_id)
    stamp = now()
    with connect() as conn:
        cursor = conn.execute("INSERT INTO command_runs(project_id,command,output,exit_code,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (project_id, body.command, "", -1, "pending", stamp, stamp))
        run_id = cursor.lastrowid
    return {"command": body.command, **terminal_jobs.start(project, run_id, body.command, body.timeout_seconds or 600)}


@app.get("/api/terminal/{run_id}")
def terminal_status(run_id: int):
    result = terminal_jobs.status(run_id)
    if not result:
        raise HTTPException(404, "Command run not found")
    return result


@app.delete("/api/terminal/{run_id}")
def cancel_terminal(run_id: int):
    command = get_command(run_id)
    if command["status"] == "pending":
        with connect() as conn:
            conn.execute("UPDATE command_runs SET status='cancelled',updated_at=? WHERE id=?", (now(), run_id))
        return get_command(run_id)
    return terminal_jobs.cancel(run_id)


@app.post("/api/projects/{project_id}/terminal/{run_id}/approve")
def approve_terminal(project_id: int, run_id: int):
    project = get_project(project_id)
    command = get_command(run_id)
    if command["project_id"] != project_id:
        raise HTTPException(404, "Command run not found in this project")
    if command["status"] != "pending":
        raise HTTPException(409, "Only pending commands can be approved")
    return {"command": command["command"], **terminal_jobs.start(project, run_id, command["command"])}


@app.get("/api/projects/{project_id}/terminal")
def terminal_history(project_id: int):
    get_project(project_id)
    with connect() as conn:
        return rows(conn.execute("SELECT * FROM command_runs WHERE project_id=? ORDER BY id DESC LIMIT 40", (project_id,)))


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
