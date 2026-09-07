# Olladex

**Local AI development agent for Ollama**  
*Code locally. Build autonomously.*

Olladex is a Codex-style, repository-first development workspace powered by models running through Ollama. It combines a conversational coding agent with visible repository tools, local Bash, Git diffs, Mermaid and Graphviz/DOT diagrams, and practical Office-file workflows.

The interface follows the navy, blue, white and split-workspace design language established in Context Studio while focusing specifically on software-development work.

## Conversation and execution

Start with `./start-local.sh` and paste its connection token into the browser. Desktop builds connect automatically using an ephemeral token delivered through the preload bridge. The API requires bearer authentication; CORS is an additional origin check. Both development services bind to localhost.

Messages stream while the agent works. Add guidance in the composer at any time, answer inline questions, or press **Stop**. Shell approvals show the exact command and working directory. Interactive file proposals pause execution until you apply or reject them, so subsequent checks use the reviewed content. Background edits stay in their task worktree.

Turns, tool intentions/results and conversation checkpoints are stored in SQLite. Reopening a chat replays its activity and reconnects to active work. Restarted turns are marked **interrupted**, not automatically replayed. **Continue from saved context** preserves the original task workspace and tells the model to inspect uncertain tool outcomes before acting again. A tool budget limit is shown as **budget exhausted**, not success.

Use **Saved preferences and decisions** to inspect, edit or clear persistent conversation memory. The agent can also save preferences you explicitly ask it to remember. Model profiles expose a context-token budget; configure it within the selected model's supported context length. Context sizing uses a conservative character estimate, reserves output space and keeps complete tool-response groups; it is not a model-specific tokenizer.

File tools reject path escapes and skip symlink files when searching/indexing. **Shell execution is not an OS sandbox**: approved commands and Autonomous mode have your operating-system permissions. Review and Assisted modes require approval for arbitrary shell strings, including test scripts. Manually entered terminal commands are treated as explicit user instructions. Autonomous mode is an explicit trust choice.

See [runtime architecture and verification](docs/conversation-runtime.md) for endpoint details, recovery semantics and remaining limitations.

## Core capabilities

- Open and persist local repositories.
- Connect to local or network-hosted Ollama and discover installed models.
- Persistent projects, task sessions, messages and activity records in SQLite.
- Persistent background task queue with isolated worktrees and configurable worker concurrency.
- Live streamed conversation, tool activity, inline questions, steering, Stop, and resumable saved context.
- Repository tree, UTF-8 file viewer/editor and text/code search.
- Review-first agent file proposals with selectable diff hunks, apply, reject and conflict-safe revert.
- Project-scoped manual file writes with unified diffs and timestamped `.olladex/history` backups.
- ANSI-capable xterm terminal backed by a real local PTY on Linux/macOS, with streamed keyboard input, live output, cancellation, history, resizing, timeouts and destructive-command blocks.
- Interactive terminal input for prompts and long-running processes after a PTY command starts.
- PTY resize events and shortcut controls for Ctrl-C, Tab, Escape and command history navigation.
- Review, Assisted and Autonomous command-approval modes.
- Controlled Git branch creation/switching, per-file stage/unstage, commit, status, history and staged/unstaged diff view.
- Two-step Git fetch, fast-forward pull and push proposals showing the exact command before explicit approval.
- GitHub CLI integration for viewing open issues, queueing issue implementation and approval-gated pull-request creation.
- Project instructions automatically supplied to the Ollama agent.
- Tree-sitter repository intelligence covering languages, frameworks, scripts and detected symbols, with a portable fallback parser.
- Persistent incremental repository index with hybrid lexical/Ollama-embedding ranking, cached vectors, automatic stale-file cleanup and transparent lexical fallback.
- Reusable local model profiles controlling chat model, embedding model, temperature, tool-step budget and context limits.
- Create, edit and delete custom model profiles while protecting the three built-in profiles.
- Persistent compact session summaries carried into future model requests.
- Mermaid and Graphviz/DOT live editors with SVG preview and export.
- DOCX, XLSX, PPTX and PDF inspection.
- Create basic Word documents, Excel workbooks and PowerPoint presentations.
- Responsive Context Studio-style three-pane interface.
- Hardened Electron desktop shell with update checks and generated updater metadata.
- Automated Linux, macOS and Windows release pipeline with tests, frozen-API smoke checks and installer validation.
- Native Windows ConPTY terminal through pywinpty, with a pipe fallback when ConPTY is unavailable.
- Recoverable tool errors and repeated-call guards that help local models correct failed agent steps.

## Architecture

```text
Browser or Electron / Next.js (port 5081)
        |
        v
FastAPI (port 8001) ---- SQLite
        |
        +---- Ollama (configurable endpoint)
        +---- persistent background queue
        +---- selected local repository
        +---- local shell, Git and GitHub CLI
        +---- python-docx / openpyxl / python-pptx / pypdf

Mermaid and Graphviz/DOT are rendered locally in the browser.
```

## Start locally

Prerequisites:

- Python 3.11+
- Node.js 22+
- Git
- GitHub CLI (`gh`) for issue and pull-request workflows
- Ollama running locally or on your network

```bash
cp .env.example .env
# Adjust OLLADEX_OLLAMA_URL if required.
chmod +x start-local.sh
./start-local.sh
```

Open:

- Olladex: `http://localhost:5081`
- API documentation: `http://localhost:8001/docs`

The frontend and API listen on all interfaces so the app can be used on the local network. Set `NEXT_PUBLIC_API_URL` to the server's LAN address when accessing Olladex from another device, for example:

```bash
NEXT_PUBLIC_API_URL=http://192.168.1.249:8001/api ./start-local.sh
```

Install the configured embedding model to enable hybrid semantic retrieval:

```bash
ollama pull nomic-embed-text
```

If it is not installed or cannot be reached, Olladex continues with lexical ranking.

## Desktop app

Launch the desktop shell in development mode:

```bash
./start-desktop.sh
```

Build an installer for the current operating system:

```bash
npm --prefix desktop install
npm --prefix desktop run dist
```

The packaging pipeline builds the production Next.js application, freezes the FastAPI service with PyInstaller, and creates an AppImage/DEB, DMG or NSIS installer with Electron Builder. Native installers should be built on their target operating system. Tags matching `v*` also trigger `.github/workflows/release-desktop.yml`, which builds all three platforms and attaches the artifacts to a GitHub release.

macOS and Windows signing is optional. Configure `CSC_LINK` and `CSC_KEY_PASSWORD` as repository secrets; for Apple notarization also configure `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD` and `APPLE_TEAM_ID`. Unsigned artifacts are produced when those credentials are absent.

Packaged builds expose a manual update check. For private GitHub repositories, set `OLLADEX_GITHUB_TOKEN` in the desktop process environment to permit release checks. Set `OLLADEX_AUTO_UPDATE_CHECK=1` to check automatically after launch. Olladex never writes this token to its database.

A portable Linux x64 ZIP can be built with `npm --prefix desktop run portable:linux`.

## Manual development setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
npm --prefix frontend install

export OLLADEX_API_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
printf "Connection token: %s\n" "$OLLADEX_API_TOKEN"
OLLADEX_DATA_ROOT="$PWD/data" .venv/bin/uvicorn backend.app.api:app --reload --host 127.0.0.1 --port 8001
npm --prefix frontend run dev -- --hostname 127.0.0.1 --port 5081
```

Run verification:

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend run build
```

## First test workflow

1. Open a repository by entering its absolute path.
2. Create a new task.
3. Ask: `Inspect this project and explain its architecture.`
4. Ask: `Add a health endpoint, run the relevant tests and show the changes.`
5. Review agent activity, the file editor, Git diff and terminal output.
6. Use **Queue** to let another prompt run persistently in the background.
7. Connect GitHub CLI to import an issue or prepare a pull request for explicit approval.
8. Open the Diagrams tab to create Mermaid or DOT output.
9. Open an Office file from the tree or create one in the Office tab.

## Safety boundary

Olladex resolves every agent file path against the selected repository and rejects traversal outside it. Agent edits are proposals and do not touch the repository until approved. File writes retain timestamped previous versions under `.olladex/history`. Bash commands run with the same operating-system permissions as the Olladex process; approval modes and a blocklist reduce risk, but Olladex is intended for a trusted local machine or trusted LAN only. Do not expose it directly to the public Internet.

## v0.6 limitations

- Office editing is structured and practical, not a pixel-perfect replacement for Word, Excel or PowerPoint.
- Desktop installers are unsigned unless signing credentials are configured. Private-repository update checks require an environment token.
- Git remote commands inherit credentials already configured on the machine; Olladex does not store Git credentials.
- GitHub workflows require the `gh` CLI to be installed and authenticated on the local machine.
- Background tasks run serially. Cancelling a running task is cooperative and takes effect after the current Ollama request returns.
- Repository content and embedding vectors are stored in Olladex's local SQLite data directory; the first semantic index may take time on large repositories and is capped at 500 new embeddings per refresh.
- Windows prefers native ConPTY and uses Git Bash, PowerShell or Command Prompt as the command shell.
- Session summaries are deterministic and local rather than generated by a second model call.

## Next release direction

v0.7 should focus on interruptible streaming Ollama requests, parallel worktree-backed jobs, GitHub PR review/comments, a public signed update channel and deeper Office editing.
