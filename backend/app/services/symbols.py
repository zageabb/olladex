from __future__ import annotations

import re
from pathlib import Path


LANGUAGES = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".go": "go", ".rs": "rust",
    ".java": "java", ".cs": "c_sharp", ".cpp": "cpp", ".c": "c",
    ".rb": "ruby", ".php": "php", ".swift": "swift", ".kt": "kotlin",
}

SYMBOL_NODES = {
    "function_definition": "function", "function_declaration": "function",
    "method_definition": "method", "method_declaration": "method",
    "class_definition": "class", "class_declaration": "class",
    "interface_declaration": "interface", "type_alias_declaration": "type",
    "struct_item": "struct", "enum_item": "enum", "trait_item": "trait",
    "function_item": "function", "impl_item": "implementation",
}


def extract(path: Path, relative: str, limit: int = 250) -> list[dict]:
    language = LANGUAGES.get(path.suffix.lower())
    if not language:
        return []
    source = path.read_bytes()
    try:
        from tree_sitter_language_pack import get_parser
        parser = get_parser(language)
        root = parser.parse(source).root_node
        found: list[dict] = []
        stack = [root]
        while stack and len(found) < limit:
            node = stack.pop()
            kind = SYMBOL_NODES.get(node.type)
            if kind:
                name_node = node.child_by_field_name("name")
                if name_node:
                    found.append({"name": source[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace"), "kind": kind, "path": relative, "line": node.start_point[0] + 1, "parser": "tree-sitter"})
            stack.extend(reversed(node.children))
        return found
    except Exception:
        return fallback(source.decode("utf-8", errors="ignore"), relative, limit)


def fallback(content: str, relative: str, limit: int = 250) -> list[dict]:
    pattern = re.compile(r"^(?:export\s+)?(?:async\s+)?(?:def|class|function|interface|type|const|let|var)\s+([A-Za-z_$][\w$]*)")
    result = []
    for number, line in enumerate(content.splitlines(), 1):
        match = pattern.match(line.strip())
        if match:
            result.append({"name": match.group(1), "kind": "symbol", "path": relative, "line": number, "parser": "fallback"})
            if len(result) >= limit:
                break
    return result

