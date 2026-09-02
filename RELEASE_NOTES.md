# Olladex release notes

## v0.8.1

Olladex v0.8.1 turns parallel task execution into a coordinated multi-agent development workflow with task-to-PR lifecycle tracking, autonomous lead-agent decomposition, dependency-aware specialists, integration worktrees and combined CI gates.

### Added

- Persistent parent/child task relationships, explicit task dependencies and specialist agent roles.
- Dependency-aware scheduling that waits for prerequisites and blocks downstream tasks when prerequisites fail or are cancelled.
- Autonomous lead-agent planning through Ollama, with bounded specialist decomposition and a final reviewer/consolidation task.
- Automatic dependency-result hand-offs to downstream specialists and the final reviewer.
- Task graph UI for autonomous leads, manual specialists, dependencies, review bundles and consolidated lead results.
- Durable task-to-pull-request linkage with PR state, review decision and status-check visibility.
- Safe automatic cleanup of merged task worktrees when no uncommitted work remains.
- Managed integration worktrees using `olladex/integration-<lead-task-id>` branches.
- Specialist branch preflight with changed-file overlap reporting.
- Conflict-safe cherry-pick integration that aborts without modifying `main`.
- Combined integration check command, push gate and single final integration pull request workflow.
- Dedicated push/PR CI workflow for backend pytest, frontend TypeScript checking and production Next.js builds.
- Temporary-Git-repository tests for worktree integration, overlap detection, combined checks and conflict aborts.
- SQLite-backed tests for dependency waiting, failed prerequisites and cross-project dependency rejection.

### Fixed

- Desktop publisher now targets `zageabb/olladex` instead of the retired `olladex-` repository slug.
- Electron release metadata now treats the repository as public.
- Frontend and desktop package metadata now report v0.8.1 instead of the older v0.6.0 line.
- Application header uses the live backend version rather than a hard-coded v0.6 label.
- Pull-request persistence fields were reconciled across task lifecycle and orchestration migrations.
- Repository embeddings no longer incorrectly enter a five-minute cooldown on a fresh process before any embedding failure has occurred.
- API assembly coverage now validates the real assembled OpenAPI contract rather than FastAPI internal router objects.

### Verification

- GitHub Actions CI run #12 passed on the release-candidate code.
- Backend: 30 tests passed under Python 3.12.
- Frontend: dependency install, strict TypeScript check and production Next.js build passed under Node 22.
- Desktop: dependency install, Electron shell syntax checks and release metadata validation passed.

## v0.8.0

Olladex v0.8 introduced isolated Git worktrees for parallel agents, pull-request review tooling and deeper Office-file inspection/generation.

### Added

- Per-task managed Git worktrees and `olladex/task-<id>` branches so agents can work concurrently in the same repository.
- Agent filesystem routing into task worktrees while ordinary API requests continue to use the main checkout.
- Task branch commit, push and pull-request promotion workflow.
- GitHub pull-request list/detail/diff review services with comments, approvals and requested changes.
- Pull-request review workspace with check/status visibility.
- Deeper DOCX, XLSX, PPTX and PDF inspection plus improved basic Office generation.
- Worktree lifecycle tests and API route assembly coverage.

### Safety

- Task proposal application/revert is routed back into the originating task worktree.
- Worktree deletion is confined to Olladex-managed directories.
- Automatic cleanup refuses worktrees that still contain uncommitted changes.

## v0.7 development line

The v0.7 development line established the parallel task runtime that v0.8 later isolated with Git worktrees.

### Added

- Configurable multi-worker background task queue with `OLLADEX_TASK_WORKERS`.
- Cooperative cancellation checks during streamed Ollama chat and before tool execution.
- Streaming Ollama `/api/chat` handling with cancellable background jobs.
- Initial safe concurrency controls before same-repository worktree isolation arrived in v0.8.

## v0.6.0

Olladex v0.6 adds persistent background development work, review-first GitHub workflows, full model-profile management and a stronger cross-platform desktop release path.

### Added

- SQLite-backed background agent queue with recovery of interrupted jobs, persistent status, results, errors and session history.
- Queue controls in the composer and a dedicated task workspace with cooperative cancellation.
- GitHub CLI status and open-issue discovery for repositories with a supported GitHub origin.
- One-click conversion of a GitHub issue into a queued Olladex implementation session.
- Pull-request proposals that show and persist the exact `gh pr create` command before separate approval.
- Editing of all model profile settings plus deletion of custom profiles and protection for built-in profiles.
- Native Windows ConPTY support through pywinpty with live input and resize, retaining a compatible pipe fallback.
- Electron update checks, download/install prompts and GitHub release metadata for packaged builds.
- Optional private-release authentication through an environment token without database storage.
- Release CI verification job, per-platform frozen API health smoke test and installer-size/type validation.

### Verification

- Twenty-one backend tests cover queued agent execution, result persistence, complete model-profile lifecycle, GitHub command approval and all previous workflows.
- Production Next.js compilation and strict TypeScript checking pass with the Queue, GitHub and updater interfaces.
- Python, Electron and workflow syntax checks pass.
- The frozen v0.6 API, standalone frontend and Linux portable bundle are exercised in the release pass.

## v0.5.0

Olladex v0.5 makes repository context persistent, upgrades the local terminal to a full ANSI surface and automates native desktop release builds.

### Added

- Incremental SQLite repository index that updates changed files, removes deleted entries and reuses cached Ollama embeddings.
- Hybrid indexed context selection with per-profile file and character budgets and a lexical fallback when embeddings are unavailable.
- Three seeded model profiles plus creation and project selection of reusable custom profiles.
- Profile controls for chat model, embedding model, temperature, maximum agent steps and context size.
- xterm-based ANSI rendering, direct keyboard streaming and exact PTY resize forwarding.
- Cross-platform API sidecar builder and GitHub Actions matrix for Linux AppImage/DEB, macOS DMG and Windows NSIS artifacts.
- Optional macOS/Windows signing and Apple notarization through repository secrets.
- Windows shell fallback through Git Bash, PowerShell or Command Prompt when packaged on Windows.
- PTY final-output draining to prevent fast commands from losing their last output bytes.

### Verification

- Seventeen backend tests cover incremental indexing, cached semantic ranking, model-profile APIs and all earlier safety, Git, Office and terminal workflows.
- The interactive PTY workflow passes repeatedly, including input, resize and final-output capture.
- Production Next.js compilation and strict TypeScript checking pass with the xterm integration.
- Python compilation, workflow parsing, frozen API health and Linux portable desktop smoke checks are included in the release pass.

## v0.4.0

Olladex v0.4 adds a real desktop distribution path and strengthens the context, terminal and Git workflows used by the local agent.

### Added

- Electron desktop shell with context isolation, sandboxing, disabled Node integration and external-navigation protection.
- PyInstaller and Electron Builder pipeline for AppImage/DEB, DMG and NSIS builds.
- OS-local desktop data storage and loopback-only desktop services.
- Hybrid context ranking using Ollama embeddings plus the existing lexical scorer.
- Automatic lexical fallback when the configured embedding model is unavailable.
- A Context Lens in the Project panel showing selected files, ranking strategy and semantic score.
- Persisted Git remote-operation proposals for fetch, fast-forward pull and push.
- Exact-command review with separate approve and reject actions before any remote Git operation runs.
- Remote/upstream and ahead/behind visibility in the Changes panel.
- PTY resize support and Ctrl-C, Tab, Escape and history shortcut controls.
- Recoverable tool-error observations and a guard against repeated identical tool calls.

### Verification

- Sixteen backend tests cover hybrid retrieval, Git remote preparation/execution, API approvals, PTY resize, recoverable tool failures and all earlier safety workflows.
- Production Next.js compilation and strict TypeScript checking pass.
- The standalone frontend and PyInstaller-frozen API both pass loopback health smoke tests.
- Electron 39 is installed and its shell scripts pass syntax validation; native packaging is exercised on Linux.

## v0.3.0

Olladex v0.3 deepens the local development loop with controlled Git writes, interactive terminal sessions and a more selective context engine.

### Added

- Create and switch branches from the Changes panel.
- Stage and unstage individual files, then commit staged work using per-project author settings.
- Send interactive input to running PTY commands and stop them without leaving the workspace.
- Tree-sitter symbol extraction for common languages with a regex fallback when a parser is unavailable.
- Lexically ranked repository excerpts selected from the current task and supplied to Ollama within a fixed context budget.
- Deterministic persistent session summaries that retain recent tasks, outcomes, tool activity and touched files.
- Session-memory UI and richer repository-map metadata showing symbol kind and parser source.
- Additive SQLite migrations for Git identity and session-summary state.

### Verification

- Twelve backend tests cover context ranking, summaries, controlled Git workflows, review-safe changes, terminal policy, repository intelligence, Office files and path confinement.
- Production Next.js compilation and strict TypeScript checking pass.
- Manual service-level smoke checks cover live PTY input, Git stage/commit/branch actions and summary persistence.

## v0.2.0

Olladex v0.2 turns the initial repository agent into a review-first development workspace.

### Added

- Agent file edits are stored as proposals instead of being written immediately.
- Unified proposals are divided into independently selectable hunks.
- Selected hunks can be applied while unselected changes remain untouched.
- Applied changes can be reverted only when the file still matches the applied version, preventing accidental overwrite of later work.
- Timestamped file history avoids replacing earlier backups.
- Bash commands run through a PTY with incremental output polling and cancellation.
- Agent commands support Review, Assisted and Autonomous approval modes.
- Assisted mode automatically permits common read-only, test and build commands while holding higher-impact commands for approval.
- Project instructions are persisted and automatically included in Ollama context.
- Repository intelligence detects languages, frameworks, test/build scripts and common Python/JavaScript/TypeScript symbols.
- A new Project panel exposes agent rules, approval mode and repository mapping.
- Additive SQLite migrations upgrade v0.1 data in place.

### Verification

- Eight backend tests cover workspace safety, Office round trips, partial-hunk changes, safe revert, terminal policy and repository intelligence.
- Production Next.js compilation and strict TypeScript checking pass.
- End-to-end API smoke coverage verifies settings, intelligence, partial apply, PTY execution and revert.

## v0.1.0

Initial local-first release with Ollama chat, repository tools, file editing, Bash, Git status/diffs, Mermaid, Graphviz/DOT and Office-file workflows.
