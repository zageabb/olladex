from __future__ import annotations

import difflib

from fastapi import HTTPException

from ..database import connect
from . import workspace


def build_hunks(before: str, after: str) -> list[dict]:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
    hunks: list[dict] = []
    for index, group in enumerate(matcher.get_grouped_opcodes(3)):
        group = list(group)
        if not any(tag != "equal" for tag, *_ in group):
            continue
        old_start = group[0][1] + 1
        old_end = group[-1][2]
        new_start = group[0][3] + 1
        new_end = group[-1][4]
        lines: list[str] = []
        changes = 0
        for tag, i1, i2, j1, j2 in group:
            if tag in {"equal", "delete", "replace"}:
                prefix = " " if tag == "equal" else "-"
                lines.extend(prefix + line.rstrip("\n") for line in before_lines[i1:i2])
            if tag in {"insert", "replace"}:
                lines.extend("+" + line.rstrip("\n") for line in after_lines[j1:j2])
            if tag != "equal":
                changes += max(i2 - i1, j2 - j1)
        hunks.append({
            "index": index,
            "header": f"@@ -{old_start},{max(0, old_end-old_start+1)} +{new_start},{max(0, new_end-new_start+1)} @@",
            "lines": lines,
            "changes": changes,
        })
    return hunks


def selected_content(before: str, after: str, hunk_indexes: list[int] | None) -> str:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, before_lines, after_lines)
    groups = [list(group) for group in matcher.get_grouped_opcodes(3)]
    available = {index for index, group in enumerate(groups) if any(tag != "equal" for tag, *_ in group)}
    selected = available if hunk_indexes is None else set(hunk_indexes)
    if not selected.issubset(available):
        raise HTTPException(400, "One or more selected hunks do not exist")
    opcode_hunks: dict[tuple, int] = {}
    for index, group in enumerate(groups):
        for opcode in group:
            if opcode[0] != "equal":
                opcode_hunks[tuple(opcode)] = index
    output: list[str] = []
    for opcode in matcher.get_opcodes():
        tag, i1, i2, j1, j2 = opcode
        if tag == "equal":
            output.extend(before_lines[i1:i2])
        elif opcode_hunks.get(tuple(opcode)) in selected:
            output.extend(after_lines[j1:j2])
        else:
            output.extend(before_lines[i1:i2])
    return "".join(output)


def _target_project(project: dict, change: dict) -> dict:
    session_id = change.get("session_id")
    if not session_id:
        return project
    with connect() as conn:
        task = conn.execute(
            "SELECT worktree_path,worktree_branch FROM background_tasks WHERE session_id=? AND worktree_path<>'' ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    if not task:
        return project
    target = dict(project)
    target["path"] = task["worktree_path"]
    target["task_branch"] = task["worktree_branch"]
    return target


def apply(project: dict, change: dict, hunk_indexes: list[int] | None) -> str:
    if change["status"] != "proposed":
        raise HTTPException(409, "Only proposed changes can be applied")
    target = _target_project(project, change)
    path = workspace.safe_path(target, change["path"])
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if current != change["before_content"]:
        raise HTTPException(409, "The file changed after this proposal was created; review a fresh diff")
    content = selected_content(change["before_content"], change["after_content"], hunk_indexes)
    workspace.write_text(target, change["path"], content)
    return content


def revert(project: dict, change: dict) -> None:
    if change["status"] != "applied":
        raise HTTPException(409, "Only applied changes can be reverted")
    target = _target_project(project, change)
    path = workspace.safe_path(target, change["path"])
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    expected = change.get("applied_content") or change["after_content"]
    if current != expected:
        raise HTTPException(409, "The file has changed since this edit was applied; automatic revert was stopped")
    workspace.write_text(target, change["path"], change["before_content"])
