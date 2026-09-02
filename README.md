# Olladex v0.6.0

**Local AI development agent for Ollama**  
*Code locally. Build autonomously.*

Olladex is a Codex-style, repository-first development workspace powered by models running through Ollama. It combines a conversational coding agent with visible repository tools, local Bash, Git diffs, Mermaid and Graphviz/DOT diagrams, and practical Office-file workflows.

The interface follows the navy, blue, white and split-workspace design language established in Context Studio while focusing specifically on software-development work.

## Core capabilities

- Open and persist local repositories.
- Connect to local or network-hosted Ollama and discover installed models.
- Persistent projects, task sessions, messages and activity records in SQLite.
- Bounded Ollama tool loop with visible tool activity.
- Repository tree, UTF-8 file viewer/editor and text/code search.
- Review-first agent file proposals with selectable diff hunks, apply, reject and conflict-safe revert.
- Project-scoped manual file writes with unified diffs and timestamped `.olladex/history` backups.
- ANSI-capable xterm terminal backed by a real local PTY on Linux/macOS, with streamed keyboard input, live output, cancellation, history, resizing, timeouts and destructive-command blocks.
- Interactive terminal input for prompts and long-running processes after a PTY command starts.
- PTY resize events and shortcut controls for Ctrl-C, Tab, Escape and command history navigation.
- Review, Assisted and Autonomous command-approval modes.
- Controlled Git branch creation/switching, per-file stage/unstage, commit, status, history and staged/unstaged diff view.
- Two-step Git fetch, fast-forward pull and push proposals showing the exact command before explicit approval.
- Project instructions automatically supplied to the Ollama agent.
- Tree-sitter repository intelligence covering languages, frameworks, scripts and detected symbols, with a portable fallback parser.
- Persistent incremental repository index with hybrid lexical/Ollama-embedding ranking, cached vectors, automatic stale-file cleanup and transparent lexical fallback.
- Reusable local model profiles controlling chat model, embedding model, temperature, tool-step budget and context limits.
- Create, edit and remove custom model profiles without restarting Olladex.
- Persistent background agent queue with visible queued, running, completed, failed and cancelled states.
- Import GitHub issues into dedicated background agent sessions.
- Read open GitHub issues and pull requests from the selected repository remote.
- Review-first GitHub pull-request creation with separate proposal, approval and rejection actions.
- Persistent compact session summaries carried into future model requests.
- Mermaid and Graphviz/DOT live editors with SVG preview and export.
- DOCX, XLSX, PPTX and PDF inspection.
- Create basic Word documents, Excel workbooks and PowerPoint presentations.
- Responsive Context Studio-style three-pane interface.
- Hardened Electron desktop shell and automated Linux, macOS and Windows PyInstaller/Electron Builder release pipeline.
- Recoverable tool errors and repeated-call guards that help local models correct failed agent steps.

## Architecture

```text
Browser or Electron / Next.js (port 5081)
        |
        v
FastAPI (port 8001) ---- SQLite
        |
        +---- Ollama (configurable endpoint)
        +---- selected local repository
        +---- Bash and Git CLI
        +---- python-docx / openpyxl / python-pptx / pypdf

Mermaid and Graphviz/DOT are rendered locally in the browser.
```

## Start locally

Prerequisites:

- Python 3.11+
- Node.js 22+
- Git
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

For private GitHub issue/PR workflows, add a token to `.env`. The token is read from the environment and is never written to Olladex's database:

```bash
OLLADEX_GITHUB_TOKEN=github_pat_...
```

Public repository issues can be read without a token. Creating a pull request always requires a token and explicit in-app approval.

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

A portable Linux x64 ZIP can be built with `npm --prefix desktop run portable:linux`.

## Manual development setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
npm --prefix frontend install

OLLADEX_DATA_ROOT="$PWD/data" .venv/bin/uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8001
npm --prefix frontend run dev -- --hostname 0.0.0.0 --port 5081
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
6. Open the Diagrams tab to create Mermaid or DOT output.
7. Open an Office file from the tree or create one in the Office tab.

## Safety boundary

Olladex resolves every agent file path against the selected repository and rejects traversal outside it. Agent edits are proposals and do not touch the repository until approved. File writes retain timestamped previous versions under `.olladex/history`. Bash commands run with the same operating-system permissions as the Olladex process; approval modes and a blocklist reduce risk, but Olladex is intended for a trusted local machine or trusted LAN only. Do not expose it directly to the public Internet.

## v0.6 limitations

- Office editing is structured and practical, not a pixel-perfect replacement for Word, Excel or PowerPoint.
- Desktop installers are unsigned unless signing credentials are configured. Release builds now generate updater metadata, but the in-app updater transport is not enabled for private GitHub releases.
- Git remote commands inherit credentials already configured on the machine; Olladex does not store Git credentials.
- Repository content and embedding vectors are stored in Olladex's local SQLite data directory; the first semantic index may take time on large repositories and is capped at 500 new embeddings per refresh.
- Windows uses Git Bash when available, then PowerShell, then Command Prompt; native ConPTY screen semantics are not yet implemented.
- Session summaries are deterministic and local rather than generated by a second model call.
- Running background jobs finish their current model request before shutdown or cancellation; only queued jobs can currently be cancelled immediately.

## Next release direction

v0.7 should focus on parallel job limits, pausing running jobs, native Windows ConPTY, issue comments/status updates, authenticated private-release updates and visual browser testing.
