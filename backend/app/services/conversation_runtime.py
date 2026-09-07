"""Durable conversation events, cooperative steering and explicit recovery."""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager

from fastapi import HTTPException
from ..database import connect, now

_local = threading.local()
_lock = threading.Lock()
_threads: dict[int, threading.Thread] = {}
_stopping = threading.Event()
ACTIVE = ('running', 'waiting_for_approval', 'waiting_for_input')

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_runs (
 id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id), task_id INTEGER,
 status TEXT NOT NULL, checkpoint TEXT NOT NULL DEFAULT '[]', cancel_requested INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_session ON agent_runs(session_id)
 WHERE status IN ('running','waiting_for_approval','waiting_for_input');
CREATE TABLE IF NOT EXISTS agent_events (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES agent_runs(id), kind TEXT NOT NULL,
 payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS run_events ON agent_events(run_id,id);
CREATE TABLE IF NOT EXISTS agent_inputs (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES agent_runs(id), content TEXT NOT NULL,
 consumed INTEGER NOT NULL DEFAULT 0
);
"""


def init():
    _stopping.clear()
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute("UPDATE agent_runs SET status='interrupted' WHERE status IN ('running','waiting_for_approval','waiting_for_input')")
        conn.execute("UPDATE command_runs SET status='interrupted' WHERE status='running'")


def current_id():
    return getattr(_local, 'run_id', None)


@contextmanager
def bind(run_id):
    previous = current_id()
    _local.run_id = run_id
    try:
        yield
    finally:
        _local.run_id = previous


def get(run_id):
    with connect() as conn:
        row = conn.execute('SELECT * FROM agent_runs WHERE id=?', (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Conversation run not found')
    return dict(row)


def create(session_id, task_id=None):
    import sqlite3
    with connect() as conn:
        if not conn.execute('SELECT id FROM sessions WHERE id=?', (session_id,)).fetchone():
            raise HTTPException(404, 'Session not found')
        try:
            cursor = conn.execute('INSERT INTO agent_runs(session_id,task_id,status,created_at,updated_at) VALUES(?,?,?,?,?)',
                                  (session_id, task_id, 'running', now(), now()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'This conversation already has an active turn')
    return cursor.lastrowid


def emit(kind, payload, run_id=None):
    run_id = run_id or current_id()
    if not run_id:
        return
    with connect() as conn:
        cursor = conn.execute('INSERT INTO agent_events(run_id,kind,payload,created_at) VALUES(?,?,?,?)',
                             (run_id, kind, json.dumps(payload, default=str), now()))
    return cursor.lastrowid


def events(run_id, after=0):
    with connect() as conn:
        return [{**dict(row), 'payload': json.loads(row['payload'])} for row in conn.execute(
            'SELECT * FROM agent_events WHERE run_id=? AND id>? ORDER BY id LIMIT 500', (run_id, after))]


def state(status, run_id=None):
    run_id = run_id or current_id()
    if run_id:
        with connect() as conn:
            conn.execute('UPDATE agent_runs SET status=?,updated_at=? WHERE id=?', (status, now(), run_id))
            row = conn.execute('SELECT task_id FROM agent_runs WHERE id=?', (run_id,)).fetchone()
            if row and row['task_id'] and status in ACTIVE:
                conn.execute('UPDATE background_tasks SET status=? WHERE id=?', (status, row['task_id']))
        emit('status', {'status': status}, run_id)


def checkpoint(messages):
    if current_id():
        with connect() as conn:
            conn.execute('UPDATE agent_runs SET checkpoint=?,updated_at=? WHERE id=?', (json.dumps(messages), now(), current_id()))


def cancelled():
    if not current_id():
        return False
    return _stopping.is_set() or bool(get(current_id())['cancel_requested'])


def check_cancelled():
    from . import task_queue
    if cancelled() or task_queue.cancel_requested():
        from .ollama import AgentCancelled
        raise AgentCancelled('Stopped at your request. Completed work has been retained.')


def steer(run_id, content):
    run = get(run_id)
    if run['status'] not in ACTIVE:
        raise HTTPException(409, 'This turn is no longer active; start or resume a turn')
    with connect() as conn:
        conn.execute('INSERT INTO agent_inputs(run_id,content) VALUES(?,?)', (run_id, content))
        conn.execute('INSERT INTO messages(session_id,role,content,created_at,run_id) VALUES(?,?,?,?,?)',
                     (run['session_id'], 'user', content, now(), run_id))
    emit('user_message', {'content': content}, run_id)


def consume_inputs():
    if not current_id():
        return []
    with connect() as conn:
        rows = conn.execute('SELECT id,content FROM agent_inputs WHERE run_id=? AND consumed=0 ORDER BY id', (current_id(),)).fetchall()
        conn.execute('UPDATE agent_inputs SET consumed=1 WHERE run_id=? AND consumed=0', (current_id(),))
    return [{'role': 'user', 'content': row['content']} for row in rows]


def ask(question):
    if not current_id():
        return {'question': question, 'status': 'waiting_for_input'}
    emit('question', {'question': question})
    state('waiting_for_input')
    while True:
        check_cancelled()
        inputs = consume_inputs()
        if inputs:
            state('running')
            return {'answer': '\n'.join(item['content'] for item in inputs)}
        time.sleep(.1)


def command(project, command):
    from . import task_queue, terminal, workspace
    from ..config import settings
    cwd = str(workspace.project_root(project))
    pending = terminal.requires_approval(project, command)
    with connect() as conn:
        cursor = conn.execute('INSERT INTO command_runs(project_id,task_id,run_id,cwd,command,output,exit_code,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (project['id'], task_queue.current_task_id(), current_id(), cwd, command, '', -1, 'pending' if pending else 'running', now(), now()))
        command_id = cursor.lastrowid
    if pending:
        emit('approval', {'command_run_id': command_id, 'command': command, 'cwd': cwd})
        state('waiting_for_approval')
        while True:
            check_cancelled()
            with connect() as conn:
                row = conn.execute('SELECT status FROM command_runs WHERE id=?', (command_id,)).fetchone()
            if row['status'] == 'approved':
                break
            if row['status'] == 'rejected':
                state('running')
                return {'command': command, 'output': 'The user declined this command. Choose another approach.', 'exit_code': 126, 'status': 'rejected', 'command_run_id': command_id}
            time.sleep(.1)
    check_cancelled()
    state('running')
    with connect() as conn:
        conn.execute("UPDATE command_runs SET status='running' WHERE id=?", (command_id,))
    result = terminal.run({**project, 'path': cwd}, command, settings.command_timeout_seconds)
    with connect() as conn:
        conn.execute('UPDATE command_runs SET status=?,output=?,exit_code=?,updated_at=? WHERE id=?',
                     ('completed', result['output'], result['exit_code'], now(), command_id))
    return {**result, 'status': 'completed', 'command_run_id': command_id, 'cwd': cwd}


def approve(command_id, accepted):
    with connect() as conn:
        row = conn.execute('SELECT * FROM command_runs WHERE id=?', (command_id,)).fetchone()
        if not row or not row['run_id']:
            raise HTTPException(404, 'Conversation command not found')
        run = conn.execute('SELECT status,cancel_requested FROM agent_runs WHERE id=?', (row['run_id'],)).fetchone()
        if not run or run['status'] != 'waiting_for_approval' or run['cancel_requested']:
            raise HTTPException(409, 'This approval is no longer active')
        cursor = conn.execute("UPDATE command_runs SET status=?,updated_at=? WHERE id=? AND status='pending'", ('approved' if accepted else 'rejected', now(), command_id))
        if cursor.rowcount != 1:
            raise HTTPException(409, 'This command has already been decided')
    emit('approval_decided', {'command_run_id': command_id, 'accepted': accepted}, row['run_id'])
    return {'status': 'approved' if accepted else 'rejected'}


def launch(session_id, content, resume_id=None):
    checkpoint_data = None
    task_id = None
    if resume_id:
        prior = get(resume_id)
        if prior['session_id'] != session_id or prior['status'] not in ('interrupted', 'budget_exhausted', 'cancelled', 'failed'):
            raise HTTPException(409, 'Only a stopped or interrupted turn can be resumed')
        checkpoint_data = json.loads(prior['checkpoint'])
        task_id = prior['task_id']
        if task_id:
            from . import task_queue
            task = task_queue.get(task_id)
            if not task or not task.get('worktree_path'):
                raise HTTPException(409, 'The original task workspace is unavailable')
    if not resume_id:
        with connect() as conn:
            task = conn.execute("SELECT id,worktree_path FROM background_tasks WHERE session_id=? ORDER BY id DESC LIMIT 1", (session_id,)).fetchone()
        if task and task['worktree_path']:
            from pathlib import Path
            if not Path(task['worktree_path']).is_dir():
                raise HTTPException(409, 'The task workspace is unavailable; start a new conversation to use the main project')
            task_id = task['id']
    run_id = create(session_id, task_id)
    def worker():
        with bind(run_id):
            from . import task_queue
            task_queue._local.task_id = task_id
            if task_id:
                with connect() as conn:
                    conn.execute("UPDATE background_tasks SET cancel_requested=0,status='running' WHERE id=?", (task_id,))
            result = None
            error = ""
            try:
                from ..main import run_session_agent
                _local.resume = checkpoint_data
                result = run_session_agent(session_id, content)
                if task_id and get(run_id)['status'] == 'running':
                    task = task_queue.get(task_id)
                    sha = task_queue._auto_commit_specialist(task)
                    if sha:
                        result['content'] += f'\n\nTask branch auto-committed as {sha[:12]}.'
                emit('final', result)
                if get(run_id)['status'] == 'running':
                    state('completed')
            except Exception as exc:
                from .ollama import AgentCancelled
                error = str(exc)
                emit('error', {'message': error})
                state('cancelled' if isinstance(exc, AgentCancelled) else 'failed')
            finally:
                if task_id:
                    final_status = get(run_id)["status"]
                    with connect() as conn:
                        conn.execute("UPDATE background_tasks SET status=?,result=?,error=?,completed_at=? WHERE id=?", (final_status, result["content"] if result else "", error, now(), task_id))
                    task_queue._finalize_parent(task_queue.get(task_id), final_status, result=result["content"] if result else "", error=error)
                _local.resume = None
                task_queue._local.task_id = None
                with _lock:
                    _threads.pop(run_id, None)
    thread = threading.Thread(target=worker, name=f'olladex-conversation-{run_id}', daemon=True)
    with _lock:
        _threads[run_id] = thread
    thread.start()
    return get(run_id)


def resume_messages():
    value = getattr(_local, 'resume', None)
    _local.resume = None
    if not value:
        return None
    # An interrupted call may have performed its side effect before recording a result.
    # Fill unanswered tool calls with an explicit unknown result; never replay them.
    last_assistant = next((i for i in range(len(value)-1, -1, -1) if value[i].get('role') == 'assistant'), None)
    if last_assistant is not None:
        calls = value[last_assistant].get('tool_calls') or []
        answered = sum(m.get('role') == 'tool' for m in value[last_assistant+1:])
        for call in calls[answered:]:
            value.append({'role': 'tool', 'tool_name': call['function']['name'], 'content': 'Execution was interrupted. Outcome is unknown. Inspect the workspace and ask before repeating any mutation or command.'})
    return value


def stop(run_id):
    if get(run_id)['status'] not in ACTIVE:
        raise HTTPException(409, 'This turn has already ended')
    with connect() as conn:
        conn.execute('UPDATE agent_runs SET cancel_requested=1 WHERE id=?', (run_id,))
    emit('status', {'status': 'stopping'}, run_id)
    return {'status': 'stopping'}


def shutdown():
    _stopping.set()
    with _lock:
        threads = list(_threads.values())
    for thread in threads:
        thread.join(timeout=2)


def wait_for_change(project, result):
    change_id = result['change_id']
    emit('change_approval', {'change_id': change_id, 'project_id': project['id'], 'path': result['path'], 'diff': result['diff']})
    state('waiting_for_approval')
    while True:
        check_cancelled()
        with connect() as conn:
            row = conn.execute('SELECT status,applied_content FROM file_changes WHERE id=?', (change_id,)).fetchone()
        if row['status'] != 'proposed':
            state('running')
            return {**result, 'status': row['status'], 'applied_content': row['applied_content'],
                    'note': 'The user reviewed this proposal. Only applied_content is on disk; selected hunks may differ from the original proposal.'}
        time.sleep(.1)
