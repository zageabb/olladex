from backend.app.config import settings
from backend.app.database import connect, init_db, now
from backend.app.services import repository_index


def test_repository_index_updates_changed_and_removed_files(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_root", tmp_path / "data")
    init_db()
    repository = tmp_path / "repository"
    repository.mkdir()
    source = repository / "service.py"
    source.write_text("def authenticate():\n    return True\n", encoding="utf-8")
    with connect() as conn:
        cursor = conn.execute("INSERT INTO projects(name,path,model,created_at,last_opened_at) VALUES(?,?,?,?,?)", ("Index", str(repository), "test", now(), now()))
        project_id = cursor.lastrowid
    project = {"id": project_id, "name": "Index", "path": str(repository), "model": "test"}

    def embedder(texts):
        return [[1.0, float(index)] for index, _ in enumerate(texts)]

    first = repository_index.refresh(project, embedder=embedder, embedding_model="test-embed")
    assert first["changed"] == 1
    assert first["embedded"] == 1
    result = repository_index.ranked_context(project, "authentication", embedder=embedder, embedding_model="test-embed")
    assert result[0]["path"] == "service.py"
    assert result[0]["strategy"] == "indexed-hybrid"

    source.write_text("def authenticate_user():\n    return False\n", encoding="utf-8")
    assert repository_index.refresh(project, embedder=embedder, embedding_model="test-embed")["changed"] == 1
    source.unlink()
    assert repository_index.refresh(project)["removed"] == 1
