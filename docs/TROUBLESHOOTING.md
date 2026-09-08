# Olladex Troubleshooting

**Scope:** Olladex v0.8.1 `main`  
**Purpose:** diagnose common startup, Ollama, repository, Git, terminal, task, Office and desktop failures

Use this guide from the top of the relevant symptom rather than changing multiple settings at once.

---

## 1. General diagnostic rule

When Olladex reports a failure:

1. identify which layer failed: browser, API, Ollama, repository, shell/Git, task runtime or desktop shell;
2. reproduce with the smallest action possible;
3. read the exact status/error shown by the relevant panel;
4. verify current filesystem/Git/task state before retrying a write;
5. change one variable at a time;
6. re-run the smallest relevant check;
7. only then retry the original workflow.

Do not repeatedly approve the same failing write/command without understanding whether the previous attempt partially completed.

---

## 2. Browser asks for a connection token

### Expected behaviour

Source mode uses a bearer token. `start-local.sh` prints it to the terminal.

### Fix

1. return to the terminal that launched Olladex;
2. find:

```text
Olladex connection token (paste into the browser): ...
```

3. copy the token;
4. paste it into the Olladex authentication prompt.

### If no token is shown

Check whether you started services manually. For manual startup:

```bash
export OLLADEX_API_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
printf '%s\n' "$OLLADEX_API_TOKEN"
```

Restart the backend with that same environment variable.

---

## 3. Frontend loads but API calls fail

Symptoms may include:

- repeated authentication prompt;
- project list never loads;
- browser network errors;
- CORS error;
- `401`/`403`/connection refused.

### Check backend

```bash
curl http://127.0.0.1:8001/docs
```

If the TCP connection fails, the backend is not listening on the expected port/address.

### Check frontend API URL

Default:

```text
http://localhost:8001/api
```

If ports/host were changed, ensure `NEXT_PUBLIC_API_URL` points to the backend address visible from the browser.

### Check CORS

If the browser origin is not localhost/127.0.0.1, add the actual frontend origin to `OLLADEX_CORS_ORIGINS` and restart the backend.

Do not disable authentication to solve a CORS problem.

---

## 4. Ollama shows offline

### Check Ollama independently

On the Ollama host:

```bash
ollama list
```

From the Olladex host, confirm the Ollama HTTP endpoint is reachable using the configured server address.

### In Olladex

Open:

```text
Project → Ollama server & defaults
```

Then:

1. verify Server URL;
2. select **Test server + models**;
3. read the result;
4. only save after the intended chat model is visible.

### Common causes

- Ollama process not running;
- wrong IP/port;
- Ollama bound only to loopback on another machine;
- firewall blocks port 11434;
- model name typed incorrectly;
- DNS/hostname not resolvable.

---

## 5. Chat model is missing

Check installed models:

```bash
ollama list
```

Install/pull the intended model on the Ollama host.

Then use **Test server + models** again.

If a project selects a model profile, remember that the profile chat model can override the backend default.

---

## 6. Embedding model missing or semantic retrieval disabled

Symptom:

- Context Lens shows lexical/indexed-lexical strategy;
- semantic scores unavailable/zero;
- repository ranking still works but is less semantic.

Install the configured model:

```bash
ollama pull nomic-embed-text
```

Then:

1. test Ollama settings;
2. refresh repository index;
3. retry Context Lens query.

Olladex is designed to fall back to lexical retrieval; this is not a fatal chat failure.

---

## 7. Model returns poor/irrelevant repository answers

### Diagnose context first

Open Project → Context Lens and query the same topic.

Check:

- are relevant files ranked?
- is index stale?
- is retrieval lexical-only?
- is context file count too small?
- is context token budget too small for the repository/task?

### Recovery order

1. refresh index;
2. ensure embedding model works;
3. make the prompt more specific;
4. adjust profile context files/tokens only if necessary;
5. use a more capable chat model if reasoning/tool use remains weak.

---

## 8. Tool budget exhausted

Symptom:

```text
budget exhausted
```

This is not success.

### Fix

- simplify the task;
- split work into stages;
- increase profile Tool steps within the UI limit if the model reliably uses tools;
- use background/multi-agent tasks for naturally separable work;
- avoid very broad prompts such as “fix everything in the repo”.

---

## 9. Agent repeatedly tries the same failing tool call

Olladex contains repeated-call guards, but a model can still become stuck around a failing action.

### Recovery

1. stop the turn if it is not progressing;
2. inspect the exact error/tool result;
3. verify repository state;
4. continue with explicit guidance:

```text
The previous tool call failed because <reason>. Do not repeat it unchanged. Inspect the relevant state and choose a different safe approach.
```

If the local model consistently fails to recover from structured tool errors, use a more capable model/profile for agentic work.

---

## 10. Agent edit is proposed but file does not change

This is expected until you apply the proposal.

Open **Changes** and:

1. inspect diff/hunks;
2. select wanted hunks;
3. choose Apply.

Review-first agent editing deliberately separates proposal from repository mutation.

---

## 11. Apply fails

Common causes:

- source file changed after proposal creation;
- proposal no longer matches expected file state;
- selected hunks conflict;
- task proposal belongs to a different worktree/context.

### Recovery

1. inspect the current file/Git diff;
2. reject stale proposal if appropriate;
3. ask the agent to re-read the latest file and prepare a new proposal;
4. do not force a patch onto content it was not generated against.

---

## 12. Revert is refused

This is usually a safety feature.

Revert requires the current file to still match the known applied state. If later work changed it, blind revert could destroy that work.

### Recovery

Use:

- Git diff/history;
- `.olladex/history` backup;
- manual edit;
- new agent proposal based on current state.

---

## 13. Manual file save fails

Check:

- selected project still points to the repository;
- file still exists;
- file is text/UTF-8 compatible with the editor path;
- permissions permit the Olladex process to write;
- file has not changed externally since it was opened.

If external edits happened, reopen/refresh the file before saving to avoid overwriting newer content.

---

## 14. Repository does not appear after Open

Confirm:

- path is absolute;
- path exists on the machine running the backend;
- backend OS user can access it;
- you did not enter a path that exists only on the browser/client machine when the backend runs elsewhere.

In a LAN deployment, repository paths are always from the backend host's filesystem perspective.

---

## 15. Git controls say Git is not initialised

If the directory should be a Git repository:

```bash
git -C /path/to/repo status
```

If not initialised and you intentionally want Git:

```bash
cd /path/to/repo
git init
```

Then refresh Olladex.

Do not initialise Git in a directory merely to remove the warning if the project is not meant to be version-controlled.

---

## 16. Branch creation or checkout fails

Check native Git first:

```bash
git status
git branch --all
```

Possible causes:

- invalid branch name;
- uncommitted changes block checkout;
- branch already exists;
- repository state is mid-merge/rebase/cherry-pick;
- filesystem permission problem.

Resolve the underlying Git state before retrying through Olladex.

---

## 17. Commit button disabled

The UI requires:

- non-empty commit message;
- at least one staged change.

Stage the required files first.

Also verify project Git author name/email if commit identity is wrong.

---

## 18. Fetch/pull/push approval fails

Read the exact command and output shown in the Git operation card.

Check:

```bash
git remote -v
git status
git branch -vv
```

Typical causes:

- missing credentials;
- no upstream;
- remote branch rejected;
- non-fast-forward condition;
- network/DNS failure;
- wrong remote URL.

Olladex does not store Git credentials; fix the host Git credential/authentication configuration.

---

## 19. `gh unavailable` or GitHub panel not working

Check:

```bash
gh --version
gh auth status
```

If unauthenticated:

```bash
gh auth login
```

Also confirm the repository remote points to GitHub.

The rest of Olladex should continue to work when `gh` is unavailable.

---

## 20. GitHub issue queue action fails

Check:

- `gh` authenticated;
- issue still exists/is accessible;
- repository origin is supported;
- selected project is the intended repository;
- task queue database/service is healthy.

Then retry after refreshing the GitHub/Queue state.

---

## 21. PR creation proposal succeeds but PR is not created

Preparing a PR is only step one.

You must approve the pending exact `gh pr create` command.

If approval was attempted and failed, inspect the stored operation output and run `gh auth status`/Git branch checks.

---

## 22. Terminal says command failed to start

Check:

- command exists in PATH;
- repository working directory still exists;
- backend process user can spawn shell processes;
- on Windows, ConPTY/shell dependencies are available.

Try a simple command:

```bash
pwd
```

or on Windows shell fallback:

```text
cd
```

If even the simplest command fails, diagnose the backend terminal service/environment rather than the original command.

---

## 23. Terminal output appears stuck

If the process is interactive, it may be waiting for input.

Try:

- clicking terminal and typing expected input;
- Tab/Enter as appropriate;
- Ctrl-C;
- Stop.

For commands that intentionally run a development server, “running” is expected until you stop it.

---

## 24. Terminal command timed out

The configured command timeout may be too low for non-interactive controlled execution.

Default:

```text
OLLADEX_COMMAND_TIMEOUT_SECONDS=120
```

Increase only when justified and restart the backend.

For genuinely interactive/long-running work, use the interactive Terminal surface instead of a short command tool path.

---

## 25. Windows terminal problems

Check Python dependency:

```bash
pip show pywinpty
```

The Windows backend prefers ConPTY and can fall back to other shell execution paths.

Also verify one of the supported shells is present:

- Git Bash;
- PowerShell;
- Command Prompt.

Packaged desktop failures should also be checked against the frozen API build contents.

---

## 26. Background task remains queued

Check:

- worker count is non-zero/valid;
- other workers are not all occupied;
- task dependencies are satisfied;
- required prerequisite task has not failed/cancelled;
- backend process is running;
- Ollama is reachable.

Configuration:

```text
OLLADEX_TASK_WORKERS=3
```

A dependency-waiting task is different from a broken queue.

---

## 27. Background task remains running after Stop

Cancellation is cooperative.

The current Ollama request/tool may need to return before the worker observes cancellation.

Do not immediately delete worktrees/process data. Wait for the task state to settle, then inspect its result/error/worktree.

---

## 28. Task worktree cannot be cleaned up

Olladex refuses automatic cleanup when a managed worktree contains uncommitted changes.

### Recovery

1. inspect the task branch/worktree diff;
2. decide whether the work is valuable;
3. commit/promote it or intentionally discard it using normal Git controls;
4. only then allow cleanup.

Do not manually remove the directory first; that can leave Git worktree metadata inconsistent.

---

## 29. Downstream multi-agent task is blocked

Inspect prerequisite tasks.

A dependent task can be blocked if a prerequisite:

- failed;
- was cancelled;
- has not completed.

Fix/re-run the prerequisite or create a replacement dependency plan rather than forcing the downstream task to run without required context.

---

## 30. Multi-agent lead plan is poor

Possible causes:

- objective too vague;
- too many specialists requested;
- local model weak at structured planning;
- task naturally should be single-agent;
- dependencies not obvious from prompt.

### Recovery

- make objective more concrete;
- state hard boundaries and verification;
- reduce maximum specialist count;
- manually add specialists/dependencies;
- use a stronger chat model/profile for lead planning.

---

## 31. Integration preflight reports file overlaps

Overlap means multiple selected specialist branches touched the same path.

It does not automatically mean failure.

### Review

1. inspect each specialist branch/diff for the overlapping file;
2. determine whether edits affect different compatible sections;
3. reduce selected tasks or adjust integration order if needed;
4. build integration branch only after understanding overlap risk.

---

## 32. Integration branch creation fails on conflict

The integration workflow is designed to abort safely on cherry-pick conflict rather than alter `main`.

### Recovery

1. inspect conflicting specialist branches;
2. decide which change is authoritative;
3. resolve/rebase one specialist branch or create a focused integration-fix task;
4. rerun preflight/integration;
5. run full combined checks.

---

## 33. Push integration / Create final PR disabled

The v0.8.1 UI gates these actions on passing combined checks.

Run checks and obtain a passing status first.

If your repository uses a different validation command, change the command field before running checks.

---

## 34. Office file inspection fails

Check:

- extension matches file type;
- file exists inside project;
- file is not corrupt;
- required Python Office library installed;
- file size is within applicable limits;
- password/encryption is not preventing the library from opening it.

Try opening the file in its native Office application to confirm it is structurally valid.

---

## 35. Office creation fails

Check:

- target path is repository-relative and valid;
- target directory exists or service supports creating it;
- Olladex process can write;
- requested extension matches selected kind;
- content/data format is valid.

For Excel basic creation, remember the UI interprets each line as comma-separated row data.

---

## 36. Rich Word/Excel/PowerPoint editor controls are missing

If you are on v0.8.1 `main`, this is expected.

Word Studio, Spreadsheet Studio and Presentation Studio exist on Office expansion branches and are not part of the released/current `main` UI.

See `OFFICE_EXPANSION.md` before switching/merging branches.

---

## 37. Diagram preview shows an error

For Mermaid:

- check diagram syntax;
- avoid unsupported directives/features;
- start from a small valid diagram and add nodes gradually.

For DOT:

- check braces/semicolons/quoted strings;
- ensure the source is valid Graphviz DOT.

The preview error is local; invalid diagram source does not damage repository files unless you separately save bad source.

---

## 38. Export SVG button disabled

The button is enabled only when a valid SVG preview exists.

Fix the diagram render error first.

---

## 39. Desktop app does not start

Run source layers separately to isolate the problem:

```bash
.venv/bin/python -m pytest -q
npm --prefix frontend run build
```

Then try:

```bash
npm --prefix desktop install
npm --prefix desktop start
```

Possible causes:

- Node version too old;
- backend Python dependencies missing;
- frontend build failed;
- Electron dependency installation issue;
- packaged sidecar missing/cannot execute;
- OS security/quarantine restriction.

---

## 40. `npm: command not found`

Confirm Node/npm installation:

```bash
node --version
npm --version
```

Olladex requires Node 22+ for the documented development baseline.

On systems with multiple Node installations, ensure the shell launching `start-local.sh`/`start-desktop.sh` has the intended Node/npm in PATH.

---

## 41. Python virtual environment problems

Check:

```bash
python3 --version
.venv/bin/python --version
```

If the virtual environment was created with an incompatible/broken Python installation, recreate it:

```bash
rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
```

Only do this when no local virtualenv-specific work needs preserving.

---

## 42. Frontend build fails

Run:

```bash
npm --prefix frontend install
npm --prefix frontend run lint
npm --prefix frontend run build
```

Fix the first TypeScript/build error rather than retrying packaging repeatedly.

---

## 43. Backend tests fail

Run with enough output to identify the first failing test:

```bash
.venv/bin/python -m pytest
```

For Git/worktree tests, ensure Git is installed and temporary directories can be created.

For Windows-specific terminal tests, verify `pywinpty`/shell environment.

---

## 44. Desktop installer build fails

Run stages independently:

```bash
npm --prefix desktop run build:api
npm --prefix desktop run prepare:app
npm --prefix desktop run dist
```

This identifies whether the failure belongs to:

- API freezing;
- frontend preparation;
- electron-builder packaging/signing.

Signing errors should not be diagnosed as core application build errors.

---

## 45. Desktop update check fails

Check:

- packaged build has correct repository metadata;
- network can reach GitHub releases;
- requested release exists;
- version metadata is consistent;
- for a private source, token is supplied in desktop process environment.

v0.8.1 metadata targets:

```text
zageabb/olladex
```

---

## 46. Version shown in UI looks wrong

The header uses the live backend version.

Check:

```text
backend/app/__init__.py
frontend/package.json
desktop/package.json
```

For a release, these should be deliberately reconciled.

Do not trust old prose in README/release notes over the running backend version when diagnosing the installed application.

---

## 47. SQLite/database problems

Default database:

```text
./data/olladex.sqlite3
```

Before destructive recovery:

1. stop Olladex;
2. make a backup copy of the data directory;
3. identify whether error is migration, corruption or permission-related;
4. preserve repository files/worktrees separately.

Do not delete the database as a first troubleshooting step if chat/task history matters.

---

## 48. Large repository feels slow

Potential costs:

- initial repository indexing;
- embedding generation;
- large context candidate set;
- multiple concurrent task workers;
- local Ollama model throughput.

Improve in this order:

1. use incremental index rather than repeatedly rebuilding;
2. verify embedding cache is working;
3. reduce model/profile context files if excessive;
4. reduce task-worker concurrency if Ollama is saturated;
5. use an appropriately sized model for the hardware.

---

## 49. Security incident / suspicious command

If an unexpected command executed or a repository changed unexpectedly:

1. stop active agent/task processes;
2. switch project to Review mode;
3. inspect terminal/tool activity;
4. inspect Git diff/status in main and task worktrees;
5. preserve logs/data before cleanup;
6. rotate any credentials that may have been exposed to the process/command;
7. use Git/history backups to recover files;
8. review the prompt/model/tool path that authorised the action before resuming Autonomous/Assisted mode.

Remember: the shell runs with host OS permissions and is not a security sandbox.

---

## 50. Minimum information for a useful bug report

Include:

- Olladex version;
- source vs desktop build;
- OS;
- Python version;
- Node/npm version;
- Ollama URL type (local/network, without secrets);
- chat model and embedding model;
- project approval mode;
- exact UI action;
- exact error/status text;
- relevant backend/terminal output;
- whether issue reproduces in a fresh chat/project;
- whether repository is Git and whether task was in a worktree;
- smallest reproducible sequence;
- relevant test result.

Do not include API tokens, GitHub tokens, passwords or private repository content that is unnecessary to reproduce the issue.
