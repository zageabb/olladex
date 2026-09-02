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


def _json_output(code: int, output: str, fallback: str) -> object:
    if code:
        raise ValueError(output.strip() or fallback)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise ValueError("GitHub CLI returned invalid JSON data") from exc


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
    return _json_output(code, output, "Could not list GitHub issues")  # type: ignore[return-value]


def issue(project: dict, number: int) -> dict:
    slug = repository_slug(project)
    code, output = _gh(project, ["issue", "view", str(number), "--repo", slug, "--json", "number,title,body,url,labels"])
    return _json_output(code, output, f"Could not load GitHub issue #{number}")  # type: ignore[return-value]


def pull_requests(project: dict, state: str = "open") -> list[dict]:
    if state not in {"open", "closed", "merged", "all"}:
        raise ValueError("Unsupported pull-request state")
    slug = repository_slug(project)
    args = ["pr", "list", "--repo", slug, "--limit", "50", "--json", "number,title,url,state,isDraft,author,headRefName,baseRefName,updatedAt,reviewDecision,statusCheckRollup"]
    if state != "all":
        args.extend(["--state", state])
    code, output = _gh(project, args)
    return _json_output(code, output, "Could not list GitHub pull requests")  # type: ignore[return-value]


def pull_request(project: dict, number: int) -> dict:
    slug = repository_slug(project)
    fields = "number,title,body,url,state,isDraft,author,headRefName,baseRefName,mergeable,reviewDecision,reviews,comments,files,commits,statusCheckRollup"
    code, output = _gh(project, ["pr", "view", str(number), "--repo", slug, "--json", fields], timeout=60)
    return _json_output(code, output, f"Could not load GitHub pull request #{number}")  # type: ignore[return-value]


def pull_request_diff(project: dict, number: int) -> str:
    slug = repository_slug(project)
    code, output = _gh(project, ["pr", "diff", str(number), "--repo", slug], timeout=90)
    if code:
        raise ValueError(output.strip() or f"Could not load diff for pull request #{number}")
    return output[-750_000:]


def add_pull_request_comment(project: dict, number: int, body: str) -> dict:
    slug = repository_slug(project)
    if not body.strip():
        raise ValueError("Comment cannot be empty")
    code, output = _gh(project, ["pr", "comment", str(number), "--repo", slug, "--body", body], timeout=60)
    if code:
        raise ValueError(output.strip() or f"Could not comment on pull request #{number}")
    return {"number": number, "repository": slug, "output": output.strip()}


def submit_pull_request_review(project: dict, number: int, event: str, body: str = "") -> dict:
    slug = repository_slug(project)
    event_map = {"approve": "--approve", "comment": "--comment", "request-changes": "--request-changes"}
    flag = event_map.get(event)
    if not flag:
        raise ValueError("Unsupported review action")
    args = ["pr", "review", str(number), "--repo", slug, flag]
    if body.strip():
        args.extend(["--body", body])
    elif event in {"comment", "request-changes"}:
        raise ValueError("A review body is required for comments and requested changes")
    code, output = _gh(project, args, timeout=60)
    if code:
        raise ValueError(output.strip() or f"Could not review pull request #{number}")
    return {"number": number, "repository": slug, "action": event, "output": output.strip()}


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
