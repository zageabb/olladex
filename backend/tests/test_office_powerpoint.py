import base64

from backend.app.services.office import create, edit, inspect, preview_edit


def project(path):
    return {"id": 1, "name": "Presentation Studio", "path": str(path), "model": "test"}


def test_presentation_studio_edits_shape_geometry_style_and_content(tmp_path):
    item = project(tmp_path)
    create(item, "pptx", "deck.pptx", "Deck", "Overview", [])

    operations = [
        {"action": "set_shape_text", "slide_index": 0, "shape_index": 0, "text": "Updated deck"},
        {"action": "set_shape_position", "slide_index": 0, "shape_index": 0, "left": 0.8, "top": 0.5, "width": 5.5, "height": 0.8, "rotation": 3},
        {"action": "set_shape_style", "slide_index": 0, "shape_index": 0, "fill_color": "D9EAF7", "line_color": "336699", "font_color": "112233", "font_size": 24, "bold": True},
        {"action": "add_textbox", "slide_index": 0, "left": 1, "top": 3, "width": 4, "height": 1, "text": "Added note"},
        {"action": "add_shape", "slide_index": 0, "shape": "rounded_rectangle", "left": 7, "top": 3, "width": 2.5, "height": 1.2, "text": "Status", "fill_color": "FFF2CC"},
        {"action": "set_slide_background", "slide_index": 0, "color": "F5F7FA"},
    ]

    preview = preview_edit(item, "deck.pptx", operations)
    assert preview["status"] == "preview"
    assert inspect(item, "deck.pptx")["slides"][0]["text"][0] == "Deck"

    result = edit(item, "deck.pptx", operations)
    slide = result["after"]["slides"][0]
    title = slide["shapes"][0]
    assert title["text"] == "Updated deck"
    assert title["left_inches"] == 0.8
    assert title["top_inches"] == 0.5
    assert title["width_inches"] == 5.5
    assert title["rotation"] == 3
    assert any(shape["text"] == "Added note" for shape in slide["shapes"])
    assert any(shape["text"] == "Status" for shape in slide["shapes"])


def test_presentation_studio_slide_lifecycle(tmp_path):
    item = project(tmp_path)
    create(item, "pptx", "deck.pptx", "Deck", "Overview", [])

    added = edit(
        item,
        "deck.pptx",
        [
            {"action": "add_slide", "layout_index": 1, "title": "Second", "content": "Details"},
            {"action": "add_slide", "layout_index": 1, "title": "Third", "content": "More"},
        ],
    )
    assert added["after"]["slide_count"] == 3
    assert added["after"]["slides"][1]["text"][0] == "Second"
    assert added["after"]["slides"][2]["text"][0] == "Third"

    reordered = edit(item, "deck.pptx", [{"action": "reorder_slide", "slide_index": 2, "target_index": 1}])
    assert reordered["after"]["slides"][1]["text"][0] == "Third"
    assert reordered["after"]["slides"][2]["text"][0] == "Second"

    deleted = edit(item, "deck.pptx", [{"action": "delete_slide", "slide_index": 2}])
    assert deleted["after"]["slide_count"] == 2
    assert [slide["text"][0] for slide in deleted["after"]["slides"]] == ["Deck", "Third"]


def test_presentation_studio_can_insert_project_image(tmp_path):
    item = project(tmp_path)
    create(item, "pptx", "deck.pptx", "Deck", "Overview", [])
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z0c8AAAAASUVORK5CYII="
    )
    (tmp_path / "pixel.png").write_bytes(png)

    before = inspect(item, "deck.pptx")
    result = edit(
        item,
        "deck.pptx",
        [{"action": "add_image", "slide_index": 0, "image_path": "pixel.png", "left": 5, "top": 2, "width": 2}],
    )
    assert len(result["after"]["slides"][0]["shapes"]) == len(before["slides"][0]["shapes"]) + 1
    picture = result["after"]["slides"][0]["shapes"][-1]
    assert picture["left_inches"] == 5
    assert picture["top_inches"] == 2
    assert picture["width_inches"] == 2
