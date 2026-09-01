# Olladex release notes

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
