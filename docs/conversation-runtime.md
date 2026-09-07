# Conversation runtime

The React conversation surface reads a durable NDJSON event stream from FastAPI. Model text, plans, tool starts/results, questions, approvals and user steering share one ordered timeline. It renders user-facing model output only; Ollama thinking fields are not exposed.

## API

All `/api` requests require `Authorization: Bearer <OLLADEX_API_TOKEN>`.

- `POST /api/sessions/{id}/runs`: start a turn (`content`, optional `resume_id`). One active turn per session is enforced in SQLite.
- `GET /api/sessions/{id}/runs`: discover current and historical turns.
- `GET /api/runs/{id}/events?after=<event-id>`: replay and follow events; reconnect from the last received ID.
- `POST /api/runs/{id}/input`: steering or an answer (`content`).
- `DELETE /api/runs/{id}`: cooperative Stop; preserves completed file changes.
- `POST /api/commands/{id}/decision`: approve once or decline (`accepted`). Decisions are conditional database transitions.
- `GET/PUT /api/sessions/{id}/memory`: user-editable preferences and decisions (`content`).

The old synchronous message endpoint remains for compatibility; new clients should use runs so they can display and resolve questions and approvals.

## Persistence and recovery

`agent_runs` holds state and the model message checkpoint. `agent_events` is the append-only timeline. `agent_inputs` holds steering until the worker consumes it. `command_runs` retains the run/task identity and exact working directory. File proposals retain the exact workspace in which they were created. Existing database migrations add fields and a separate per-workspace index without deleting existing user data.

The runtime records a tool intention before dispatch and records the result after execution. A process can fail between a side effect and its result record. This is not exactly-once execution: recovery never automatically replays an uncertain call. It records an unknown outcome and asks the model to inspect the workspace. Shell commands still require approval outside Autonomous mode. Stop cancels command process groups; a synchronous filesystem write already underway may finish.

Background tasks keep their original task identity and worktree when explicitly resumed. Active/waiting worktrees cannot be removed by cleanup endpoints. Worktree indexes have independent keys, preventing concurrent branches from replacing one another's context.

## Model behavior

The prompt distinguishes conversation from action, encourages concise explanations between meaningful actions, accepts steering, and asks focused questions when needed. Tools include bounded line-range reads, validated unique-context patches, plan updates, user questions and explicitly requested memory. Interactive patches remain reviewable proposals; worktree patches apply directly. Models differ in conversational and tool-calling ability; these changes improve the transport/runtime but do not make every local model equally capable.

## Verification

Run `python -m pytest backend/tests -q -W error::pytest.PytestUnhandledThreadExceptionWarning`, then `npm --prefix frontend run build`. Install Chromium with `cd frontend && npx playwright install chromium`, then run `npm run test:e2e`.

Backend regression coverage includes authentication/origin checks, path/symlink confinement, independent indexes, cancellation deadlocks, stale-file conflict detection, streaming/replay, steering, approval in the original workspace, Stop during silent generation, patch validation and persistence before approval. Deterministic mocked Ollama transport exercises the actual agent loop without model-dependent assertions. Browser tests cover live guidance and cross-session/project response races.

The architecture continues to use worker threads and SQLite. Paused turns occupy a worker, so large-scale scheduling, OS-level sandboxing, and model-specific tokenization remain separate future work. Packaged installers need target-platform smoke testing before a release.
