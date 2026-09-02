from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from ..config import settings
from . import git


def repository(project: dict) -> tuple[str, str]:
    remotes = git.summary(project).get("remotes", [])
    remote = next((item for item in remotes if item["name"] == "origin"), remotes[0] if remotes else None)
    if not remote:
        raise ValueError("This repository has no Git remote")
    url = remote["url"]
    match = re.match(r"git@[^:]+:([^/]+)/(.+?)(?:\.git)?$", url)
    if match:
        return match.group(1), re.sub(r"\.git$", "", match.group(2))
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("The Git remote is not a recognised GitHub repository")
    return parts[-2], re.sub(r"\.git$", "", parts[-1])


def _client() -> httpx.Client:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return httpx.Client(base_url=settings.github_api_url.rstrip("/"), headers=headers, timeout=httpx.Timeout(20, connect=5))


def _request(method: str, path: str, **kwargs) -> dict | list:
    try:
        with _client() as client:
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.json().get("message", exc.response.text) if exc.response.content else str(exc)
        raise ValueError(f"GitHub returned {exc.response.status_code}: {detail}") from exc
    except httpx.HTTPError as exc:
        raise ValueError(f"Could not reach GitHub: {exc}") from exc


def overview(project: dict) -> dict:
    owner, repo = repository(project)
    issues_data = _request("GET", f"/repos/{owner}/{repo}/issues", params={"state": "open", "per_page": 30})
    pulls_data = _request("GET", f"/repos/{owner}/{repo}/pulls", params={"state": "open", "per_page": 20})
    issues = [
        {"number": item["number"], "title": item["title"], "body": item.get("body") or "", "url": item["html_url"], "labels": [label["name"] for label in item.get("labels", [])]}
        for item in issues_data if "pull_request" not in item
    ]
    pulls = [
        {"number": item["number"], "title": item["title"], "url": item["html_url"], "head": item["head"]["ref"], "base": item["base"]["ref"], "draft": item.get("draft", False)}
        for item in pulls_data
    ]
    return {"repository": f"{owner}/{repo}", "authenticated": bool(settings.github_token), "issues": issues, "pull_requests": pulls}


def issue(project: dict, number: int) -> dict:
    owner, repo = repository(project)
    item = _request("GET", f"/repos/{owner}/{repo}/issues/{number}")
    if "pull_request" in item:
        raise ValueError("That number identifies a pull request, not an issue")
    return {"repository": f"{owner}/{repo}", "number": item["number"], "title": item["title"], "body": item.get("body") or "", "url": item["html_url"]}


def create_pull_request(project: dict, operation: dict) -> dict:
    owner, repo = repository(project)
    if f"{owner}/{repo}" != operation["repository"]:
        raise ValueError("The GitHub repository changed after this pull request was proposed")
    if not settings.github_token:
        raise ValueError("Set OLLADEX_GITHUB_TOKEN before creating a pull request")
    result = _request("POST", f"/repos/{owner}/{repo}/pulls", json={"title": operation["title"], "body": operation["body"], "head": operation["head"], "base": operation["base"], "draft": bool(operation["draft"])})
    return {"number": result["number"], "url": result["html_url"], "state": result["state"], "title": result["title"]}
