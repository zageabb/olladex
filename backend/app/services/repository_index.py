from __future__ import annotations

import json
import os
import time
from pathlib import Path

from ..database import connect, now
from .context_engine import Embedder, cosine, tokens
from .workspace import IGNORED, TEXT_SUFFIXES, project_root


SKIP_NAMES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock"}
_embedding_failures: dict[tuple[int, str], float] = {}


def _files(project: dict):
    root = project_root(project)
    for base, dirs, files in os.walk(root):
        dirs[:] = [directory for directory in dirs if directory not in IGNORED]
        for name in files:
            path = Path(base) / name
            if name in SKIP_NAMES or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size <= 500_000:
                yield path.relative_to(root).as_posix(), path, stat


def refresh(project: dict, embedder: Embedder | None = None, embedding_model: str = "") -> dict:
    project_id = int(project["id"])
    with connect() as conn:
        existing = {row["path"]: dict(row) for row in conn.execute("SELECT * FROM repository_index WHERE project_id=?", (project_id,))}
    seen: set[str] = set()
    changed = 0
    stamp = now()
    with connect() as conn:
        for relative, path, stat in _files(project):
            seen.add(relative)
            previous = existing.get(relative)
            if previous and previous["size"] == stat.st_size and previous["mtime_ns"] == stat.st_mtime_ns:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")[:120_000]
            except OSError:
                continue
            conn.execute(
                "INSERT INTO repository_index(project_id,path,size,mtime_ns,content,vector,embedding_model,indexed_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project_id,path) DO UPDATE SET size=excluded.size,mtime_ns=excluded.mtime_ns,content=excluded.content,vector='',embedding_model='',indexed_at=excluded.indexed_at",
                (project_id, relative, stat.st_size, stat.st_mtime_ns, content, "", "", stamp),
            )
            changed += 1
        removed = [path for path in existing if path not in seen]
        for relative in removed:
            conn.execute("DELETE FROM repository_index WHERE project_id=? AND path=?", (project_id, relative))

    embedded = 0
    failure_key = (project_id, embedding_model)
    last_failure = _embedding_failures.get(failure_key)
    can_embed = bool(embedder and embedding_model and (last_failure is None or time.monotonic() - last_failure > 300))
    if can_embed:
        with connect() as conn:
            pending = [dict(row) for row in conn.execute("SELECT path,content FROM repository_index WHERE project_id=? AND (vector='' OR embedding_model!=?) ORDER BY path LIMIT 500", (project_id, embedding_model))]
        try:
            for offset in range(0, len(pending), 16):
                batch = pending[offset:offset + 16]
                vectors = embedder([f"{item['path']}\n{item['content'][:8000]}" for item in batch])
                if len(vectors) != len(batch):
                    raise ValueError("Incomplete embedding batch")
                with connect() as conn:
                    for item, vector in zip(batch, vectors):
                        conn.execute("UPDATE repository_index SET vector=?,embedding_model=?,indexed_at=? WHERE project_id=? AND path=?", (json.dumps(vector), embedding_model, now(), project_id, item["path"]))
                        embedded += 1
            _embedding_failures.pop(failure_key, None)
        except Exception:
            _embedding_failures[failure_key] = time.monotonic()

    return {**status(project), "changed": changed, "removed": len(existing.keys() - seen), "embedded_now": embedded}


def status(project: dict) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS files,SUM(CASE WHEN vector!='' THEN 1 ELSE 0 END) AS embedded,MAX(indexed_at) AS updated_at FROM repository_index WHERE project_id=?", (project["id"],)).fetchone()
    return {"files": row["files"] or 0, "embedded": row["embedded"] or 0, "updated_at": row["updated_at"]}


def ranked_context(project: dict, query: str, embedder: Embedder | None = None, embedding_model: str = "", max_files: int = 8, max_chars: int = 32_000) -> list[dict]:
    refresh(project, embedder=embedder, embedding_model=embedding_model)
    terms = tokens(query)
    if not terms:
        return []
    with connect() as conn:
        records = [dict(row) for row in conn.execute("SELECT path,content,vector,embedding_model FROM repository_index WHERE project_id=?", (project["id"],))]
    query_vector = None
    if embedder and any(item["vector"] and item["embedding_model"] == embedding_model for item in records):
        try:
            query_vector = embedder([query])[0]
        except Exception:
            query_vector = None
    ranked = []
    for item in records:
        lower_path = item["path"].lower()
        lower_content = item["content"].lower()
        lexical = sum(12 for term in terms if term in lower_path) + sum(min(8, lower_content.count(term)) for term in terms)
        semantic = 0.0
        if query_vector and item["vector"] and item["embedding_model"] == embedding_model:
            try:
                semantic = max(0.0, cosine(query_vector, json.loads(item["vector"])))
            except (TypeError, json.JSONDecodeError):
                semantic = 0.0
        lines = item["content"].splitlines()
        first = next((index for index, line in enumerate(lines) if any(term in line.lower() for term in terms)), 0)
        start = max(0, first - 8)
        ranked.append({"path": item["path"], "lexical_score": float(lexical), "semantic_score": semantic, "start_line": start + 1, "excerpt": "\n".join(lines[start:start + 38])})
    maximum_lexical = max((item["lexical_score"] for item in ranked), default=0.0) or 1.0
    hybrid = query_vector is not None
    for item in ranked:
        item["score"] = item["lexical_score"] / maximum_lexical * 0.65 + item["semantic_score"] * 0.35 if hybrid else item["lexical_score"]
        item["strategy"] = "indexed-hybrid" if hybrid else "indexed-lexical"
    ranked = [item for item in ranked if item["score"] > 0]
    ranked.sort(key=lambda item: (-item["score"], len(item["path"]), item["path"]))
    result = []
    used = 0
    for item in ranked:
        remaining = max_chars - used
        if remaining <= 0:
            break
        excerpt = item["excerpt"][:remaining]
        result.append({**item, "score": round(item["score"], 4), "semantic_score": round(item["semantic_score"], 4), "excerpt": excerpt})
        used += len(excerpt)
        if len(result) >= max_files:
            break
    return result
