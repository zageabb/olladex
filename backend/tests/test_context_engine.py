from backend.app.services.context_engine import ranked_context


def project(path):
    return {"id": 1, "name": "Context", "path": str(path), "model": "test"}


def test_ranked_context_prefers_path_and_content_matches(tmp_path):
    (tmp_path / "auth.py").write_text("def create_token():\n    return 'jwt token'\n", encoding="utf-8")
    (tmp_path / "other.py").write_text("def unrelated():\n    return True\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("Authentication uses a JWT token.\n", encoding="utf-8")
    result = ranked_context(project(tmp_path), "Fix authentication JWT token creation")
    assert result[0]["path"] == "auth.py"
    assert all("excerpt" in item for item in result)


def test_ranked_context_ignores_lock_files(tmp_path):
    (tmp_path / "package-lock.json").write_text("authentication " * 100, encoding="utf-8")
    assert ranked_context(project(tmp_path), "authentication") == []


def test_hybrid_context_uses_embedding_similarity(tmp_path):
    (tmp_path / "battery.py").write_text("def state_of_charge():\n    return 80\n", encoding="utf-8")
    (tmp_path / "weather.py").write_text("def forecast():\n    return 'sunny'\n", encoding="utf-8")

    def embedder(texts):
        return [[1.0, 0.0] if "energy reserve" in text or "battery.py" in text else [0.0, 1.0] for text in texts]

    result = ranked_context(project(tmp_path), "energy reserve", embedder=embedder)
    assert result[0]["path"] == "battery.py"
    assert result[0]["strategy"] == "hybrid"
