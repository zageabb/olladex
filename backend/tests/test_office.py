from backend.app.services.office import create, inspect


def project(path):
    return {"id": 1, "name": "Office", "path": str(path), "model": "test"}


def test_create_and_inspect_office_files(tmp_path):
    item = project(tmp_path)
    create(item, "docx", "report.docx", "Report", "First paragraph", [])
    assert inspect(item, "report.docx")["paragraphs"][0] == "Report"

    create(item, "xlsx", "book.xlsx", "Data", "", [["Name", "Value"], ["A", 2]])
    workbook = inspect(item, "book.xlsx")
    assert workbook["sheets"][0]["rows"][1][1] == 2

    create(item, "pptx", "deck.pptx", "Deck", "Overview", [])
    assert inspect(item, "deck.pptx")["slides"][0]["text"][0] == "Deck"

