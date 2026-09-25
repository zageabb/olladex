# Olladex v0.7 — Swarm Technical Specification

> Implementation status: active development on `feature/swarm-v0.7` / PR #7.
>
> Implemented in the current branch: persistent Swarm schema/profiles, per-project skill toggle, per-role local Ollama model profiles, concurrency-aware scheduling, isolated worktrees, Blackboard tools, merged live activity, agent steering, structured hand-offs, persistent reactive Coordinator with recovery and pre-review gates, Agent Board UI, SQLite concurrency hardening, Swarm integration preflight/worktree/checks/push/PR flow, backend regression tests, and Playwright coverage.
>
> Remaining polish: richer graph visualisation, deeper integration UX/status presentation, and any issues found during real local-Ollama dogfooding.

## 1. Purpose

Introduce an optional **Swarm skill** to Olladex that allows a user to give one substantial objective to a coordinating local LLM, which decomposes the objective into tasks and manages multiple specialised local LLM agents.

Every swarm agent:

- runs through Ollama only;
- has an explicitly selected model/model profile;
- receives a bounded task and tool budget;
- has its own persistent identity;
- has its own execution history;
- can work in an isolated Git worktree;
- exposes plans, progress, findings, tool actions and results live;
- can be individually stopped or steered;
- contributes structured findings to shared swarm knowledge.

The feature must remain optional. Disabling the Swarm skill must leave normal Olladex conversation and background-task behaviour unchanged.

## 2. Existing Olladex Foundation

The current code already provides much of the required foundation:

- `projects`, `sessions`, `messages`, `model_profiles`
- `background_tasks`
- `agent_runs`, `agent_events`, `agent_inputs`
- `file_changes`, `command_runs`
- repository/workspace indexes
- a worker pool in `services/task_queue.py`
- dependency-aware background tasks
- parent/child orchestration
- specialist roles
- isolated Git worktrees
- lead decomposition
- reviewer consolidation
- integration branches and combined checks

The Swarm feature should therefore **extend the existing orchestration/task/runtime model**, not introduce a parallel agent framework.

## 3. Core Architecture

```text
Project
   |
   +-- Session
         |
         +-- SwarmRun
              |
              +-- Coordinator
              +-- Task Graph
              +-- Blackboard
              +-- Specialist Agent
              |     +-- BackgroundTask
              |     +-- AgentRun
              |     +-- AgentEvents
              |     +-- Worktree
              |
              +-- Reviewer / Challenger
              +-- Integration Workspace
```

A `SwarmRun` is an orchestration container. Actual execution continues to use existing Olladex task and agent-run primitives.

## 4. Database Model

### 4.1 swarm_runs

```sql
CREATE TABLE swarm_runs (
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
    completed_at TEXT NOT NULL DEFAULT ''
);
```

Suggested states:

```text
planning
running
waiting
reviewing
integrating
completed
failed
cancelled
paused
```

### 4.2 Extend background_tasks

Add:

```sql
swarm_id INTEGER REFERENCES swarm_runs(id) ON DELETE CASCADE
model_profile_id INTEGER REFERENCES model_profiles(id) ON DELETE SET NULL
assigned_model TEXT NOT NULL DEFAULT ''
task_kind TEXT NOT NULL DEFAULT 'specialist'
priority INTEGER NOT NULL DEFAULT 100
depth INTEGER NOT NULL DEFAULT 0
progress INTEGER NOT NULL DEFAULT 0
current_activity TEXT NOT NULL DEFAULT ''
```

`assigned_model` is stored separately to preserve an audit record of the actual model used even if a profile changes later.

Suggested `task_kind` values:

```text
coordinator
architect
researcher
backend
frontend
coder
tester
reviewer
challenger
integrator
documentation
specialist
```

## 5. Swarm Profiles

```sql
CREATE TABLE swarm_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    coordinator_profile_id INTEGER,
    default_worker_profile_id INTEGER,
    role_profiles TEXT NOT NULL DEFAULT '{}',
    max_agents INTEGER NOT NULL DEFAULT 6,
    max_concurrency INTEGER NOT NULL DEFAULT 3,
    max_depth INTEGER NOT NULL DEFAULT 1,
    dynamic_size INTEGER NOT NULL DEFAULT 1,
    agent_tool_budget INTEGER NOT NULL DEFAULT 30,
    coordinator_tool_budget INTEGER NOT NULL DEFAULT 20,
    require_reviewer INTEGER NOT NULL DEFAULT 1,
    require_challenger INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

`role_profiles` maps swarm roles to existing Olladex `model_profiles`.

Example:

```json
{
  "coordinator": 4,
  "coder": 6,
  "backend": 6,
  "frontend": 6,
  "tester": 6,
  "researcher": 4,
  "reviewer": 4,
  "challenger": 4
}
```

## 6. Built-in Swarm Presets

### Quick Review
- Maximum agents: 3
- Concurrency: 2
- Researcher
- Tester
- Reviewer

### Development
- Maximum agents: 5
- Concurrency: 3
- Architect
- Backend/Coder
- Frontend/Coder
- Tester
- Reviewer

### Bug Hunt
- Maximum agents: 4
- Concurrency: 3
- Reproducer
- Investigator
- Fixer
- Tester

### Deep Development
- Maximum agents: 8
- configurable concurrency
- Architect
- Researchers
- Coders
- Tester
- Challenger
- Reviewer
- Integrator

### Custom
Fully user-defined.

## 7. Local Model Enforcement

Swarm is **Ollama local-only** for v0.7.

Role model selections must come from the configured Ollama server and should be validated against `GET /api/tags` before a swarm starts.

Example:

```text
Coordinator: phi4:14b
Coder: qwen2.5-coder:7b
Tester: qwen2.5-coder:7b
Reviewer: phi4:14b
```

A missing assigned model must block the swarm with an explicit error. Olladex must not silently substitute another model.

## 8. Maximum Agents vs Concurrency

These are separate settings.

Example:

```text
Maximum agents:      8
Maximum concurrency: 3
```

Eight specialist identities may exist while only three execute simultaneously.

## 9. Scheduler

Extend `task_queue._claim_next()`.

Current eligibility is essentially:

```text
queued + dependencies complete = claim
```

Swarm eligibility becomes:

```text
queued
+ dependencies complete
+ swarm not paused
+ swarm concurrency slot available
+ global worker available
= claim
```

Use deterministic priority ordering, for example:

```text
priority ASC
created_at ASC
```

### Per-swarm concurrency check

```sql
SELECT COUNT(*)
FROM background_tasks
WHERE swarm_id=?
AND status IN ('running','waiting_for_input','waiting_for_approval');
```

Only claim when this count is below `swarm.max_concurrency`.

## 10. Resource Scheduling

v0.7 should use concurrency slots rather than trying to predict VRAM.

Later, Olladex can inspect `GET /api/ps` and add model-weighted scheduling.

Initial rule:

```text
1 running agent = 1 concurrency slot
```

## 11. Dynamic Agent Creation

Default:

```text
Dynamic swarm = ON
```

`max_agents` is a ceiling, not a target.

Only the Coordinator may create new agents. Specialists can request extra help but cannot directly spawn child agents.

Initial recursion limit:

```text
max_depth = 1
```

That permits Coordinator -> Specialist but prevents uncontrolled recursive agent creation.

## 12. Coordinator Protocol

The Coordinator should produce structured task plans.

Example:

```json
{
  "summary": "Authentication handling spans middleware, session storage and API tests.",
  "tasks": [
    {
      "client_id": "A",
      "title": "Trace authentication flow",
      "role": "researcher",
      "objective": "Map the current authentication and session flow.",
      "depends_on": [],
      "write_access": false
    },
    {
      "client_id": "B",
      "title": "Inspect authentication tests",
      "role": "tester",
      "objective": "Identify current test coverage and reproduce the reported issue.",
      "depends_on": [],
      "write_access": false
    },
    {
      "client_id": "C",
      "title": "Implement correction",
      "role": "backend",
      "objective": "Implement the minimal fix using findings from A and B.",
      "depends_on": ["A", "B"],
      "write_access": true
    }
  ]
}
```

The backend maps temporary task IDs to real database IDs.

## 13. Coordinator Responsibilities

The Coordinator should:

1. understand the objective;
2. inspect repository intelligence;
3. create the smallest useful task graph;
4. avoid duplicated work;
5. monitor task outcomes;
6. add specialists only when justified;
7. update swarm state;
8. identify blockers;
9. ensure testing occurs;
10. trigger review/challenge;
11. prepare integration recommendations;
12. produce the final user-facing summary.

The Coordinator should normally delegate code changes rather than edit files directly.

## 14. Shared Blackboard

```sql
CREATE TABLE swarm_blackboard (
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
```

Recommended categories:

```text
fact
finding
decision
question
answer
risk
file
interface
test_result
dependency
assumption
recommendation
```

The Blackboard is the shared memory layer between agents. Agents should consume structured findings rather than full peer conversations.

## 15. Blackboard API and Tools

Proposed endpoints:

```text
GET  /api/swarms/{id}/blackboard
POST /api/swarms/{id}/blackboard
GET  /api/swarms/{id}/blackboard?category=finding
GET  /api/swarms/{id}/blackboard?task_id=123
```

Proposed agent tools:

```text
swarm_read_blackboard
swarm_publish_finding
swarm_publish_decision
swarm_publish_risk
swarm_request_help
```

## 16. Agent-to-Agent Communication

Do not implement unrestricted peer-to-peer conversations.

Preferred path:

```text
Agent -> Blackboard / Coordinator
```

This keeps context size controlled and prevents unproductive multi-agent chatter.

## 17. Agent Observability

Every specialist should execute through existing durable runtime primitives:

```text
agent_runs
agent_events
```

Important event kinds:

```text
status
progress
plan
assistant_start
text_delta
assistant_end
tool_start
tool_result
finding
decision
risk
blocker
handoff
file_change
test_result
command
question
answer
completed
failed
```

## 18. Visible Reasoning / Work Journal

The UI should not depend on raw hidden Ollama thinking fields.

Instead, agents should emit explicit engineering journal events:

```text
PLAN
Trace request authentication from API middleware to session loading.

ACTION
Search repository for verify_token.

RESULT
8 matches.

FINDING
Session lookup occurs before JWT validation.

DECISION
Inspect session caching before modifying middleware.

RISK
Changing validation order may alter 404 vs 401 behaviour.
```

This provides an auditable record of what an agent is doing without relying on internal chain-of-thought.

## 19. Work Journal Protocol

Specialist prompts should require:

- `PLAN` before a meaningful group of actions;
- `FINDING` when an important fact is established;
- `DECISION` when choosing between meaningful approaches;
- `RISK` for uncertainty or danger;
- `BLOCKER` when unable to proceed;
- `HANDOFF` at completion.

These should map to structured `agent_events`.

## 20. Swarm UI

Add a new rail entry:

```text
Agent
Files
Terminal
Diagrams
Office
Queue
Swarm
Project
```

It should only be active when the Swarm skill is enabled.

### Dashboard

Display:

- swarm title/status;
- Coordinator model;
- number of agents created vs maximum;
- running count vs concurrency;
- completed/failed counts;
- progress;
- pause/stop controls;
- message-to-Coordinator action.

### Task Graph

Visualise dependencies and states:

```text
waiting
ready
running
blocked
review
complete
failed
```

### Agent Cards

Each card should display:

- role;
- assigned model;
- task;
- current activity;
- latest finding;
- tool usage / budget;
- progress;
- worktree/branch;
- Open / Message / Stop actions.

### Individual Agent View

Sections:

- overview;
- live activity timeline;
- files changed;
- terminal activity;
- findings;
- task dependencies;
- worktree details.

## 21. User Steering

Add:

```text
POST /api/swarm-agents/{task_id}/input
```

Reuse the existing `agent_inputs` mechanism so the user can guide a running agent at its next safe iteration.

Optionally allow:

```text
Apply to all agents
```

which publishes a swarm-level decision.

## 22. Pause / Resume / Stop

Endpoints:

```text
POST /api/swarms/{id}/pause
POST /api/swarms/{id}/resume
DELETE /api/swarms/{id}
```

Pause:
- prevents new tasks from being claimed;
- allows running activity to reach a safe boundary;
- preserves state and worktrees.

Stop:
- sets swarm cancellation;
- requests cancellation of running specialists;
- cancels pending tasks;
- preserves completed worktrees, Blackboard and history.

## 23. Specialist Prompts

### Coding specialist

```text
You are a coding specialist in an Olladex swarm.

Your responsibility is ONLY the assigned task.
Do not broaden the objective unnecessarily.
Inspect evidence before modifying code.
Work inside your isolated worktree.
Run relevant checks.
Publish important findings to the swarm Blackboard.
Do not assume work done by another agent unless it is present
in your dependency hand-off or Blackboard.
```

### Tester

```text
You are the testing specialist.

Attempt to reproduce the reported behaviour first.
Do not modify production code unless explicitly authorised.
Create or improve tests where useful.
Report failing tests accurately.
```

### Reviewer

```text
You are the independent reviewer.

Do not assume the implementation is correct.
Inspect the actual changes and verification evidence.
Identify regressions, omissions and unsupported claims.
```

## 24. Challenger Role

Add `challenger`.

Its purpose is to try to disprove the proposed solution by looking for:

- regressions;
- race conditions;
- invalid assumptions;
- security issues;
- incomplete tests;
- API incompatibilities;
- error paths;
- edge cases.

For complex swarms:

```text
Build -> Test -> Challenge -> Correct if needed -> Review
```

## 25. Worktree Model

Reuse existing worktree infrastructure.

Suggested logical layout:

```text
.olladex/
    worktrees/
        swarm-17/
            agent-41/
            agent-42/
            agent-43/
            agent-44/
            integration/
```

Coding specialists get isolated branches/worktrees. Non-writing agents should also use deterministic repository state where practical.

## 26. Dependency Inheritance

Keep the existing ability for dependent tasks to inherit completed dependency branches.

For multiple dependencies, perform merge/preflight before execution. If they cannot be combined safely, mark the dependent task `BLOCKED` and notify the Coordinator.

Do not silently resolve conflicts without recording them.

## 27. Integration

Keep the current integration workflow and enhance it for Swarm:

- select completed specialist branches;
- overlap preflight;
- integration worktree;
- combined checks;
- integration push;
- final PR.

Target lifecycle:

```text
Specialists
  -> Tester
  -> Challenger
  -> Reviewer
  -> Coordinator selection
  -> Integration preflight
  -> Integration worktree
  -> Combined checks
  -> User review / autonomous policy
  -> Final branch / PR
```

## 28. Model Settings UI

Under:

```text
Settings
  -> Skills
       -> Swarm
```

provide:

```text
Enable Swarm                     [x]
Default preset                   Development
Maximum agents                   6
Maximum concurrent agents        3
Dynamic swarm size               [x]

Coordinator                      phi4:14b
Default worker                   qwen2.5-coder:7b

Role overrides
Architect                        phi4:14b
Backend                          qwen2.5-coder:7b
Frontend                         qwen2.5-coder:7b
Tester                           qwen2.5-coder:7b
Researcher                       phi4:14b
Reviewer                         phi4:14b
Challenger                       phi4:14b

Require final reviewer           [x]
Enable challenger                [ ]

Agent tool budget                30
Coordinator tool budget          20
```

Model dropdowns should come from the configured Ollama server.

## 29. Skill Toggle

A generic project-skill store is recommended:

```sql
CREATE TABLE project_skills (
    project_id INTEGER NOT NULL,
    skill TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(project_id, skill)
);
```

Initial Swarm state should be disabled for existing projects to preserve behaviour.

## 30. API Specification

### Swarms

```text
POST /api/projects/{project_id}/swarms
GET  /api/projects/{project_id}/swarms
GET  /api/swarms/{swarm_id}
DELETE /api/swarms/{swarm_id}
POST /api/swarms/{swarm_id}/pause
POST /api/swarms/{swarm_id}/resume
```

### Agents

```text
GET  /api/swarms/{id}/agents
GET  /api/swarm-agents/{task_id}
POST /api/swarm-agents/{task_id}/input
DELETE /api/swarm-agents/{task_id}
```

Agent response should include:

```json
{
  "task_id": 73,
  "role": "backend",
  "model": "qwen2.5-coder:7b",
  "status": "running",
  "progress": 45,
  "current_activity": "Inspecting authentication middleware",
  "run_id": 191,
  "worktree_branch": "olladex/task-73",
  "tool_usage": 17,
  "tool_budget": 30
}
```

## 31. Swarm Event Streaming

Add a swarm-wide stream:

```text
GET /api/swarms/{id}/events?after=...
```

Envelope:

```json
{
  "id": 992,
  "swarm_id": 17,
  "task_id": 73,
  "run_id": 191,
  "kind": "finding",
  "payload": {
    "message": "..."
  }
}
```

The existing per-run stream remains available for the detailed agent view.

## 32. Progress

Do not ask the LLM to invent overall completion percentages.

Derive coarse progress from task states, for example:

```text
queued      0%
running    50%
review     80%
completed 100%
```

Individual task progress can later be derived from explicit plan-step completion.

## 33. Failure Handling

### Worker failure

Coordinator receives an `AGENT_FAILED` event and may decide to:

- retry;
- replace;
- replan;
- continue without the task.

Retries should create a new run history rather than erasing the original failure.

### Ollama unavailable

Pause new claims and show a waiting state. Do not immediately fail queued tasks.

### Missing model

Block the role before execution.

### Tool budget exhausted

Use `budget_exhausted`; Coordinator decides whether to allocate a new run/budget.

## 34. Global Swarm Budgets

Recommended initial controls:

```text
Maximum agents             8
Maximum concurrency        3
Maximum total tool calls   200
Maximum retries            2
Maximum task depth         1
```

Later additions may include elapsed runtime, token budgets and GPU thresholds.

## 35. Security / Permissions

Swarm must preserve existing Olladex safety semantics.

- interactive change handling still follows Review / Assisted / Autonomous modes;
- specialist writes occur in isolated worktrees;
- final integration remains subject to existing approval policy;
- shell commands continue to use current command controls;
- no agent gains filesystem access outside the selected repository merely by being in a swarm.

## 36. Development File Map

Likely existing files to modify:

```text
backend/app/database.py
backend/app/config.py
backend/app/orchestration_routes.py
backend/app/task_routes.py
backend/app/settings_routes.py

backend/app/services/task_queue.py
backend/app/services/orchestration.py
backend/app/services/ollama.py
backend/app/services/conversation_runtime.py
backend/app/services/worktrees.py
backend/app/services/integration.py

frontend/app/page.tsx
frontend/components/TaskOrchestrationPanel.tsx
```

Suggested new backend modules:

```text
backend/app/swarm_routes.py
backend/app/services/swarm.py
backend/app/services/swarm_scheduler.py
backend/app/services/swarm_blackboard.py
backend/app/services/swarm_profiles.py
```

Suggested new frontend modules:

```text
frontend/components/SwarmPanel.tsx
frontend/components/SwarmAgentCard.tsx
frontend/components/SwarmAgentView.tsx
frontend/components/SwarmGraph.tsx
frontend/components/SwarmBlackboard.tsx
frontend/components/SwarmSettings.tsx
frontend/components/SwarmPanel.module.css
```

## 37. Migration Strategy

All schema changes should be additive.

Existing non-swarm tasks should simply have:

```text
swarm_id = NULL
```

Use the current additive-column migration pattern for `background_tasks` and `CREATE TABLE IF NOT EXISTS` for new tables.

## 38. Testing Requirements

### Scheduler
- max concurrency;
- dependencies;
- dependency failure;
- paused swarms;
- cancellation;
- dynamic agent creation;
- no over-capacity claims.

### Models
- role profile lookup;
- missing model detection;
- assigned-model audit;
- no silent fallback.

### Blackboard
- scoped reads;
- task attribution;
- categories;
- concurrent writes.

### Runtime
- every specialist has an `agent_run`;
- event replay;
- reconnect;
- steering;
- stop;
- application restart/interruption.

### Worktrees
- agents cannot modify main workspace;
- dependency branch inheritance;
- conflict detection;
- integration branch correctness.

### UI / Playwright
- create swarm;
- view task graph;
- open running agent;
- watch event stream;
- steer agent;
- stop agent;
- pause/resume swarm;
- inspect Blackboard;
- integration flow.

## 39. Implementation Phases

### Phase 1 — Swarm Data Foundation
- `swarm_runs`
- `swarm_profiles`
- `swarm_id`
- per-task model assignment
- skill enable/disable
- APIs
- migrations

### Phase 2 — Scheduler
- max swarm size
- max concurrency
- pause/resume
- priority
- model validation
- swarm cancellation

### Phase 3 — Agent Runtime Visibility
Ensure every background specialist has `agent_run` + `agent_events`, and add structured finding/decision/risk/blocker/handoff events.

This should happen before making the system more autonomous because observability is a core requirement.

### Phase 4 — Blackboard
- persistence
- agent tools
- Coordinator access
- UI/filtering

### Phase 5 — Persistent Coordinator
Move beyond the current one-shot decomposition flow.

Current:

```text
decompose once -> specialists -> reviewer
```

Target:

```text
plan
-> spawn
-> observe
-> react
-> replan
-> add specialists if justified
-> review
-> integrate
```

### Phase 6 — Swarm Dashboard
- agent cards
- graph
- live state
- models
- budgets
- current activity
- timelines
- controls

### Phase 7 — Reviewer and Challenger
Introduce explicit independent verification roles.

### Phase 8 — Integration Automation
Connect existing integration features into the swarm lifecycle and expose readiness/conflict/check states.

## 40. Product-Level View

Do not immediately replace the existing orchestration UI.

Keep the layers:

```text
SWARM
High-level autonomous orchestration

ORCHESTRATION
Detailed/manual task graph control

QUEUE
Individual background jobs
```

All three share the same underlying task/runtime/worktree infrastructure.

## 41. Recommended v0.7 Scope

Ship:

- Swarm skill toggle
- Swarm profiles
- per-role local model selection
- dynamic maximum agent count
- independent concurrency limit
- persistent Coordinator
- specialist task graph
- isolated worktrees
- durable per-agent runs/events
- live agent dashboard
- visible plans/actions/findings
- Blackboard
- agent steering
- pause/stop
- Tester
- Reviewer
- optional Challenger
- integration worktree
- combined checks

Defer:

- arbitrary recursive swarms
- unrestricted peer-to-peer agent chat
- GPU/VRAM-aware scheduling
- remote/cloud workers
- multiple Ollama servers per swarm
- direct agent-created-agent recursion

## 42. Core Design Principle

**Swarm should orchestrate existing Olladex agents, event streams, task queues and worktrees rather than create a second execution architecture.**

That keeps the feature understandable, recoverable and maintainable while turning Olladex into a visible, controllable local multi-agent software-engineering environment.


## 43. Interaction Layer Integration Contract

The parallel Interaction Layer branch should treat Swarm execution as a backend capability and consume stable Swarm APIs rather than reimplement orchestration logic in the UI.

Preferred board endpoint:

```text
GET /api/swarms/{swarm_id}/board
```

Cursor parameters:

```text
after_event
after_coordinator_event
after_blackboard
limit
```

The response contains:

- `swarm`: durable Swarm state and agent list;
- `summary`: total/active/completed/failed counts, concurrency, overall progress and integration readiness;
- `events`: incremental agent events;
- `coordinator_events`: incremental Coordinator decisions/status/budget events;
- `blackboard`: incremental shared knowledge entries;
- `cursors`: the next `event`, `coordinator_event` and `blackboard` cursor values to send on the next poll.

The Interaction Layer should own presentation of this data. The Swarm backend remains responsible for:

- model/profile resolution;
- agent spawning and concurrency;
- dependency handling;
- worktree isolation;
- Blackboard persistence;
- Coordinator decisions and budgets;
- recovery/follow-up/helper agents;
- review gating;
- integration readiness and integration execution.

This separation is intentional so the Interaction Layer can evolve independently without creating a second orchestration implementation.
