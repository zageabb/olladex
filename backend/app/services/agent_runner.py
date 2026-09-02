from __future__ import annotations

import json
from collections.abc import Callable

from ..database import connect, now, rows
from . import changes as change_service
from . import ollama
from .session_summary import build as build_session_summary


def run(session_id: int, project: dict, content: str, checkpoint: Callable[[], None] | None = None) -> dict:
    """Persist one complete agent turn and return its assistant message."""
    if checkpoint:
        checkpoint()
    with connect() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id=? AND project_id=?", (session_id, project["id"])).fetchone()
        if not session:
            raise ValueError("Session not found in this project")
        history = rows(conn.execute("SELECT role,content FROM messages WHERE session_id=? ORDER BY id", (session_id,)))
        conn.execute("INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)", (session_id, "user", content, now()))

    answer, activities = ollama.chat(
        project,
        [*history, {"role": "user", "content": content}],
        session_summary=session["summary"] or "",
        checkpoint=checkpoint,
    )
    if checkpoint:
        checkpoint()
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
        message_id = cursor.lastrowid
        summary_messages = rows(conn.execute("SELECT role,content,activities FROM messages WHERE session_id=? ORDER BY id", (session_id,)))
        summary = build_session_summary(summary_messages)
        conn.execute("UPDATE sessions SET summary=?,last_summarized_message_id=? WHERE id=?", (summary, message_id, session_id))
    return {"id": message_id, "role": "assistant", "content": answer, "activities": activities, "created_at": stamp}
