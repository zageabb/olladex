from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import settings
from .database import connect, decode_json, init_db, now, rows
from .schemas import ChatRequest, CommandRequest, FileWriteRequest, OfficeCreateRequest, ProjectCreate, SessionCreate
from .services import git, office, ollama, terminal, workspace


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
            return dict(existing)
        cursor = conn.execute("INSERT INTO projects(name,path,model,created_at,last_opened_at) VALUES(?,?,?,?,?)", (body.name or path.name, str(path), body.model or settings.ollama_model, stamp, stamp))
        project_id = cursor.lastrowid
        conn.execute("INSERT INTO sessions(project_id,title,created_at,updated_at) VALUES(?,?,?,?)", (project_id, "Welcome to Olladex", stamp, stamp))
    return get_project(project_id)


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
    with connect() as conn:
        cursor = conn.execute("INSERT INTO file_changes(project_id,session_id,path,before_content,after_content,diff,created_at) VALUES(?,?,?,?,?,?,?)", (project_id, body.session_id, path, before, after, diff, now()))
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
        cursor = conn.execute("INSERT INTO messages(session_id,role,content,activities,created_at) VALUES(?,?,?,?,?)", (session_id, "assistant", answer, json.dumps(activities, default=str), stamp))
        conn.execute("UPDATE sessions SET updated_at=? WHERE id=?", (stamp, session_id))
        for activity in activities:
            if activity.get("tool") == "write_file" and isinstance(activity.get("result"), dict):
                result = activity["result"]
                conn.execute(
                    "INSERT INTO file_changes(project_id,session_id,path,before_content,after_content,diff,created_at) VALUES(?,?,?,?,?,?,?)",
                    (project["id"], session_id, result.get("path", ""), result.get("before", ""), result.get("after", ""), result.get("diff", ""), stamp),
                )
    return {"id": cursor.lastrowid, "role": "assistant", "content": answer, "activities": activities, "created_at": stamp}


@app.post("/api/projects/{project_id}/terminal")
def run_terminal(project_id: int, body: CommandRequest):
    result = terminal.run(get_project(project_id), body.command, body.timeout_seconds)
    with connect() as conn:
        cursor = conn.execute("INSERT INTO command_runs(project_id,command,output,exit_code,created_at) VALUES(?,?,?,?,?)", (project_id, body.command, result["output"], result["exit_code"], now()))
    return {"id": cursor.lastrowid, **result}


@app.get("/api/projects/{project_id}/terminal")
def terminal_history(project_id: int):
    get_project(project_id)
    with connect() as conn:
        return rows(conn.execute("SELECT * FROM command_runs WHERE project_id=? ORDER BY id DESC LIMIT 40", (project_id,)))


@app.get("/api/projects/{project_id}/changes")
def changes(project_id: int):
    get_project(project_id)
    with connect() as conn:
        return rows(conn.execute("SELECT id,path,diff,status,created_at FROM file_changes WHERE project_id=? ORDER BY id DESC LIMIT 100", (project_id,)))


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
