import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from .config import settings


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=10000;
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  model TEXT NOT NULL,
  approval_mode TEXT NOT NULL DEFAULT 'assisted',
  instructions TEXT NOT NULL DEFAULT '',
  git_author_name TEXT NOT NULL DEFAULT 'Olladex User',
  git_author_email TEXT NOT NULL DEFAULT 'olladex@local',
  model_profile_id INTEGER REFERENCES model_profiles(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  last_opened_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  chat_model TEXT NOT NULL,
  embedding_model TEXT NOT NULL DEFAULT '',
  temperature REAL NOT NULL DEFAULT 0.2,
  max_steps INTEGER NOT NULL DEFAULT 8,
  context_files INTEGER NOT NULL DEFAULT 8,
  context_chars INTEGER NOT NULL DEFAULT 32000,
  is_builtin INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  last_summarized_message_id INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  activities TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS file_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
  path TEXT NOT NULL,
  before_content TEXT NOT NULL,
  after_content TEXT NOT NULL,
  diff TEXT NOT NULL,
  hunks TEXT NOT NULL DEFAULT '[]',
  applied_content TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'applied',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS command_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  command TEXT NOT NULL,
  output TEXT NOT NULL,
  exit_code INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'completed',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS git_operations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  action TEXT NOT NULL,
  remote TEXT NOT NULL,
  remote_url TEXT NOT NULL,
  branch TEXT NOT NULL,
  command TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  output TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS repository_index (
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  content TEXT NOT NULL,
  vector TEXT NOT NULL DEFAULT '',
  embedding_model TEXT NOT NULL DEFAULT '',
  indexed_at TEXT NOT NULL,
  PRIMARY KEY(project_id,path)
);
CREATE TABLE IF NOT EXISTS workspace_index (
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  workspace TEXT NOT NULL,
  path TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  content TEXT NOT NULL,
  vector TEXT NOT NULL DEFAULT '',
  embedding_model TEXT NOT NULL DEFAULT '',
  indexed_at TEXT NOT NULL,
  PRIMARY KEY(project_id,workspace,path)
);
CREATE TABLE IF NOT EXISTS background_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  prompt TEXT NOT NULL,
  source_kind TEXT NOT NULL DEFAULT 'manual',
  source_ref TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'queued',
  result TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  worktree_path TEXT NOT NULL DEFAULT '',
  worktree_branch TEXT NOT NULL DEFAULT '',
  pull_request_number INTEGER NOT NULL DEFAULT 0,
  pull_request_url TEXT NOT NULL DEFAULT '',
  pull_request_state TEXT NOT NULL DEFAULT '',
  parent_task_id INTEGER REFERENCES background_tasks(id) ON DELETE SET NULL,
  depends_on TEXT NOT NULL DEFAULT '[]',
  agent_role TEXT NOT NULL DEFAULT 'worker',
  integration_path TEXT NOT NULL DEFAULT '',
  integration_branch TEXT NOT NULL DEFAULT '',
  integration_check_command TEXT NOT NULL DEFAULT '',
  integration_check_status TEXT NOT NULL DEFAULT '',
  integration_check_output TEXT NOT NULL DEFAULT '',
  integration_pr_number INTEGER NOT NULL DEFAULT 0,
  integration_pr_url TEXT NOT NULL DEFAULT '',
  integration_pr_state TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  started_at TEXT NOT NULL DEFAULT '',
  completed_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS swarm_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  enabled INTEGER NOT NULL DEFAULT 1,
  coordinator_profile_id INTEGER REFERENCES model_profiles(id) ON DELETE SET NULL,
  default_worker_profile_id INTEGER REFERENCES model_profiles(id) ON DELETE SET NULL,
  role_profiles TEXT NOT NULL DEFAULT '{}',
  max_agents INTEGER NOT NULL DEFAULT 6,
  max_concurrency INTEGER NOT NULL DEFAULT 3,
  max_depth INTEGER NOT NULL DEFAULT 1,
  dynamic_size INTEGER NOT NULL DEFAULT 1,
  agent_tool_budget INTEGER NOT NULL DEFAULT 30,
  coordinator_tool_budget INTEGER NOT NULL DEFAULT 20,
  require_reviewer INTEGER NOT NULL DEFAULT 1,
  require_challenger INTEGER NOT NULL DEFAULT 0,
  is_builtin INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS swarm_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  objective TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'planning',
  profile_id INTEGER REFERENCES swarm_profiles(id) ON DELETE SET NULL,
  coordinator_task_id INTEGER REFERENCES background_tasks(id) ON DELETE SET NULL,
  integration_task_id INTEGER REFERENCES background_tasks(id) ON DELETE SET NULL,
  max_agents INTEGER NOT NULL DEFAULT 6,
  max_concurrency INTEGER NOT NULL DEFAULT 3,
  total_agents_created INTEGER NOT NULL DEFAULT 0,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  started_at TEXT NOT NULL DEFAULT '',
  completed_at TEXT NOT NULL DEFAULT '',
  integration_path TEXT NOT NULL DEFAULT '',
  integration_branch TEXT NOT NULL DEFAULT '',
  integration_check_command TEXT NOT NULL DEFAULT '',
  integration_check_status TEXT NOT NULL DEFAULT '',
  integration_check_output TEXT NOT NULL DEFAULT '',
  integration_pr_number INTEGER NOT NULL DEFAULT 0,
  integration_pr_url TEXT NOT NULL DEFAULT '',
  integration_pr_state TEXT NOT NULL DEFAULT '',
  coordinator_instructions TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS swarm_coordinator_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  swarm_id INTEGER NOT NULL REFERENCES swarm_runs(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS swarm_coordinator_events_swarm ON swarm_coordinator_events(swarm_id,id);
CREATE TABLE IF NOT EXISTS swarm_blackboard (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  swarm_id INTEGER NOT NULL REFERENCES swarm_runs(id) ON DELETE CASCADE,
  task_id INTEGER REFERENCES background_tasks(id) ON DELETE SET NULL,
  category TEXT NOT NULL,
  key TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL,
  confidence REAL,
  supersedes_id INTEGER REFERENCES swarm_blackboard(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS swarm_blackboard_swarm ON swarm_blackboard(swarm_id,id);
CREATE TABLE IF NOT EXISTS project_skills (
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  skill TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(project_id,skill)
);
CREATE TABLE IF NOT EXISTS workspaces (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_projects (
  workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  PRIMARY KEY(workspace_id, project_id),
  UNIQUE(project_id)
);
CREATE TABLE IF NOT EXISTS memory_scopes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT NOT NULL,
  scope_key TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(scope, scope_key)
);
CREATE TABLE IF NOT EXISTS github_operations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  action TEXT NOT NULL,
  repository TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  head TEXT NOT NULL,
  base TEXT NOT NULL,
  command TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  output TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

ADDITIVE_COLUMNS = {
    "projects": {
        "approval_mode": "TEXT NOT NULL DEFAULT 'assisted'",
        "instructions": "TEXT NOT NULL DEFAULT ''",
        "git_author_name": "TEXT NOT NULL DEFAULT 'Olladex User'",
        "git_author_email": "TEXT NOT NULL DEFAULT 'olladex@local'",
        "model_profile_id": "INTEGER REFERENCES model_profiles(id) ON DELETE SET NULL",
    },
    "model_profiles": {"context_tokens": "INTEGER NOT NULL DEFAULT 16384","is_builtin": "INTEGER NOT NULL DEFAULT 0"},
    "messages": {"run_id": "INTEGER"},
    "sessions": {"memory": "TEXT NOT NULL DEFAULT ''","summary": "TEXT NOT NULL DEFAULT ''", "last_summarized_message_id": "INTEGER NOT NULL DEFAULT 0"},
    "file_changes": {"workspace_path": "TEXT NOT NULL DEFAULT ''","hunks": "TEXT NOT NULL DEFAULT '[]'", "applied_content": "TEXT NOT NULL DEFAULT ''", "updated_at": "TEXT NOT NULL DEFAULT ''"},
    "command_runs": {"task_id": "INTEGER", "run_id": "INTEGER", "cwd": "TEXT NOT NULL DEFAULT ''","status": "TEXT NOT NULL DEFAULT 'completed'", "updated_at": "TEXT NOT NULL DEFAULT ''"},
    "git_operations": {"remote_url": "TEXT NOT NULL DEFAULT ''"},
    "swarm_runs": {
        "integration_path": "TEXT NOT NULL DEFAULT ''",
        "integration_branch": "TEXT NOT NULL DEFAULT ''",
        "integration_check_command": "TEXT NOT NULL DEFAULT ''",
        "integration_check_status": "TEXT NOT NULL DEFAULT ''",
        "integration_check_output": "TEXT NOT NULL DEFAULT ''",
        "integration_pr_number": "INTEGER NOT NULL DEFAULT 0",
        "integration_pr_url": "TEXT NOT NULL DEFAULT ''",
        "integration_pr_state": "TEXT NOT NULL DEFAULT ''",
        "coordinator_instructions": "TEXT NOT NULL DEFAULT ''",
    },
    "background_tasks": {
        "worktree_path": "TEXT NOT NULL DEFAULT ''", "worktree_branch": "TEXT NOT NULL DEFAULT ''",
        "pull_request_number": "INTEGER NOT NULL DEFAULT 0", "pull_request_url": "TEXT NOT NULL DEFAULT ''", "pull_request_state": "TEXT NOT NULL DEFAULT ''",
        "parent_task_id": "INTEGER REFERENCES background_tasks(id) ON DELETE SET NULL", "depends_on": "TEXT NOT NULL DEFAULT '[]'", "agent_role": "TEXT NOT NULL DEFAULT 'worker'",
        "integration_path": "TEXT NOT NULL DEFAULT ''", "integration_branch": "TEXT NOT NULL DEFAULT ''",
        "integration_check_command": "TEXT NOT NULL DEFAULT ''", "integration_check_status": "TEXT NOT NULL DEFAULT ''", "integration_check_output": "TEXT NOT NULL DEFAULT ''",
        "integration_pr_number": "INTEGER NOT NULL DEFAULT 0", "integration_pr_url": "TEXT NOT NULL DEFAULT ''", "integration_pr_state": "TEXT NOT NULL DEFAULT ''",
        "swarm_id": "INTEGER REFERENCES swarm_runs(id) ON DELETE CASCADE",
        "model_profile_id": "INTEGER REFERENCES model_profiles(id) ON DELETE SET NULL",
        "assigned_model": "TEXT NOT NULL DEFAULT ''",
        "task_kind": "TEXT NOT NULL DEFAULT 'specialist'",
        "priority": "INTEGER NOT NULL DEFAULT 100",
        "depth": "INTEGER NOT NULL DEFAULT 0",
        "progress": "INTEGER NOT NULL DEFAULT 0",
        "current_activity": "TEXT NOT NULL DEFAULT ''",
    },
}


def now() -> str:
    return datetime.now(UTC).isoformat()


def init_db() -> None:
    settings.data_root.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database_path, timeout=10) as conn:
        conn.executescript(SCHEMA)
        for table, columns in ADDITIVE_COLUMNS.items():
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        stamp = now()
        defaults = [
            ("Balanced local", settings.ollama_model, settings.ollama_embedding_model, 0.2, 8, 8, 32000, 1),
            ("Fast review", settings.ollama_model, settings.ollama_embedding_model, 0.1, 6, 6, 20000, 1),
            ("Deep implementation", settings.ollama_model, settings.ollama_embedding_model, 0.15, 12, 12, 48000, 1),
        ]
        for profile in defaults:
            conn.execute("INSERT OR IGNORE INTO model_profiles(name,chat_model,embedding_model,temperature,max_steps,context_files,context_chars,is_builtin,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (*profile, stamp, stamp))
        conn.execute("UPDATE model_profiles SET is_builtin=1 WHERE name IN ('Balanced local','Fast review','Deep implementation')")
        balanced = conn.execute("SELECT id FROM model_profiles WHERE name='Balanced local'").fetchone()
        fast = conn.execute("SELECT id FROM model_profiles WHERE name='Fast review'").fetchone()
        deep = conn.execute("SELECT id FROM model_profiles WHERE name='Deep implementation'").fetchone()
        balanced_id = balanced[0] if balanced else None
        fast_id = fast[0] if fast else balanced_id
        deep_id = deep[0] if deep else balanced_id
        swarm_defaults = [
            ("Quick Review", balanced_id, fast_id, 3, 2, 1, 1, 0),
            ("Development", balanced_id, deep_id, 5, 3, 1, 1, 0),
            ("Bug Hunt", balanced_id, deep_id, 4, 3, 1, 1, 0),
            ("Deep Development", deep_id, deep_id, 8, 3, 1, 1, 1),
        ]
        for name, coordinator_id, worker_id, max_agents, max_concurrency, max_depth, reviewer, challenger in swarm_defaults:
            conn.execute(
                "INSERT OR IGNORE INTO swarm_profiles(name,coordinator_profile_id,default_worker_profile_id,max_agents,max_concurrency,max_depth,require_reviewer,require_challenger,is_builtin,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,1,?,?)",
                (name, coordinator_id, worker_id, max_agents, max_concurrency, max_depth, reviewer, challenger, stamp, stamp),
            )
        conn.execute("UPDATE swarm_profiles SET is_builtin=1 WHERE name IN ('Quick Review','Development','Bug Hunt','Deep Development')")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.database_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def rows(cursor: sqlite3.Cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


def decode_json(value: str | None, fallback=None):
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return [] if fallback is None else fallback
