import json

from backend.app.services.workspace import repository_intelligence


def test_repository_intelligence_detects_stack_and_symbols(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"next": "16", "react": "19"}, "scripts": {"build": "next build", "test": "node --test"}}), encoding="utf-8")
    (tmp_path / "page.tsx").write_text("export function Workspace() { return null }\nconst VERSION = '1'\n", encoding="utf-8")
    project = {"id": 1, "name": "Demo", "path": str(tmp_path), "model": "test", "instructions": "Run tests"}
    result = repository_intelligence(project)
    assert result["frameworks"] == ["Next.js", "React"]
    assert "npm run test" in result["test_commands"]
    assert any(symbol["name"] == "Workspace" for symbol in result["symbols"])
    assert result["instructions_configured"] is True

