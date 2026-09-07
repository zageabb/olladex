from fastapi import APIRouter, HTTPException
from .database import connect, now, rows
from .schemas import CommandRequest, TerminalInputRequest, TerminalResizeRequest
from .services import terminal, terminal_jobs
from .main import get_project, get_command
router = APIRouter()

@router.post("/api/projects/{project_id}/terminal")
def run_terminal(project_id: int, body: CommandRequest):
    result = terminal.run(get_project(project_id), body.command, body.timeout_seconds)
    with connect() as conn:
        stamp = now()
        cursor = conn.execute("INSERT INTO command_runs(project_id,command,output,exit_code,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (project_id, body.command, result["output"], result["exit_code"], "completed", stamp, stamp))
    return {"id": cursor.lastrowid, "status": "completed", **result}


@router.post("/api/projects/{project_id}/terminal/start")
def start_terminal(project_id: int, body: CommandRequest):
    project = get_project(project_id)
    stamp = now()
    with connect() as conn:
        cursor = conn.execute("INSERT INTO command_runs(project_id,command,output,exit_code,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (project_id, body.command, "", -1, "pending", stamp, stamp))
        run_id = cursor.lastrowid
    return {"command": body.command, **terminal_jobs.start(project, run_id, body.command, body.timeout_seconds or 600, body.columns, body.rows)}


@router.get("/api/terminal/{run_id}")
def terminal_status(run_id: int):
    result = terminal_jobs.status(run_id)
    if not result:
        raise HTTPException(404, "Command run not found")
    return result


@router.delete("/api/terminal/{run_id}")
def cancel_terminal(run_id: int):
    command = get_command(run_id)
    if command["status"] == "pending":
        with connect() as conn:
            conn.execute("UPDATE command_runs SET status='cancelled',updated_at=? WHERE id=?", (now(), run_id))
        return get_command(run_id)
    return terminal_jobs.cancel(run_id)


@router.post("/api/terminal/{run_id}/input")
def terminal_input(run_id: int, body: TerminalInputRequest):
    get_command(run_id)
    try:
        return terminal_jobs.write_input(run_id, body.data)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/api/terminal/{run_id}/resize")
def terminal_resize(run_id: int, body: TerminalResizeRequest):
    get_command(run_id)
    try:
        return terminal_jobs.resize(run_id, body.columns, body.rows)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/api/projects/{project_id}/terminal/{run_id}/approve")
def approve_terminal(project_id: int, run_id: int):
    project = get_project(project_id)
    command = get_command(run_id)
    if command["project_id"] != project_id:
        raise HTTPException(404, "Command run not found in this project")
    if command.get("run_id"):
        from .services import conversation_runtime
        return conversation_runtime.approve(run_id, True)
    if command.get("cwd"):
        project = {**project, "path": command["cwd"]}
    if command["status"] != "pending":
        raise HTTPException(409, "Only pending commands can be approved")
    return {"command": command["command"], **terminal_jobs.start(project, run_id, command["command"])}


@router.get("/api/projects/{project_id}/terminal")
def terminal_history(project_id: int):
    get_project(project_id)
    with connect() as conn:
        return rows(conn.execute("SELECT * FROM command_runs WHERE project_id=? ORDER BY id DESC LIMIT 40", (project_id,)))


