import base64

from backend.app.services.office import create, edit, inspect, preview_edit


def project(path):
    return {"id": 1, "name": "Word Studio", "path": str(path), "model": "test"}


def test_word_studio_formats_paragraphs_tables_and_sections(tmp_path):
    item = project(tmp_path)
    create(item, "docx", "report.docx", "Report", "Original paragraph", [])

    preview = preview_edit(
        item,
        "report.docx",
        [
            {"action": "set_paragraph", "paragraph_index": 1, "text": "Styled paragraph", "style": "Heading 2", "alignment": "center"},
            {"action": "set_run", "paragraph_index": 1, "run_index": 0, "bold": True, "italic": True, "underline": True, "font_size": 18, "color": "336699"},
            {"action": "add_table", "rows": 2, "columns": 2, "style": "Table Grid", "data": [["Name", "Value"], ["A", 2]]},
            {"action": "set_header", "section_index": 0, "text": "Olladex header"},
            {"action": "set_footer", "section_index": 0, "text": "Olladex footer"},
            {"action": "set_section", "section_index": 0, "orientation": "landscape", "left_margin": 0.75, "right_margin": 0.75},
        ],
    )

    assert preview["after"]["paragraphs"][1]["text"] == "Styled paragraph"
    assert inspect(item, "report.docx")["paragraphs"][1]["text"] == "Original paragraph"

    result = edit(item, "report.docx", preview["operations"])
    word = result["after"]
    paragraph = word["paragraphs"][1]
    assert paragraph["style"] == "Heading 2"
    assert paragraph["alignment"] == "center"
    assert paragraph["runs"][0]["bold"] is True
    assert paragraph["runs"][0]["italic"] is True
    assert paragraph["runs"][0]["underline"] is True
    assert paragraph["runs"][0]["font_size"] == 18
    assert paragraph["runs"][0]["color"] == "336699"
    assert word["table_details"][0]["rows"][1][1] == "2"
    assert word["sections"][0]["orientation"] == "landscape"
    assert word["sections"][0]["header"] == "Olladex header"
    assert word["sections"][0]["footer"] == "Olladex footer"
    assert word["sections"][0]["left_margin_inches"] == 0.75


def test_word_studio_supports_insert_delete_rows_columns_and_links(tmp_path):
    item = project(tmp_path)
    create(item, "docx", "report.docx", "Report", "First\nSecond", [])

    result = edit(
        item,
        "report.docx",
        [
            {"action": "insert_paragraph_after", "paragraph_index": 1, "text": "Inserted", "style": "List Bullet"},
            {"action": "add_hyperlink", "paragraph_index": 1, "text": "OpenAI", "url": "https://openai.com"},
            {"action": "add_table", "rows": 1, "columns": 1, "style": "Table Grid", "data": [["A"]]},
            {"action": "add_table_row", "table_index": 0, "values": ["B"]},
            {"action": "add_table_column", "table_index": 0, "width_inches": 1.0},
        ],
    )

    assert any(paragraph["text"] == "Inserted" and paragraph["style"] == "List Bullet" for paragraph in result["after"]["paragraphs"])
    assert result["after"]["table_details"][0]["row_count"] == 2
    assert result["after"]["table_details"][0]["column_count"] == 2

    inserted_index = next(index for index, paragraph in enumerate(result["after"]["paragraphs"]) if paragraph["text"] == "Inserted")
    deleted = edit(item, "report.docx", [{"action": "delete_paragraph", "paragraph_index": inserted_index}])
    assert not any(paragraph["text"] == "Inserted" for paragraph in deleted["after"]["paragraphs"])


def test_word_studio_can_insert_project_image(tmp_path):
    item = project(tmp_path)
    create(item, "docx", "report.docx", "Report", "Image below", [])
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z0c8AAAAASUVORK5CYII="
    )
    (tmp_path / "pixel.png").write_bytes(png)

    result = edit(
        item,
        "report.docx",
        [{"action": "add_image", "image_path": "pixel.png", "width_inches": 1.25, "paragraph_index": 1}],
    )

    assert len(result["after"]["inline_shapes"]) == 1
    assert result["after"]["inline_shapes"][0]["width_inches"] == 1.25
