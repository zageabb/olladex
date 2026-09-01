from backend.app.services.changes import apply, build_hunks, revert


def project(path):
    return {"id": 1, "name": "Changes", "path": str(path), "model": "test"}


def test_partial_hunk_apply_and_safe_revert(tmp_path):
    original = "".join(f"line {index}\n" for index in range(1, 21))
    proposed = original.replace("line 2\n", "line two\n").replace("line 18\n", "line eighteen\n")
    target = tmp_path / "sample.txt"
    target.write_text(original, encoding="utf-8")
    hunks = build_hunks(original, proposed)
    assert len(hunks) == 2

    change = {"status": "proposed", "path": "sample.txt", "before_content": original, "after_content": proposed}
    applied = apply(project(tmp_path), change, [hunks[0]["index"]])
    assert "line two" in applied
    assert "line 18" in applied
    assert "line eighteen" not in applied

    applied_change = {**change, "status": "applied", "applied_content": applied}
    revert(project(tmp_path), applied_change)
    assert target.read_text(encoding="utf-8") == original


def test_hunks_show_additions_and_deletions():
    hunks = build_hunks("one\ntwo\n", "one\nthree\n")
    assert hunks[0]["lines"] == [" one", "-two", "+three"]

