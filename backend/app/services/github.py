from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess

from . import git
from .workspace import project_root


def repository_slug(project: dict, remote: str = "origin") -> str:
    code, url = git._git(project, "remote", "get-url", remote)
    if code:
        raise ValueError(url.strip() or f"Could not resolve Git remote: {remote}")
    value = url.strip()
    patterns = (
        r"^https?://github\.com/([^/]+/[^/]+?)(?:\.git)?$",
        r"^git@github\.com:([^/]+/[^/]+?)(?:\.git)?$",
        r"^ssh://git@github\.com/([^/]+/[^/]+?)(?:\.git)?$",
    )
    for pattern in patterns:
        match = re.match(pattern, value)
        if match:
            return match.group(1)
    raise ValueError("The selected repository does not have a supported GitHub origin remote")


def _gh(project: dict, args: list[str], timeout: int = 45) -> tuple[int, str]:
    if not shutil.which("gh"):
        return 127, "GitHub CLI (gh) is not installed"
    completed = subprocess.run(
        ["gh", *args], cwd=project_root(project), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, check=False,
    )
    return completed.returncode, completed.stdout


def status(project: dict) -> dict:
    try:
        slug = repository_slug(project)
    except ValueError as exc:
        return {"available": False, "authenticated": False, "repository": "", "error": str(exc)}
    if not shutil.which("gh"):
        return {"available": False, "authenticated": False, "repository": slug, "error": "Install GitHub CLI to enable issue and pull-request workflows"}
    code, output = _gh(project, ["auth", "status", "--hostname", "github.com"])
    return {"available": True, "authenticated": code == 0, "repository": slug, "error": "" if code == 0 else output.strip()[-1000:]}


def issues(project: dict) -> list[dict]:
    slug = repository_slug(project)
    code, output = _gh(project, ["issue", "list", "--repo", slug, "--state", "open", "--limit", "50", "--json", "number,title,body,url,labels,updatedAt"])
    if code:
        raise ValueError(output.strip() or "Could not list GitHub issues")
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError("GitHub CLI returned invalid issue data") from exc


def issue(project: dict, number: int) -> dict:
    slug = repository_slug(project)
    code, output = _gh(project, ["issue", "view", str(number), "--repo", slug, "--json", "number,title,body,url,labels"])
    if code:
        raise ValueError(output.strip() or f"Could not load GitHub issue #{number}")
    return json.loads(output)


def prepare_pull_request(project: dict, title: str, body: str, base: str) -> dict:
    slug = repository_slug(project)
    summary = git.summary(project)
    head = summary.get("branch", "")
    if not head or head == "detached":
        raise ValueError("Create or switch to a named branch before opening a pull request")
    git.validate_branch(project, base)
    args = ["pr", "create", "--repo", slug, "--title", title, "--body", body, "--base", base, "--head", head]
    return {"action": "create_pr", "repository": slug, "title": title, "body": body, "head": head, "base": base, "args": args, "command": shlex.join(["gh", *args])}


def execute_pull_request(project: dict, operation: dict) -> dict:
    prepared = prepare_pull_request(project, operation["title"], operation["body"], operation["base"])
    for field in ("repository", "head", "base", "command"):
        if prepared[field] != operation[field]:
            raise ValueError("The pull-request operation changed after approval; prepare it again")
    code, output = _gh(project, prepared["args"], timeout=90)
    if code:
        raise ValueError(output.strip() or "GitHub pull-request creation failed")
    return {"output": output.strip(), "url": next((part for part in output.split() if part.startswith("https://")), "")}
