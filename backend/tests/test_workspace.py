from pathlib import Path

from backend.app.services.workspace import safe_path, search, tree, write_text


def project(path: Path) -> dict:
    return {"id": 1, "name": "Demo", "path": str(path), "model": "test"}


def test_tree_search_and_write(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def health():\n    return 'ok'\n", encoding="utf-8")
    items = tree(project(tmp_path))
    assert items[0]["name"] == "src"
    assert search(project(tmp_path), "health")[0]["line"] == 1
    before, after, diff = write_text(project(tmp_path), "src/main.py", "def health():\n    return True\n")
    assert "return 'ok'" in before
    assert "return True" in after
    assert "+    return True" in diff


def test_safe_path_rejects_escape(tmp_path):
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        safe_path(project(tmp_path), "../secret.txt")

