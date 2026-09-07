import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from backend.app.api import app
from backend.app.config import settings
from backend.app.database import connect, now
from backend.app.services import conversation_runtime as runtime, ollama, workspace, terminal, terminal_jobs, repository_index

@pytest.fixture
def client_project(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'data_root', tmp_path / 'data')
    repo = tmp_path / 'repo'; repo.mkdir()
    with TestClient(app) as client:
        project = client.post('/api/projects', json={'path': str(repo)}).json()
        session = client.get(f"/api/projects/{project['id']}/sessions").json()[0]
        yield client, project, session, repo

def wait_for(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = predicate()
        if value: return value
        time.sleep(.02)
    raise AssertionError('Timed out')

def test_auth_and_origin(client_project):
    client, _, _, _ = client_project
    assert client.get('/api/projects', headers={'Authorization': ''}).status_code == 401
    assert client.get('/api/projects', headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.get('/health').status_code == 200

def test_boundaries(tmp_path, client_project):
    repo = client_project[3]
    external = tmp_path / 'secret.txt'; external.write_text('external marker')
    (repo / 'linked.txt').symlink_to(external)
    project = {'path': str(repo), 'approval_mode':'assisted'}
    assert workspace.search(project, 'external marker') == []
    for path in [str(external), '../secret.txt']:
        with pytest.raises(Exception): workspace.write_text(project, path, 'bad')
    assert external.read_text() == 'external marker'
    for cmd in ['git status; echo bypass', 'ls $(echo bypass)', 'sed -i x file', 'pytest -q']:
        assert terminal.requires_approval(project, cmd)
    thread = threading.Thread(target=terminal_jobs.cancel, args=(-1,), daemon=True)
    thread.start(); thread.join(1)
    assert not thread.is_alive()

def test_isolated_indexes(client_project):
    _, project, _, repo = client_project
    other = repo.parent / 'worktree'; other.mkdir()
    (repo/'source.py').write_text('main_unique')
    (other/'source.py').write_text('branch_unique')
    repository_index.refresh(project)
    alternate = {**project, 'path': str(other)}
    repository_index.refresh(alternate)
    assert repository_index.ranked_context(project, 'main_unique')[0]['excerpt'] == 'main_unique'
    assert repository_index.ranked_context(alternate, 'branch_unique')[0]['excerpt'] == 'branch_unique'

def test_streaming_steering_question_and_approval(client_project, monkeypatch):
    client, project, session, repo = client_project
    def fake_chat(project, history, **kwargs):
        runtime.emit('text_delta', {'text':'I am checking the repository.'})
        result = runtime.ask('Which file should I inspect?')
        runtime.emit('text_delta', {'text': result['answer']})
        command = runtime.command(project, "printf approved")
        runtime.emit('tool_result', {'tool':'run_command','result':command})
        return 'Finished with your guidance.', []
    monkeypatch.setattr(ollama, 'chat', fake_chat)
    run = client.post(f"/api/sessions/{session['id']}/runs", json={'content':'Investigate'}).json()
    wait_for(lambda: runtime.get(run['id'])['status'] == 'waiting_for_input')
    assert any(e['kind'] == 'text_delta' for e in runtime.events(run['id']))
    assert client.post(f"/api/sessions/{session['id']}/runs", json={'content':'duplicate'}).status_code == 409
    client.post(f"/api/runs/{run['id']}/input", json={'content':'Read source.py'})
    wait_for(lambda: runtime.get(run['id'])['status'] == 'waiting_for_approval')
    approval = next(e for e in runtime.events(run['id']) if e['kind']=='approval')['payload']
    assert approval['cwd'] == str(repo.resolve())
    response = client.post(f"/api/commands/{approval['command_run_id']}/decision", json={'accepted':True})
    assert response.status_code == 200
    wait_for(lambda: runtime.get(run['id'])['status'] == 'completed')
    events = [json.loads(line) for line in client.get(f"/api/runs/{run['id']}/events").text.splitlines() if line.strip()]
    assert any(e['kind']=='tool_result' and e['payload']['result']['output']=='approved' for e in events)
    assert events[-1]['kind'] == 'end'
    last = next(e['id'] for e in reversed(events) if 'id' in e)
    assert 'text_delta' not in client.get(f"/api/runs/{run['id']}/events?after={last}").text

def test_stop_waiting_and_restart_does_not_replay(client_project, monkeypatch):
    client, _, session, _ = client_project
    def fake_chat(*args, **kwargs):
        runtime.checkpoint([{'role':'user','content':'Original objective'}])
        runtime.ask('Waiting')
        return '', []
    monkeypatch.setattr(ollama, 'chat', fake_chat)
    run = client.post(f"/api/sessions/{session['id']}/runs", json={'content':'Start'}).json()
    wait_for(lambda: runtime.get(run['id'])['status']=='waiting_for_input')
    client.delete(f"/api/runs/{run['id']}")
    wait_for(lambda: runtime.get(run['id'])['status']=='cancelled')
    assert json.loads(runtime.get(run['id'])['checkpoint'])[0]['content']=='Original objective'
    orphan = runtime.create(session['id'])
    runtime.init()
    assert runtime.get(orphan)['status']=='interrupted'

def test_patch_and_validation(client_project):
    _, project, _, repo = client_project
    (repo/'app.py').write_text('x = 1\n')
    result, activity = ollama.execute_tool(project, 'apply_patch', {'path':'app.py','old_text':'x = 1','new_text':'x = 2'})
    assert result['status']=='proposed'
    assert (repo/'app.py').read_text()=='x = 1\n'
    invalid, _ = ollama.execute_tool(project, 'read_file', {'path':'app.py','start_line':-5})
    assert invalid['recoverable']

def test_editor_conflict(client_project):
    client, project, _, repo = client_project
    (repo/'app.txt').write_text('newer content')
    response=client.put(f"/api/projects/{project['id']}/files?path=app.txt",json={'content':'overwrite','expected_content':'old content'})
    assert response.status_code==409
    assert (repo/'app.txt').read_text()=='newer content'

def test_real_agent_loop_persists_tools_before_approval(client_project, monkeypatch):
    import httpx
    client, project, session, repo = client_project
    (repo/'app.py').write_text('before\n')
    monkeypatch.setattr(ollama, 'ranked_context', lambda *a, **k: [])
    calls = []
    def provider(request):
        payload = json.loads(request.content); calls.append(payload)
        if len(calls) == 1:
            message = {'role':'assistant','content':'I will prepare a focused edit and check it.', 'tool_calls':[
                {'function':{'name':'apply_patch','arguments':{'path':'app.py','old_text':'before','new_text':'after'}}},
                {'function':{'name':'run_command','arguments':{'command':'printf checked'}}},
            ]}
        else:
            assert any(m.get('tool_name')=='run_command' and 'checked' in m.get('content','') for m in payload['messages'])
            message = {'role':'assistant','content':'The proposal is ready for review. The command passed.'}
        return httpx.Response(200, text=json.dumps({'message':message,'done':True})+'\n')
    monkeypatch.setattr(ollama, 'client', lambda *a, **k: httpx.Client(base_url='http://ollama.test', transport=httpx.MockTransport(provider)))
    run = client.post(f"/api/sessions/{session['id']}/runs", json={'content':'Change before to after'}).json()
    wait_for(lambda: runtime.get(run['id'])['status']=='waiting_for_approval')
    changes = client.get(f"/api/projects/{project['id']}/changes").json()
    assert len(changes)==1
    assert changes[0]['status']=='proposed'
    assert (repo/'app.py').read_text()=='before\n'
    client.post(f"/api/projects/{project['id']}/changes/{changes[0]['id']}/apply", json={})
    wait_for(lambda:any(e['kind']=='approval' for e in runtime.events(run['id'])))
    approval = next(e['payload'] for e in runtime.events(run['id']) if e['kind']=='approval')
    assert client.post(f"/api/projects/{project['id']}/terminal/{approval['command_run_id']}/approve").status_code==200
    wait_for(lambda: runtime.get(run['id'])['status']=='completed')
    assert len(client.get(f"/api/projects/{project['id']}/changes").json())==1
    assert len(calls)==2

def test_approval_keeps_worktree(client_project, monkeypatch):
    client, project, session, repo = client_project
    other = repo.parent/'task-workspace'; other.mkdir()
    def fake_chat(*args, **kwargs):
        # The pending command retains its explicit workspace even outside task-local context.
        result = runtime.command({**project, 'path':str(other)}, 'pwd')
        return result['output'], []
    monkeypatch.setattr(ollama,'chat',fake_chat)
    run=client.post(f"/api/sessions/{session['id']}/runs",json={'content':'Check workspace'}).json()
    wait_for(lambda: runtime.get(run['id'])['status']=='waiting_for_approval')
    approval=next(e['payload'] for e in runtime.events(run['id']) if e['kind']=='approval')
    client.post(f"/api/commands/{approval['command_run_id']}/decision",json={'accepted':True})
    wait_for(lambda: runtime.get(run['id'])['status']=='completed')
    final=next(e for e in runtime.events(run['id']) if e['kind']=='final')
    assert str(other.resolve()) in final['payload']['content']

def test_stop_silent_model(client_project, monkeypatch):
    import httpx
    client, _, session, _ = client_project
    release = threading.Event()
    monkeypatch.setattr(ollama,'ranked_context',lambda *a,**k:[])
    def provider(request):
        release.wait(3)
        return httpx.Response(200,text=json.dumps({'message':{'content':'late'},'done':True})+'\n')
    monkeypatch.setattr(ollama,'client',lambda *a,**k:httpx.Client(base_url='http://ollama.test',transport=httpx.MockTransport(provider)))
    run=client.post(f"/api/sessions/{session['id']}/runs",json={'content':'Start'}).json()
    wait_for(lambda:any(e['kind']=='assistant_start' for e in runtime.events(run['id'])))
    client.delete(f"/api/runs/{run['id']}")
    wait_for(lambda:runtime.get(run['id'])['status']=='cancelled')
    release.set()

def test_compaction_bounds_historical_file_arguments_without_mutating_checkpoint():
    messages = [
        {'role':'system','content':'Original objective and saved preferences'},
        {'role':'user','content':'Make the requested change'},
        {'role':'assistant','content':'Preparing an edit','tool_calls':[{'function':{'name':'write_file','arguments':{'path':'large.txt','content':'x'*200_000}}}]},
        {'role':'tool','tool_name':'write_file','content':'Applied after review'},
    ]
    compacted = ollama.fit_context(messages, 16384)
    assert len(json.dumps(compacted)) < 24000
    assert len(messages[2]['tool_calls'][0]['function']['arguments']['content']) == 200_000
    assert compacted[-1]['role'] == 'tool'
    assert compacted[-2]['role'] == 'assistant'

def test_followup_to_task_keeps_original_worktree(client_project, monkeypatch):
    client, project, session, repo = client_project
    worktree = repo.parent/'retained-worktree'; worktree.mkdir()
    (repo/'file.txt').write_text('main')
    (worktree/'file.txt').write_text('task')
    with connect() as conn:
        cursor = conn.execute("INSERT INTO background_tasks(project_id,session_id,title,prompt,status,worktree_path,worktree_branch,created_at) VALUES(?,?,?,?,?,?,?,?)",
                              (project['id'],session['id'],'Task','Change a file','completed',str(worktree),'olladex/task-1',now()))
        task_id = cursor.lastrowid
    def fake_chat(p, *args, **kwargs):
        result, activity = ollama.execute_tool(p,'write_file',{'path':'file.txt','content':'followup'})
        assert result['status']=='applied'
        return 'Followup complete', [activity]
    monkeypatch.setattr(ollama,'chat',fake_chat)
    run=client.post(f"/api/sessions/{session['id']}/runs",json={'content':'Continue the edit'}).json()
    wait_for(lambda:runtime.get(run['id'])['status']=='completed')
    wait_for(lambda:run['id'] not in runtime._threads)
    assert (repo/'file.txt').read_text()=='main'
    assert (worktree/'file.txt').read_text()=='followup'
    with connect() as conn:
        task=conn.execute('SELECT * FROM background_tasks WHERE id=?',(task_id,)).fetchone()
    assert task['status']=='completed'
    assert task['result']=='Followup complete'
