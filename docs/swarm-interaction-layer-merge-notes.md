# Swarm + Interaction Layer Merge Notes

This note tracks compatibility between:

- PR #7: `feature/swarm-v0.7`
- PR #8: `interaction-layer-v1-phase1`

The branches intentionally develop independently. They currently overlap in only three files:

```text
backend/app/database.py
backend/app/main.py
frontend/app/page.tsx
```

## backend/app/database.py

Preserve **both** sets of additive schema changes.

From Swarm:

- `swarm_profiles`
- `swarm_runs`
- `swarm_coordinator_events`
- `swarm_blackboard`
- `project_skills`
- additive Swarm fields on `background_tasks`
- built-in Swarm profile seeding

From Interaction Layer:

- `workspaces`
- `workspace_projects`
- `memory_scopes`
- any related indexes / additive columns

These schemas are complementary. Do not resolve the merge by selecting one file wholesale.

## backend/app/main.py

Preserve Interaction Layer workspace/memory endpoints and chat-memory composition.

Also preserve Swarm lifecycle hooks:

```python
from .services import swarm_coordinator
swarm_coordinator.start_active()
```

during application startup, and:

```python
from .services import swarm_coordinator
swarm_coordinator.shutdown()
```

during shutdown.

Swarm API routing is registered separately and should remain enabled.

The Interaction Layer's scoped memory context should remain authoritative for normal chat context. Swarm specialist/coordinator execution continues to use its own task/runtime context and Blackboard.

## frontend/app/page.tsx

Treat PR #8 as the presentation authority.

Do **not** resolve this file by replacing the Interaction Layer shell with the older Swarm presentation from PR #7.

The preferred integration path is for the Interaction Layer Agent Board / task presentation to consume the stable backend contract:

```text
GET /api/swarms/{swarm_id}/board
```

The response includes:

- durable Swarm state;
- agents and task dependencies;
- summary counts/progress/integration readiness;
- incremental agent events;
- incremental Coordinator events;
- incremental Blackboard entries;
- next cursor values.

Cursor parameters:

```text
after_event
after_coordinator_event
after_blackboard
limit
```

The Interaction Layer should own rendering. The Swarm backend remains responsible for orchestration, concurrency, models, worktrees, Coordinator decisions, recovery, helper agents, review gating and integration.

## Recommended Merge Order

1. Finish and validate both draft PRs independently.
2. Merge/rebase the Interaction Layer presentation first if it is ready.
3. Rebase Swarm onto the resulting `main`.
4. Resolve `database.py` by combining both additive schemas.
5. Resolve `main.py` by combining workspace/memory behavior with Swarm lifecycle hooks.
6. Let the Interaction Layer version of `page.tsx` win, then connect its Agent Board to the Swarm board API.
7. Run full backend, frontend, browser and desktop CI.
8. Dogfood a real local-Ollama swarm before promoting the Swarm PR from draft.

## Important Boundary

Avoid duplicating Swarm orchestration inside the Interaction Layer.

The UI may normalize or present task phases differently, but execution truth should remain in the Swarm backend.
