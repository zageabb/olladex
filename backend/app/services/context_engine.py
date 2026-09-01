from __future__ import annotations

import os
import re
from pathlib import Path

from .workspace import IGNORED, TEXT_SUFFIXES, project_root


SKIP_NAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock"}


def tokens(value: str) -> set[str]:
    return {item.lower() for item in re.findall(r"[A-Za-z_$][\w$.-]{2,}", value) if item.lower() not in {"the", "and", "for", "with", "this", "that", "from", "into", "add", "make"}}


def ranked_context(project: dict, query: str, max_files: int = 8, max_chars: int = 32_000) -> list[dict]:
    root = project_root(project)
    terms = tokens(query)
    if not terms:
        return []
    candidates: list[tuple[float, str, str]] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [directory for directory in dirs if directory not in IGNORED]
        for name in files:
            path = Path(base) / name
            if name in SKIP_NAMES or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > 500_000:
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            relative = path.relative_to(root).as_posix()
            lower_path = relative.lower()
            lower_content = content.lower()
            path_hits = sum(1 for term in terms if term in lower_path)
            content_hits = sum(min(8, lower_content.count(term)) for term in terms)
            score = path_hits * 12 + content_hits
            if score:
                candidates.append((score, relative, content))
    candidates.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    result: list[dict] = []
    used = 0
    for score, relative, content in candidates[: max_files * 3]:
        lines = content.splitlines()
        first = next((index for index, line in enumerate(lines) if any(term in line.lower() for term in terms)), 0)
        start = max(0, first - 8)
        excerpt = "\n".join(lines[start:start + 38])
        remaining = max_chars - used
        if remaining <= 0:
            break
        excerpt = excerpt[:remaining]
        result.append({"path": relative, "score": round(score, 2), "start_line": start + 1, "excerpt": excerpt})
        used += len(excerpt)
        if len(result) >= max_files:
            break
    return result


def format_context(items: list[dict]) -> str:
    if not items:
        return "No repository files were automatically selected."
    return "\n\n".join(f"### {item['path']} (score {item['score']}, from line {item['start_line']})\n```\n{item['excerpt']}\n```" for item in items)

