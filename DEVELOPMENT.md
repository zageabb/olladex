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
