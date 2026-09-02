from backend.app.services.office import create, edit, inspect, preview_edit


def project(path):
    return {"id": 1, "name": "Spreadsheet Studio", "path": str(path), "model": "test"}


def test_spreadsheet_studio_formats_cells_ranges_tables_and_panes(tmp_path):
    item = project(tmp_path)
    create(item, "xlsx", "book.xlsx", "Data", "", [["Name", "Value"], ["A", 2], ["B", 3]])

    operations = [
        {"action": "set_cell", "sheet": "Data", "cell": "B2", "value": "=SUM(B3:B3)"},
        {
            "action": "set_cell_format",
            "sheet": "Data",
            "cell": "B2",
            "bold": True,
            "italic": True,
            "font_size": 14,
            "font_color": "336699",
            "fill_color": "FFF2CC",
            "horizontal": "center",
            "wrap_text": True,
            "number_format": "0.00",
        },
        {"action": "set_range_values", "sheet": "Data", "start_cell": "C1", "values": [["Status"], ["Open"], ["Closed"]]},
        {"action": "merge_cells", "sheet": "Data", "range": "D1:E1"},
        {"action": "freeze_panes", "sheet": "Data", "cell": "A2"},
        {"action": "set_auto_filter", "sheet": "Data", "range": "A1:C3"},
        {"action": "set_column_width", "sheet": "Data", "column": "C", "width": 24},
        {"action": "set_row_height", "sheet": "Data", "row": 1, "height": 22},
        {"action": "add_table", "sheet": "Data", "range": "A1:C3", "name": "DataTable", "style": "TableStyleMedium2"},
    ]

    preview = preview_edit(item, "book.xlsx", operations)
    assert preview["status"] == "preview"
    assert inspect(item, "book.xlsx")["sheets"][0]["rows"][1][1] == 2

    result = edit(item, "book.xlsx", operations)
    sheet = result["after"]["sheets"][0]
    detail = next(cell for cell in sheet["cells"] if cell["cell"] == "B2")
    assert detail["formula"] == "=SUM(B3:B3)"
    assert detail["bold"] is True
    assert detail["italic"] is True
    assert detail["font_size"] == 14
    assert detail["font_color"].endswith("336699")
    assert detail["fill_color"].endswith("FFF2CC")
    assert detail["horizontal"] == "center"
    assert detail["wrap_text"] is True
    assert detail["number_format"] == "0.00"
    assert sheet["rows"][1][2] == "Open"
    assert "D1:E1" in sheet["merged_ranges"]
    assert sheet["freeze_panes"] == "A2"
    assert sheet["auto_filter"] == "A1:C3"
    assert sheet["tables"][0]["name"] == "DataTable"


def test_spreadsheet_studio_sheet_and_dimension_lifecycle(tmp_path):
    item = project(tmp_path)
    create(item, "xlsx", "book.xlsx", "Data", "", [["A", "B"], [1, 2], [3, 4]])

    result = edit(
        item,
        "book.xlsx",
        [
            {"action": "add_sheet", "name": "Summary"},
            {"action": "set_cell", "sheet": "Summary", "cell": "A1", "value": "Total"},
            {"action": "rename_sheet", "sheet": "Summary", "name": "Overview"},
            {"action": "insert_rows", "sheet": "Data", "index": 2, "amount": 1},
            {"action": "insert_columns", "sheet": "Data", "index": 2, "amount": 1},
        ],
    )

    names = [sheet["name"] for sheet in result["after"]["sheets"]]
    assert names == ["Data", "Overview"]
    overview = next(sheet for sheet in result["after"]["sheets"] if sheet["name"] == "Overview")
    assert overview["rows"][0][0] == "Total"
    data = next(sheet for sheet in result["after"]["sheets"] if sheet["name"] == "Data")
    assert data["max_row"] == 4
    assert data["max_column"] == 3

    deleted = edit(
        item,
        "book.xlsx",
        [
            {"action": "delete_rows", "sheet": "Data", "index": 2, "amount": 1},
            {"action": "delete_columns", "sheet": "Data", "index": 2, "amount": 1},
            {"action": "delete_sheet", "sheet": "Overview"},
        ],
    )
    assert [sheet["name"] for sheet in deleted["after"]["sheets"]] == ["Data"]
