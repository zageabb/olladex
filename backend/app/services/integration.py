from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..config import settings
from . import worktrees
from .workspace import project_root


def _integration_root(project: dict) -> Path:
    return (settings.data_root.expanduser().resolve() / "integrations" / str(project["id"])).resolve()


def _validate_branch(branch: str) -> str:
    branch = branch.strip()
    if not branch.startswith("olladex/task-"):
        raise ValueError(f"Refusing non-task branch: {branch}")
    return branch


def changed_files(project: dict, branch: str, base: str = "main") -> list[str]:
    branch = _validate_branch(branch)
    root = project_root(project)
    code, output = worktrees._git(root, "diff", "--name-only", f"{base}...{branch}", "--", ".")
    if code:
        raise ValueError(output.strip() or f"Could not compare {branch} with {base}")
    return [line.strip() for line in output.splitlines() if line.strip()]


def preflight(project: dict, branches: list[str], base: str = "main") -> dict:
    unique = []
    for branch in branches:
        branch = _validate_branch(branch)
        if branch not in unique:
            unique.append(branch)
    if not unique:
        raise ValueError("Select at least one specialist branch")
    files_by_branch = {branch: changed_files(project, branch, base) for branch in unique}
    owners: dict[str, list[str]] = {}
    for branch, files in files_by_branch.items():
        for path in files:
            owners.setdefault(path, []).append(branch)
    overlaps = [{"path": path, "branches": branch_names} for path, branch_names in owners.items() if len(branch_names) > 1]
    return {"base": base, "branches": unique, "files_by_branch": files_by_branch, "overlaps": overlaps}


def create(project: dict, lead_task_id: int, branches: list[str], base: str = "main", namespace: str = "lead") -> dict:
    plan = preflight(project, branches, base)
    root = project_root(project)
    managed = _integration_root(project)
    managed.mkdir(parents=True, exist_ok=True)
    namespace = (namespace or "lead").strip().lower()
    if namespace not in {"lead", "swarm"}:
        raise ValueError("Unsupported integration namespace")
    path = managed / f"{namespace}-{lead_task_id}"
    branch = f"olladex/integration-{namespace}-{lead_task_id}" if namespace != "lead" else f"olladex/integration-{lead_task_id}"
    reused = False
    if path.exists():
        code, current = worktrees._git(path, "branch", "--show-current")
        if code == 0 and current.strip() == branch:
            reused = True
            code, dirty = worktrees._git(path, "status", "--porcelain")
            if code:
                raise ValueError(dirty.strip() or "Could not inspect existing integration worktree")
            if dirty.strip():
                raise ValueError("Existing integration worktree has uncommitted changes; preserving it for inspection")
        else:
            raise ValueError("Managed integration path already exists with an unexpected branch; preserving it for inspection")
    else:
        branch_exists, _ = worktrees._git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
        if branch_exists == 0:
            code, output = worktrees._git(root, "worktree", "add", str(path), branch, timeout=120)
        else:
            code, output = worktrees._git(root, "worktree", "add", "-b", branch, str(path), base, timeout=120)
        if code:
            raise ValueError(output.strip() or "Could not create integration worktree")
    applied: list[dict] = []
    skipped: list[dict] = []
    source_heads: dict[str, str] = {}
    try:
        for source_branch in plan["branches"]:
            code, source_head = worktrees._git(path, "rev-parse", source_branch)
            if code:
                raise ValueError(source_head.strip() or f"Could not resolve {source_branch}")
            source_heads[source_branch] = source_head.strip()
            code, commits = worktrees._git(path, "rev-list", "--reverse", f"{base}..{source_branch}")
            if code:
                raise ValueError(commits.strip() or f"Could not enumerate commits for {source_branch}")
            shas = [line.strip() for line in commits.splitlines() if line.strip()]
            if not shas:
                raise ValueError(f"{source_branch} has no committed changes relative to {base}")
            for sha in shas:
                present, _ = worktrees._git(path, "merge-base", "--is-ancestor", sha, "HEAD")
                if present == 0:
                    skipped.append({"branch": source_branch, "sha": sha})
                    continue
                code, output = worktrees._git(path, "cherry-pick", sha, timeout=180)
                if code:
                    worktrees._git(path, "cherry-pick", "--abort")
                    raise ValueError(f"Integration conflict while applying {source_branch} ({sha[:12]}): {output.strip()}")
                applied.append({"branch": source_branch, "sha": sha})
    except Exception:
        # Preserve the integration worktree and branch after safely aborting the current cherry-pick.
        raise
    return {"path": str(path), "branch": branch, "reused": reused, "applied": applied, "skipped": skipped, "source_heads": source_heads, **plan, **summary(project, str(path), base)}


def integration_project(project: dict, path: str) -> dict:
    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(_integration_root(project))
    except ValueError as exc:
        raise ValueError("Integration worktree is outside Olladex's managed directory") from exc
    if not target.is_dir():
        raise ValueError("Integration worktree is no longer available")
    return {**project, "path": str(target)}


def summary(project: dict, path: str, base: str = "main") -> dict:
    target_project = integration_project(project, path)
    root = project_root(target_project)
    _, branch = worktrees._git(root, "branch", "--show-current")
    _, head = worktrees._git(root, "rev-parse", "HEAD")
    _, status = worktrees._git(root, "status", "--short")
    diff_code, diff = worktrees._git(root, "diff", f"{base}...HEAD", "--", ".")
    return {
        "path": str(root), "branch": branch.strip(), "head": head.strip(), "base": base,
        "changes": [line for line in status.splitlines() if line],
        "diff": diff[-750_000:] if diff_code == 0 else "",
    }


def run_checks(project: dict, path: str, command: str) -> dict:
    command = command.strip()
    if not command:
        raise ValueError("A check command is required")
    target_project = integration_project(project, path)
    root = project_root(target_project)
    import subprocess
    completed = subprocess.run(command, cwd=root, text=True, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900, check=False)
    return {"command": command, "exit_code": completed.returncode, "output": completed.stdout[-300_000:], "passed": completed.returncode == 0}


def push(project: dict, path: str, remote: str = "origin") -> dict:
    target_project = integration_project(project, path)
    root = project_root(target_project)
    _, branch = worktrees._git(root, "branch", "--show-current")
    branch = branch.strip()
    if not branch.startswith("olladex/integration-"):
        raise ValueError("Refusing to push a non-integration branch")
    code, output = worktrees._git(root, "push", "-u", remote, branch, timeout=180)
    if code:
        raise ValueError(output.strip() or "Integration branch push failed")
    return {"branch": branch, "remote": remote, "output": output.strip()}


def expected_deliverables(objective: str) -> list[dict]:
    text = str(objective or "")
    lower = text.lower()
    deliverables: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for match in re.finditer(r"(?<![\w.-])((?:[\w.-]+/)*[\w.-]+\.(?:py|js|jsx|ts|tsx|json|md|sql|sh|yaml|yml|toml|ini|txt))(?![\w.-])", text, re.I):
        value = match.group(1).strip("./")
        key = ("path", value.lower())
        if key not in seen:
            deliverables.append({"kind": "path", "value": value, "label": value})
            seen.add(key)
    for token, label in [
        ("test", "tests"),
        ("backup", "backup support"),
    ]:
        if re.search(rf"\b{token}\w*\b", lower):
            key = ("keyword_path", token)
            if key not in seen:
                deliverables.append({"kind": "keyword_path", "value": token, "label": label})
                seen.add(key)
    if "json" in lower and re.search(r"\bpersist\w*\b", lower):
        deliverables.append({"kind": "json_persistence", "value": "json", "label": "JSON persistence"})
    return deliverables


def validate_deliverables(project: dict, path: str, objective: str) -> dict:
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        raise ValueError("Validation workspace is unavailable")
    code, tracked_output = worktrees._git(target, "ls-files")
    if code:
        raise ValueError(tracked_output.strip() or "Could not inspect tracked deliverables")
    tracked = [line.strip() for line in tracked_output.splitlines() if line.strip()]
    tracked_lower = [item.lower() for item in tracked]
    expected = expected_deliverables(objective)
    evidence: list[dict] = []
    missing: list[str] = []

    for item in expected:
        kind = item["kind"]
        value = str(item["value"]).lower()
        matches: list[str] = []
        if kind == "path":
            matches = [path for path, lower in zip(tracked, tracked_lower) if lower == value or lower.endswith("/" + value)]
        elif kind == "keyword_path":
            matches = [path for path, lower in zip(tracked, tracked_lower) if value in lower]
        elif kind == "json_persistence":
            for relative in tracked:
                candidate = target / relative
                if not candidate.is_file() or candidate.stat().st_size > 1_000_000:
                    continue
                try:
                    body = candidate.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if re.search(r"\bjson\.(?:dump|dumps|load|loads)\b", body, re.I):
                    matches.append(relative)
        if matches:
            evidence.append({"label": item["label"], "matches": matches[:20]})
        else:
            missing.append(str(item["label"]))
    return {"ok": not missing, "expected": expected, "evidence": evidence, "missing": missing}


def verify_integration_ready(project: dict, path: str, objective: str) -> dict:
    state = summary(project, path)
    if state.get("changes"):
        raise ValueError("Integration worktree has uncommitted changes")
    deliverables = validate_deliverables(project, path, objective)
    if not deliverables["ok"]:
        raise ValueError("Missing expected deliverables: " + ", ".join(deliverables["missing"]))
    return {"summary": state, "deliverables": deliverables}


def promote_to_main(project: dict, path: str, target_branch: str = "main") -> dict:
    target_branch = str(target_branch or "main").strip()
    if not target_branch:
        raise ValueError("Target branch is required")
    integration_state = summary(project, path, target_branch)
    if integration_state.get("changes"):
        raise ValueError("Integration worktree has uncommitted changes")
    integration_head = str(integration_state.get("head") or "").strip()
    if not integration_head:
        raise ValueError("Integration commit could not be resolved")

    main_root = project_root(project)
    code, top = worktrees._git(main_root, "rev-parse", "--show-toplevel")
    if code:
        raise ValueError(top.strip() or "Configured project directory is not a Git worktree")
    if Path(top.strip()).resolve() != main_root.resolve():
        raise ValueError("Configured project directory is not the repository's main worktree root")
    code, branch = worktrees._git(main_root, "branch", "--show-current")
    if code or branch.strip() != target_branch:
        raise ValueError(f"Target branch '{target_branch}' must already be checked out in the configured project worktree")
    code, dirty = worktrees._git(main_root, "status", "--porcelain")
    if code:
        raise ValueError(dirty.strip() or "Could not inspect main worktree status")
    if dirty.strip():
        raise ValueError("Main project worktree is dirty; commit or stash local changes before promotion")

    code, resolved = worktrees._git(main_root, "rev-parse", integration_head)
    if code or resolved.strip() != integration_head:
        raise ValueError("Integration commit is not available from the main repository")
    ancestor_code, _ = worktrees._git(main_root, "merge-base", "--is-ancestor", "HEAD", integration_head)
    if ancestor_code != 0:
        raise ValueError("Main has diverged from the integration branch; fast-forward promotion is not possible")

    code, output = worktrees._git(main_root, "merge", "--ff-only", integration_head, timeout=180)
    if code:
        raise ValueError(output.strip() or "Fast-forward promotion failed")
    code, promoted_head = worktrees._git(main_root, "rev-parse", "HEAD")
    if code or promoted_head.strip() != integration_head:
        raise ValueError("Promotion did not leave main at the integration commit")
    contains_code, _ = worktrees._git(main_root, "merge-base", "--is-ancestor", integration_head, "HEAD")
    if contains_code != 0:
        raise ValueError("Main does not contain the integration commit after promotion")

    return {
        "target_branch": target_branch,
        "main_path": str(main_root),
        "integration_path": str(Path(path).expanduser().resolve()),
        "integration_branch": integration_state.get("branch") or "",
        "integration_commit": integration_head,
        "main_commit": promoted_head.strip(),
        "output": output.strip(),
    }


def remove(project: dict, path: str, branch: str, force: bool = False) -> dict:
    root = project_root(project)
    target = Path(path).expanduser().resolve()
    try:
        target.relative_to(_integration_root(project))
    except ValueError as exc:
        raise ValueError("Refusing to remove an integration worktree outside Olladex's managed directory") from exc
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(target))
    code, output = worktrees._git(root, *args, timeout=120)
    if code:
        raise ValueError(output.strip() or "Could not remove integration worktree")
    if branch:
        worktrees._git(root, "branch", "-D" if force else "-d", branch)
    worktrees._git(root, "worktree", "prune")
    return {"path": str(target), "branch": branch, "removed": True}
