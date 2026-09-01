# Olladex v0.1.0

**Local AI development agent for Ollama**  
*Code locally. Build autonomously.*

Olladex is a Codex-style, repository-first development workspace powered by models running through Ollama. It combines a conversational coding agent with visible repository tools, local Bash, Git diffs, Mermaid and Graphviz/DOT diagrams, and practical Office-file workflows.

The v0.1 interface follows the navy, blue, white and split-workspace design language established in Context Studio while focusing specifically on software-development work.

## v0.1 capabilities

- Open and persist local repositories.
- Connect to local or network-hosted Ollama and discover installed models.
- Persistent projects, task sessions, messages and activity records in SQLite.
- Bounded Ollama tool loop with visible tool activity.
- Repository tree, UTF-8 file viewer/editor and text/code search.
- Project-scoped file writes with unified diffs and `.olladex/history` backups.
- Local `/bin/bash` terminal with command history, timeouts and initial destructive-command blocks.
- Git branch, working-tree status, recent commits and staged/unstaged diff view.
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

Olladex resolves every agent file path against the selected repository and rejects traversal outside it. File writes retain the previous version under `.olladex/history`. Bash commands run with the same operating-system permissions as the Olladex process; an initial blocklist rejects obvious disk/system destruction, but v0.1 is intended for a trusted local machine or trusted LAN only. Do not expose it directly to the public Internet.

## v0.1 limitations

- The first release is a local web application with a desktop-style interface, not yet a packaged native desktop binary.
- Long-running commands return after completion rather than using a full interactive PTY stream.
- Office editing is structured and practical, not a pixel-perfect replacement for Word, Excel or PowerPoint.
- The agent applies workspace-scoped file edits directly and records their diffs; per-hunk approval and revert controls are planned next.
- Git commit, branch creation, push and pull actions are not yet exposed in the interface.
- Repository symbol indexing and semantic search are later context-engine work.

## Next release direction

v0.2 should focus on review-first file change proposals, per-hunk accept/reject/revert, true PTY streaming and cancellation, project instruction files, and a richer repository map before adding more integrations.
