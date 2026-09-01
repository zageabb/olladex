# Olladex v0.2.0

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
- PTY-backed local `/bin/bash` terminal with live output, cancellation, history, timeouts and destructive-command blocks.
- Review, Assisted and Autonomous command-approval modes.
- Git branch, working-tree status, recent commits and staged/unstaged diff view.
- Project instructions automatically supplied to the Ollama agent.
- Repository intelligence covering languages, frameworks, scripts and detected symbols.
- Mermaid and Graphviz/DOT live editors with SVG preview and export.
- DOCX, XLSX, PPTX and PDF inspection.
- Create basic Word documents, Excel workbooks and PowerPoint presentations.
- Responsive Context Studio-style three-pane interface.

## Architecture

```text
Browser / Next.js (port 5081)
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

## v0.2 limitations

- Olladex is currently a local web application with a desktop-style interface, not yet a packaged native desktop binary.
- The terminal streams PTY output and supports cancellation, but does not yet accept interactive stdin after a command starts.
- Office editing is structured and practical, not a pixel-perfect replacement for Word, Excel or PowerPoint.
- Git commit, branch creation, push and pull actions are not yet exposed in the interface.
- Repository symbols use lightweight language-aware pattern extraction; tree-sitter and semantic ranking are later context-engine work.

## Next release direction

v0.3 should focus on controlled Git write actions, interactive terminal input, tree-sitter symbol indexing, ranked context assembly, session summarisation and native desktop packaging.
