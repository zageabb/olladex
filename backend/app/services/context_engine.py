from __future__ import annotations

import math
import os
import re
from collections.abc import Callable
from pathlib import Path

from ..config import settings
from .workspace import IGNORED, TEXT_SUFFIXES, project_root


SKIP_NAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock"}
Embedder = Callable[[list[str]], list[list[float]]]


def tokens(value: str) -> set[str]:
    return {item.lower() for item in re.findall(r"[A-Za-z_$][\w$.-]{2,}", value) if item.lower() not in {"the", "and", "for", "with", "this", "that", "from", "into", "add", "make"}}


def cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0


def ranked_context(project: dict, query: str, max_files: int = 8, max_chars: int = 32_000, embedder: Embedder | None = None) -> list[dict]:
    root = project_root(project)
    terms = tokens(query)
    if not terms:
        return []
    candidates: list[dict] = []
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
            lexical = path_hits * 12 + content_hits
            lines = content.splitlines()
            first = next((index for index, line in enumerate(lines) if any(term in line.lower() for term in terms)), 0)
            start = max(0, first - 8)
            excerpt = "\n".join(lines[start:start + 38])
            candidates.append({"path": relative, "lexical_score": float(lexical), "start_line": start + 1, "excerpt": excerpt})

    candidates.sort(key=lambda item: (-item["lexical_score"], len(item["path"]), item["path"]))
    semantic_enabled = False
    semantic_pool = candidates[: max(max_files * 3, settings.context_candidate_files)]
    if embedder and semantic_pool:
        try:
            vectors = embedder([query, *[f"{item['path']}\n{item['excerpt']}" for item in semantic_pool]])
            if len(vectors) == len(semantic_pool) + 1:
                semantic_enabled = True
                for item, vector in zip(semantic_pool, vectors[1:]):
                    item["semantic_score"] = cosine(vectors[0], vector)
        except Exception:
            semantic_enabled = False

    maximum_lexical = max((item["lexical_score"] for item in candidates), default=0.0) or 1.0
    ranked = semantic_pool if semantic_enabled else [item for item in candidates if item["lexical_score"] > 0]
    for item in ranked:
        lexical_normalized = item["lexical_score"] / maximum_lexical
        semantic = max(0.0, item.get("semantic_score", 0.0))
        item["score"] = lexical_normalized * 0.65 + semantic * 0.35 if semantic_enabled else item["lexical_score"]
        item["strategy"] = "hybrid" if semantic_enabled else "lexical"
    ranked.sort(key=lambda item: (-item["score"], len(item["path"]), item["path"]))

    result: list[dict] = []
    used = 0
    for item in ranked:
        remaining = max_chars - used
        if remaining <= 0:
            break
        excerpt = item["excerpt"][:remaining]
        result.append({**item, "score": round(item["score"], 4), "semantic_score": round(item.get("semantic_score", 0.0), 4), "excerpt": excerpt})
        used += len(excerpt)
        if len(result) >= max_files:
            break
    return result


def format_context(items: list[dict]) -> str:
    if not items:
        return "No repository files were automatically selected."
    return "\n\n".join(f"### {item['path']} ({item['strategy']} score {item['score']}, from line {item['start_line']})\n```\n{item['excerpt']}\n```" for item in items)
