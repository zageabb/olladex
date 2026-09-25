import asyncio
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from .database import connect
from .services import conversation_runtime as runtime

router = APIRouter()

class Turn(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)
    resume_id: int | None = None

class Decision(BaseModel):
    accepted: bool

@router.post('/api/sessions/{session_id}/runs')
def start(session_id: int, body: Turn):
    return runtime.launch(session_id, body.content, body.resume_id)

@router.get('/api/sessions/{session_id}/runs')
def runs(session_id: int):
    with connect() as conn:
        return [dict(row) for row in conn.execute('SELECT id,session_id,status,created_at,updated_at FROM agent_runs WHERE session_id=? ORDER BY id', (session_id,))]

@router.get('/api/runs/{run_id}/events')
def events(run_id: int, after: int = 0):
    runtime.get(run_id)
    async def stream():
        cursor = after
        while True:
            batch = await asyncio.to_thread(runtime.events, run_id, cursor)
            for event in batch:
                cursor = event['id']
                yield json.dumps(event) + '\n'
            status = (await asyncio.to_thread(runtime.get, run_id))['status']
            if status not in runtime.ACTIVE and not batch:
                yield json.dumps({'kind': 'end', 'payload': {'status': status}}) + '\n'
                return
            if not batch:
                yield '\n'
                await asyncio.sleep(.15)
    return StreamingResponse(stream(), media_type='application/x-ndjson', headers={'Cache-Control':'no-store', 'X-Accel-Buffering':'no'})

@router.post('/api/runs/{run_id}/input')
def steer(run_id: int, body: Turn):
    runtime.steer(run_id, body.content)
    return {'status': 'received'}

@router.delete('/api/runs/{run_id}')
def stop(run_id: int):
    return runtime.stop(run_id)

@router.post('/api/commands/{command_id}/decision')
def decide(command_id: int, body: Decision):
    return runtime.approve(command_id, body.accepted)


class Memory(BaseModel):
    content: str = Field(max_length=8000)

@router.get('/api/sessions/{session_id}/memory')
def memory(session_id: int):
    with connect() as conn:
        row = conn.execute('SELECT memory FROM sessions WHERE id=?', (session_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Session not found')
    return {'content': row['memory']}

@router.put('/api/sessions/{session_id}/memory')
def save_memory(session_id: int, body: Memory):
    with connect() as conn:
        cursor = conn.execute('UPDATE sessions SET memory=? WHERE id=?', (body.content, session_id))
        if not cursor.rowcount:
            raise HTTPException(404, 'Session not found')
    return {'content': body.content}


VALID_MEMORY_SCOPES = {'personal', 'workspace', 'project'}

def _memory_key(scope: str, project_id: int | None, workspace_id: int | None = None) -> str:
    if scope == 'personal':
        return 'default'
    if scope == 'workspace':
        if not workspace_id:
            raise HTTPException(400, 'workspace_id is required for workspace memory')
        with connect() as conn:
            if not conn.execute('SELECT id FROM workspaces WHERE id=?', (workspace_id,)).fetchone():
                raise HTTPException(404, 'Workspace not found')
        return str(workspace_id)
    if scope == 'project':
        if not project_id:
            raise HTTPException(400, 'project_id is required for project memory')
        with connect() as conn:
            if not conn.execute('SELECT id FROM projects WHERE id=?', (project_id,)).fetchone():
                raise HTTPException(404, 'Project not found')
        return str(project_id)
    raise HTTPException(400, 'Unsupported memory scope')

@router.get('/api/memory/{scope}')
def scoped_memory(scope: str, project_id: int | None = None, workspace_id: int | None = None):
    if scope not in VALID_MEMORY_SCOPES:
        raise HTTPException(400, 'Unsupported memory scope')
    key = _memory_key(scope, project_id, workspace_id)
    with connect() as conn:
        row = conn.execute('SELECT content,updated_at FROM memory_scopes WHERE scope=? AND scope_key=?', (scope, key)).fetchone()
    return {'scope': scope, 'scope_key': key, 'content': row['content'] if row else '', 'updated_at': row['updated_at'] if row else ''}

@router.put('/api/memory/{scope}')
def save_scoped_memory(scope: str, body: Memory, project_id: int | None = None, workspace_id: int | None = None):
    if scope not in VALID_MEMORY_SCOPES:
        raise HTTPException(400, 'Unsupported memory scope')
    key = _memory_key(scope, project_id, workspace_id)
    from .database import now
    stamp = now()
    with connect() as conn:
        existing = conn.execute('SELECT id FROM memory_scopes WHERE scope=? AND scope_key=?', (scope, key)).fetchone()
        if existing:
            conn.execute('UPDATE memory_scopes SET content=?,updated_at=? WHERE id=?', (body.content, stamp, existing['id']))
        else:
            conn.execute('INSERT INTO memory_scopes(scope,scope_key,content,created_at,updated_at) VALUES(?,?,?,?,?)', (scope, key, body.content, stamp, stamp))
    return {'scope': scope, 'scope_key': key, 'content': body.content, 'updated_at': stamp}
