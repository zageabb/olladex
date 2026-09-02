from pathlib import Path

from backend.app.services.office import create, edit, inspect, preview_edit


def project(path):
    return {"id": 1, "name": "Office", "path": str(path), "model": "test"}


def test_create_and_inspect_office_files(tmp_path):
    item = project(tmp_path)
    create(item, "docx", "report.docx", "Report", "First paragraph", [])
    word = inspect(item, "report.docx")
    assert word["paragraphs"][0]["text"] == "Report"
    assert word["paragraphs"][1]["text"] == "First paragraph"

    create(item, "xlsx", "book.xlsx", "Data", "", [["Name", "Value"], ["A", 2]])
    workbook = inspect(item, "book.xlsx")
    assert workbook["sheets"][0]["rows"][1][1] == 2

    create(item, "pptx", "deck.pptx", "Deck", "Overview", [])
    assert inspect(item, "deck.pptx")["slides"][0]["text"][0] == "Deck"


def test_word_preview_does_not_modify_then_apply_creates_backup(tmp_path):
    item = project(tmp_path)
    create(item, "docx", "report.docx", "Report", "Original paragraph", [])
    operations = [
        {"action": "set_paragraph", "paragraph_index": 1, "text": "Edited paragraph"},
        {"action": "append_paragraph", "text": "Added by Olladex"},
    ]

    preview = preview_edit(item, "report.docx", operations)
    assert preview["status"] == "preview"
    assert preview["after"]["paragraphs"][1]["text"] == "Edited paragraph"
    assert inspect(item, "report.docx")["paragraphs"][1]["text"] == "Original paragraph"

    result = edit(item, "report.docx", operations)
    assert result["status"] == "applied"
    assert result["after"]["paragraphs"][1]["text"] == "Edited paragraph"
    assert Path(tmp_path, result["backup_path"]).is_file()
    assert inspect(item, "report.docx")["paragraphs"][-1]["text"] == "Added by Olladex"


def test_existing_office_post_contract_can_preview_and_apply_edits(tmp_path):
    item = project(tmp_path)
    create(item, "docx", "report.docx", "Report", "Original paragraph", [])
    operations = [{"action": "set_paragraph", "paragraph_index": 1, "text": "Changed through Office POST"}]

    preview = create(item, "preview", "report.docx", "", "", operations)
    assert preview["status"] == "preview"
    assert inspect(item, "report.docx")["paragraphs"][1]["text"] == "Original paragraph"

    applied = create(item, "edit", "report.docx", "", "", operations)
    assert applied["status"] == "applied"
    assert inspect(item, "report.docx")["paragraphs"][1]["text"] == "Changed through Office POST"


def test_excel_structured_edit_supports_cells_and_sheets(tmp_path):
    item = project(tmp_path)
    create(item, "xlsx", "book.xlsx", "Data", "", [["Name", "Value"], ["A", 2]])

    result = edit(
        item,
        "book.xlsx",
        [
            {"action": "set_cell", "sheet": "Data", "cell": "B2", "value": 42},
            {"action": "add_sheet", "name": "Summary"},
            {"action": "set_cell", "sheet": "Summary", "cell": "A1", "value": "Total"},
        ],
    )

    assert result["after"]["sheets"][0]["rows"][1][1] == 42
    summary = next(sheet for sheet in result["after"]["sheets"] if sheet["name"] == "Summary")
    assert summary["rows"][0][0] == "Total"


def test_powerpoint_structured_edit_supports_text_and_new_slides(tmp_path):
    item = project(tmp_path)
    create(item, "pptx", "deck.pptx", "Deck", "Overview", [])

    result = edit(
        item,
        "deck.pptx",
        [
            {"action": "set_shape_text", "slide_index": 0, "shape_index": 0, "text": "Updated deck"},
            {"action": "add_slide", "title": "Next", "content": "More detail"},
        ],
    )

    assert result["after"]["slides"][0]["text"][0] == "Updated deck"
    assert result["after"]["slide_count"] == 2
    assert result["after"]["slides"][1]["text"][0] == "Next"
