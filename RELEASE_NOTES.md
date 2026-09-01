# Olladex release notes

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

