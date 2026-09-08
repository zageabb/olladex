# Olladex documentation

This directory is the primary knowledge source for Olladex v0.8.1 and later development.

The documentation is split by audience so users can learn the application without having to read implementation notes, while administrators and developers still have a complete reference.

## Start here

- [Olladex Manual](OLLADEx_MANUAL.md) — complete user and operator manual.
- [Setup and Configuration](SETUP_AND_CONFIGURATION.md) — prerequisites, environment variables, startup scripts, desktop packaging and deployment.
- [Workflows](WORKFLOWS.md) — repeatable procedures for agent work, changes, Git/GitHub, background tasks and multi-agent orchestration.
- [Modules and Extensions](MODULES_AND_EXTENSIONS.md) — module inventory, dependencies, status and extension boundaries.
- [Office Expansion](OFFICE_EXPANSION.md) — Office editor/convergence branches and the richer Word, Excel and PowerPoint capability planned for integration.
- [Architecture and Developer Reference](ARCHITECTURE_AND_DEVELOPER_REFERENCE.md) — system architecture, data flow, security boundaries, storage, service ownership and contribution guidance.
- [Troubleshooting](TROUBLESHOOTING.md) — diagnosis and recovery for common Ollama, Node, Python, Git, terminal, task, Office and desktop problems.

## Diagram sources

Reusable source diagrams live under [`docs/diagrams`](diagrams/):

- `system-architecture.mmd`
- `review-first-change-workflow.mmd`
- `background-task-workflow.mmd`
- `github-pr-workflow.mmd`
- `multi-agent-integration.dot`

Rendered documentation illustrations live under [`docs/assets`](assets/).

## Documentation status conventions

| Label | Meaning |
|---|---|
| **Core** | Available on `main` in v0.8.1. |
| **Optional dependency** | Core feature whose full capability depends on another local tool such as `gh`, an embedding model or signing credentials. |
| **Expansion branch** | Implemented outside `main` and documented for evaluation/integration. |
| **Planned** | Direction described in repository notes but not implemented. |

When the application and documentation disagree, treat the current code on `main` as authoritative and update these documents in the same pull request as the behaviour change.

## Documentation maintenance rule

Every feature change should update at least one of the following in the same PR:

1. the main manual if users interact with it;
2. setup/configuration if installation, environment or packaging changes;
3. workflows if operator procedure changes;
4. modules/extensions if capability ownership or status changes;
5. architecture reference if APIs, storage, trust boundaries or service composition change.
