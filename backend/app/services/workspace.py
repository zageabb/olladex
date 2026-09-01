from __future__ import annotations

import difflib
import os
from pathlib import Path

from fastapi import HTTPException

from ..config import settings


IGNORED = {".git", ".venv", "node_modules", ".next", "dist", "build", "__pycache__", ".olladex"}
TEXT_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".txt", ".css", ".scss",
    ".html", ".yml", ".yaml", ".toml", ".ini", ".sh", ".sql", ".xml", ".svg", ".mmd", ".dot",
}


def project_root(project: dict) -> Path:
    root = Path(project["path"]).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(404, "Project directory is no longer available")
    return root


def safe_path(project: dict, relative: str) -> Path:
    root = project_root(project)
    path = (root / relative.lstrip("/")).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(400, "Path escapes the selected project") from exc
    return path


def tree(project: dict, max_depth: int = 6, max_items: int = 800) -> list[dict]:
    root = project_root(project)
    count = 0

    def walk(path: Path, depth: int) -> list[dict]:
        nonlocal count
        result = []
        if depth > max_depth:
            return result
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return result
        for item in entries:
            if count >= max_items or item.name in IGNORED or item.is_symlink():
                continue
            count += 1
            rel = item.relative_to(root).as_posix()
            node = {"name": item.name, "path": rel, "type": "directory" if item.is_dir() else "file"}
            if item.is_dir():
                node["children"] = walk(item, depth + 1)
            else:
                try:
                    node["size"] = item.stat().st_size
                except OSError:
                    node["size"] = 0
            result.append(node)
        return result

    return walk(root, 0)


def read_text(project: dict, relative: str) -> str:
    path = safe_path(project, relative)
    if not path.is_file():
        raise HTTPException(404, "File not found")
    if path.stat().st_size > settings.max_file_bytes:
        raise HTTPException(413, "File is too large for the text viewer")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(415, "File is not UTF-8 text") from exc


def write_text(project: dict, relative: str, content: str) -> tuple[str, str, str]:
    path = safe_path(project, relative)
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    backup_root = project_root(project) / ".olladex" / "history"
    backup = backup_root / relative
    backup.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup.write_text(before, encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    diff = "".join(difflib.unified_diff(before.splitlines(True), content.splitlines(True), fromfile=f"a/{relative}", tofile=f"b/{relative}"))
    return before, content, diff


def search(project: dict, query: str, limit: int = 100) -> list[dict]:
    root = project_root(project)
    query_lower = query.lower()
    results: list[dict] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORED]
        for name in files:
            path = Path(base) / name
            rel = path.relative_to(root).as_posix()
            if query_lower in name.lower():
                results.append({"path": rel, "line": 0, "text": name})
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                if path.stat().st_size > settings.max_file_bytes:
                    continue
                for number, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if query_lower in line.lower():
                        results.append({"path": rel, "line": number, "text": line[:500]})
                        if len(results) >= limit:
                            return results
            except OSError:
                continue
    return results


def project_summary(project: dict) -> str:
    root = project_root(project)
    signals = []
    checks = {
        "package.json": "Node/TypeScript project",
        "pyproject.toml": "Python project",
        "requirements.txt": "Python dependencies",
        "docker-compose.yml": "Docker Compose",
        "Dockerfile": "Docker",
        ".git": "Git repository",
    }
    for name, label in checks.items():
        if (root / name).exists():
            signals.append(label)
    top = [p.name for p in sorted(root.iterdir()) if p.name not in IGNORED][:40]
    return f"Project: {project['name']}\nPath: {root}\nDetected: {', '.join(signals) or 'general repository'}\nTop-level: {', '.join(top)}"

