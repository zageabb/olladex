from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .database import connect, now

router = APIRouter()


class ChatTitleRequest(BaseModel):
    title: str


@router.patch("/api/sessions/{session_id}")
def rename_session(session_id: int, body: ChatTitleRequest):
    title = body.title.strip()[:100]
    if not title:
        raise HTTPException(400, "Chat title cannot be empty")
    with connect() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            raise HTTPException(404, "Chat not found")
        conn.execute("UPDATE sessions SET title=?,updated_at=? WHERE id=?", (title, now(), session_id))
        updated = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    return dict(updated)
