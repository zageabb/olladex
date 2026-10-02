# Development Status

Last reviewed: 2026-10-02
Current development state: ACTIVE

## Purpose

This file is the repository-level source of truth for planned development and **evidence of completion**. It is intended to be readable by both the user and AI coding agents.

Existing project-specific roadmaps, TODO files, release notes and stage documents remain valid. They provide detail and history; this file provides the common cross-repository completion standard.

## Current objective

Advanced orchestration reliability, truthful completion, approval handling, budget recovery, parallel-agent execution and user-visible evidence.

## Existing planning and evidence sources

- `README.md`
- `RELEASE_NOTES.md`
- `docs/swarm-v0.7-technical-spec.md`
- `GitHub pull requests`
- `GitHub Actions`

## Status values

- 🔵 **PLANNED** — agreed or captured, not started.
- 🔨 **IN PROGRESS** — implementation has started but completion evidence is incomplete.
- 🚫 **BLOCKED** — cannot progress until a dependency or decision is resolved.
- ⏳ **AWAITING ACCEPTANCE** — development evidence is complete but an external/user/business acceptance step remains.
- ✅ **COMPLETE** — implementation and all applicable evidence checks have been verified.
- 💤 **DEFERRED** — intentionally postponed.

## Evidence standard

A development item MUST NOT be marked **COMPLETE** solely because an AI agent, developer or document says that it is complete.

Before using COMPLETE, verify all applicable evidence:

1. the requested implementation exists in the repository;
2. the expected files actually changed;
3. a non-empty diff or equivalent implementation evidence exists;
4. tests for the behaviour exist, or a reason for no test is recorded;
5. relevant tests pass;
6. CI passes where CI exists;
7. commit and/or pull-request evidence is recorded;
8. the change is merged into the intended branch when merge is required;
9. user/business/external acceptance is recorded separately from development completion.

If required evidence is missing, use **IN PROGRESS**, **BLOCKED** or **AWAITING ACCEPTANCE** instead.

For coding work, an empty final response, no write/edit operation, unchanged branch HEAD, empty branch diff and no requested validation are explicit evidence that the task is **not complete**.

## Development ledger

### DEV-000 — Establish evidence-based development ledger

Status: ✅ COMPLETE  
Requirement: Give the user and AI agents one persistent place to see planned work, completion state and the evidence supporting completion.

Implementation:
- Added this `DEVELOPMENT.md`.
- Added/updated `AGENTS.md` so AI agents must read and maintain this ledger.
- Existing project-specific planning documents remain in place.

Evidence:
- Files: `DEVELOPMENT.md`, `AGENTS.md`
- Commit: recorded by GitHub history for this change.
- Tests: documentation/process change; no runtime test required.
- CI: not required to establish the ledger itself.
- User acceptance: requested directly on 2026-10-02.

Completion criteria:
- [x] Common status vocabulary defined.
- [x] Completion evidence rules defined.
- [x] False-completion rule defined.
- [x] Existing planning sources referenced.
- [x] AI maintenance rule added.


### DEV-001 — Verified Development & Persistent Project State

Status: 🔨 IN PROGRESS  
Priority: High  
Target: v0.8 — Verified Development & Persistent Project State  
Owner/Agent: Advanced orchestration development  
Branch: `feature/swarm-v0.7`  
Depends on: existing task queue, agent runtime, worktree and integration services  
Can run in parallel with: UI polish that does not alter orchestration state semantics  
Integration status: isolated development branch; CI-backed implementation evidence exists but merge/post-merge verification is outstanding

Requirement:
Turn the development workflow proven through ChatGPT and Olladex usage into native Olladex behaviour so the user does not need to repeatedly prompt agents to read project state, continue correctly, prove completion, recover from failed work, or verify CI and merges.

The workflow should treat repository evidence and persistent project state as authoritative. Agent claims, UI status messages, or successful CI alone must never be sufficient evidence that a feature is complete.

Primary goals:
- make `DEVELOPMENT.md` the live project-development state and current-objective source;
- make `AGENTS.md` the persistent behavioural contract for coding agents;
- make completion an evidence-based decision performed by Olladex rather than an agent self-report;
- allow development to resume from repository state instead of depending on chat history;
- give the user short, repeatable development actions such as continue, verify, recover, review and merge;
- support safe autonomous and parallel development without weakening validation standards.

Planned workstreams:

#### 1. Persistent development state
- Read `DEVELOPMENT.md` and `AGENTS.md` automatically when development work starts or resumes.
- Resolve the current objective, highest-priority incomplete item, dependencies, branch ownership and integration state.
- Prefer repository state over conversational memory when the two disagree.
- Keep `DEVELOPMENT.md` synchronised during the same development pass as implementation changes.
- Add a state refresh/synchronisation action so stale documentation can be reconciled against Git, tests and CI.

#### 2. Evidence-based completion engine
A coding task must not become COMPLETE solely because an agent returns a final response.

Collect and verify applicable evidence including:
- expected files changed;
- meaningful diff exists;
- write/edit tools were actually used where coding was required;
- branch HEAD changed from its starting point where a code change was expected;
- requested behaviour exists in the implementation;
- relevant tests were added or updated, or a reason for no test is recorded;
- relevant tests pass;
- build/lint/type-check/migration validation passes where applicable;
- CI passes where applicable;
- commit/PR evidence exists;
- required integration or merge occurred;
- post-merge verification confirms the expected change exists on the intended branch;
- acceptance criteria are checked independently of CI.

Explicit incomplete/no-progress indicators include:
- empty final response;
- no write/edit operation for a coding task;
- unchanged branch HEAD;
- empty branch diff;
- no requested validation;
- budget exhaustion before acceptance criteria are satisfied.

Budget exhaustion must return INCOMPLETE/BLOCKED with:
- work completed;
- work remaining;
- blocker or reason for exhaustion;
- recommended additional budget;
- safest continuation point.

#### 3. Development actions / commands
Provide structured development actions, initially callable from chat and later suitable for UI controls:

- `/status` — read repository and development state and report exactly where work stands.
- `/continue` — continue the highest-priority incomplete item in the current objective.
- `/verify` — independently prove whether claimed work is complete.
- `/evidence` — show implementation, validation, Git and acceptance evidence.
- `/ci` — inspect CI, resolve underlying failures, run relevant local validation, push and recheck.
- `/review` — review the current diff against the objective and acceptance criteria.
- `/recover` — reanalyse stalled, failed or repeatedly patched work from first principles.
- `/next` — identify the next highest-value incomplete development item.
- `/merge` — perform pre-merge validation, merge when clean, then verify the target branch.
- `/sync-state` — reconcile `DEVELOPMENT.md` with actual repository, Git, tests and CI state.

These should trigger structured orchestration behaviour rather than merely inserting prompt text.

#### 4. Development modes
Add explicit development modes so the user can control behaviour without restating long instructions:

- **Explore** — discuss ideas and architecture; no code changes.
- **Plan** — inspect repository/reuse opportunities and update development state.
- **Build** — implement the current objective.
- **Autonomous** — continue until the objective is verified complete, genuinely blocked, requires a material product decision, or risks destructive changes.
- **Verify** — independently inspect evidence and acceptance criteria.
- **Recover** — perform root-cause analysis and continuation planning for stalled/failed work.
- **Release** — pre-merge review, validation, merge/tag/release and post-merge verification.

#### 5. Autonomous-development rules
When intent is clear, agents should make reasonable implementation decisions without repeatedly asking the user about low-level choices.

Autonomous work should stop only when:
1. the current objective is verified complete;
2. a genuinely ambiguous product decision materially affects behaviour;
3. progress is blocked by an external dependency;
4. continuing would risk destructive or unsafe changes.

Completing one implementation sub-step is not sufficient reason to stop if the current objective remains incomplete.

#### 6. Root-cause and recovery behaviour
- After two unsuccessful fixes to the same underlying problem, stop symptom-patching and require root-cause analysis before another code change.
- Recovery must inspect the actual failure, relevant history, current diff, tests and runtime evidence.
- Preserve enough state that a different agent can continue safely.
- A recovery task inherits the original acceptance criteria unless they are explicitly changed.

#### 7. Parallel-agent ownership
Before spawning parallel work:
- split only genuinely independent tasks;
- give each agent a concrete deliverable and acceptance criteria;
- record file/module/subsystem ownership where practical;
- check that another active agent does not already own the same area;
- record dependencies and integration responsibility;
- do not represent sequential dependency chains as parallel execution.

Each parallel child retains its own evidence and validation requirements.

#### 8. Scope and discovery handling
- Stay within the current objective.
- Fix newly discovered issues immediately only when they block the objective or are clearly low-risk and tightly related.
- Record unrelated improvements, technical debt and product ideas as follow-up items rather than silently expanding scope.
- Reuse proven existing patterns/modules before introducing duplicate architecture.
- When borrowing from another repository, reuse behaviour and proven implementation where appropriate rather than blindly copying code.

#### 9. CI, acceptance and merge gates
Treat these as separate gates:

```text
Implementation evidence
        ↓
Local validation
        ↓
CI
        ↓
Acceptance verification
        ↓
Pre-merge review
        ↓
Merge
        ↓
Post-merge verification
        ↓
Development state update
```

Green CI does not by itself prove feature completion.

Pre-merge review should check:
- complete diff against the original objective;
- no unintended debug/temporary files;
- no committed secrets;
- tests/build/validation;
- migration/deployment implications;
- documentation accuracy;
- acceptance criteria.

Post-merge verification should confirm the expected commit/change exists on the intended branch and record the resulting commit SHA.

#### 10. User-visible completion report
The final verification view should clearly separate implementation, behaviour, validation and acceptance evidence.

Example successful result:

```text
Feature: LLM Knowledge Pricing

Implementation
✓ source files changed
✓ meaningful diff exists
✓ commit created

Behaviour
✓ requested workflow exercised
✓ expected output produced

Validation
✓ tests passed
✓ production build passed
✓ CI passed

Acceptance criteria
✓ 6 / 6

VERIFIED COMPLETE
```

Example false-completion result:

```text
Task claimed complete

Verification
✗ no file-writing tools used
✗ branch HEAD unchanged
✗ branch diff empty
✗ no tests run
✗ acceptance criteria not demonstrated

Result: INCOMPLETE
```

Implementation:
- False-completion validation now rejects implementation tasks that return without durable repository changes.
- Requested validation is tracked separately; changed code without requested validation becomes recoverable `incomplete`, not complete.
- Completion evidence records starting/final branch heads and auto-commit SHA.
- Reviewer evidence is invalidated if a specialist branch changes after task completion.
- Integration records specialist branch heads at preparation time and blocks promotion if those heads later change.
- Budget exhaustion, no-progress and incomplete states remain recoverable, with retry limits and user override/abandon controls.
- Recovery can restart dependent work automatically after a recovered prerequisite completes.
- This development ledger and AGENTS.md are now present on the active development branch.

Evidence:
- Commit: latest verified implementation before this ledger sync: `4cce4891643ead5d233d6aa87c8362b6696f81fc`
- Files: `backend/app/services/task_queue.py`, `backend/app/services/swarm_finalization.py`, `backend/app/services/integration.py`, `backend/app/services/swarm_coordinator.py`, `backend/app/swarm_routes.py`, orchestration/recovery tests, `AGENTS.md`, `DEVELOPMENT.md`
- Tests: backend regression coverage includes false completion, tester exemptions, no-progress, requested validation, recovery lifecycle, stale reviewer evidence and stale integration detection.
- CI: GitHub Actions CI #478 passed on `4cce4891643ead5d233d6aa87c8362b6696f81fc`.
- PR: existing Swarm/Advanced orchestration development line; final merge evidence still outstanding.
- Merged to intended branch: no — active work remains on `feature/swarm-v0.7`.
- User/business acceptance: not yet complete; current objective remains in progress.

Completion criteria:
- [ ] Olladex automatically reads `AGENTS.md` and `DEVELOPMENT.md` for development orchestration.
- [ ] Current objective and next incomplete work can be reconstructed from repository state.
- [ ] Structured development actions/commands are implemented.
- [ ] Development modes are implemented and user-visible.
- [ ] Completion engine verifies repository/Git/write/test/CI evidence rather than trusting agent status.
- [ ] CI and feature acceptance are independent gates.
- [ ] Budget exhaustion cannot result in COMPLETE.
- [ ] Repeated failed fixes invoke root-cause/recovery behaviour.
- [ ] Parallel agents receive explicit ownership, deliverables and acceptance criteria.
- [ ] Unrelated discoveries are captured without uncontrolled scope expansion.
- [ ] Pre-merge verification compares the complete change with the original objective.
- [ ] Post-merge verification confirms the intended branch contains the expected change.
- [ ] `DEVELOPMENT.md` is updated from actual evidence before the development pass finishes.
- [ ] Automated tests cover false completion, no-progress, budget exhaustion, recovery, parallel ownership and post-merge verification.
- [ ] CI passes for the completed implementation.
- [ ] User can see a concise evidence report explaining why a task is COMPLETE or INCOMPLETE.

Notes:
This item formalises the development method currently being used successfully with ChatGPT and turns it into repeatable Olladex orchestration behaviour. It extends the existing Advanced orchestration reliability work rather than replacing it.


## New development item template

Copy this section for every meaningful feature, bug fix or development idea.

### DEV-XXX — Short title

Status: 🔵 PLANNED  
Priority: Medium

Requirement:
Describe what the user actually asked for and the intended outcome.

Implementation:
Record what was changed. Leave blank until implementation starts.

Evidence:
- Commit:
- PR:
- Files:
- Tests:
- CI:
- Merged to intended branch:
- User/business acceptance:

Completion criteria:
- [ ] Implementation exists.
- [ ] Relevant files changed.
- [ ] Tests added/updated, or reason recorded.
- [ ] Relevant tests pass.
- [ ] CI passes where applicable.
- [ ] Commit/PR evidence recorded.
- [ ] Merged where required.
- [ ] External/user acceptance separated from development completion.

Notes:
Record limitations, decisions and follow-up work.

## Parallel development coordination

Use the coordination fields on every active DEV item when parallel work is possible.

- **Owner/Agent** — the person or AI agent currently responsible for the item.
- **Branch** — the working branch or worktree used for the item.
- **Depends on** — DEV items, decisions or external prerequisites that must complete first.
- **Can run in parallel with** — DEV items that are safe to develop concurrently without conflicting ownership or sequencing.
- **Integration status** — for example: not started, isolated, ready for integration, integrated, or integration blocked.

Before starting parallel work, agents should check these fields and avoid claiming the same item, branch or overlapping integration responsibility. If two items touch the same subsystem or files, record the conflict explicitly and sequence or coordinate integration rather than assuming they are independent.

Parallel execution does not weaken the completion standard: each DEV item still requires its own implementation, tests/validation, CI evidence where applicable, and integration/merge evidence before it can be marked COMPLETE.

## Maintenance rule

Update this file during the same development pass that changes the implementation. Do not postpone status updates to a later chat. When evidence and prose disagree, repository evidence wins.
