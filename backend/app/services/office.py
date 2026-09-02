from __future__ import annotations

from docx import Document
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pypdf import PdfReader

from .workspace import safe_path


def inspect(project: dict, relative: str) -> dict:
    path = safe_path(project, relative)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        doc = Document(path)
        paragraphs = [
            {"text": p.text, "style": p.style.name if p.style else "", "runs": [{"text": r.text, "bold": r.bold, "italic": r.italic} for r in p.runs]}
            for p in doc.paragraphs
        ]
        headings = [p for p in paragraphs if str(p.get("style", "")).lower().startswith("heading")]
        tables = [[[c.text for c in row.cells] for row in table.rows] for table in doc.tables]
        return {"kind": "word", "paragraphs": paragraphs, "headings": headings, "tables": tables, "sections": len(doc.sections)}
    if suffix == ".xlsx":
        book = load_workbook(path, read_only=False, data_only=False)
        sheets = []
        for sheet in book.worksheets:
            rows = []
            formulas = []
            for row in list(sheet.iter_rows())[:200]:
                values = []
                for cell in row[:100]:
                    values.append(cell.value)
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        formulas.append({"cell": cell.coordinate, "formula": cell.value})
                rows.append(values)
            sheets.append({
                "name": sheet.title,
                "rows": rows,
                "max_row": sheet.max_row,
                "max_column": sheet.max_column,
                "formulas": formulas[:500],
                "merged_ranges": [str(value) for value in sheet.merged_cells.ranges],
                "freeze_panes": str(sheet.freeze_panes or ""),
                "auto_filter": sheet.auto_filter.ref or "",
            })
        defined_names = [name for name in book.defined_names]
        book.close()
        return {"kind": "excel", "sheets": sheets, "defined_names": defined_names}
    if suffix == ".pptx":
        deck = Presentation(path)
        slides = []
        for index, slide in enumerate(deck.slides, 1):
            shapes = []
            for shape in slide.shapes:
                item = {"name": shape.name, "type": str(shape.shape_type)}
                if hasattr(shape, "text") and shape.text:
                    item["text"] = shape.text
                shapes.append(item)
            slides.append({"number": index, "shapes": shapes, "text": [item["text"] for item in shapes if item.get("text")]})
        return {"kind": "powerpoint", "slides": slides, "slide_count": len(slides)}
    if suffix == ".pdf":
        reader = PdfReader(path)
        return {"kind": "pdf", "pages": [{"number": i + 1, "text": (page.extract_text() or "")[:20_000]} for i, page in enumerate(reader.pages)], "page_count": len(reader.pages)}
    raise ValueError("Supported Office formats are DOCX, XLSX, PPTX and PDF")


def _add_word_content(doc: Document, content: str) -> None:
    for raw in content.splitlines():
        line = raw.rstrip()
        if not line:
            doc.add_paragraph("")
        elif line.startswith("### "):
            doc.add_heading(line[4:], level=3)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("# "):
            doc.add_heading(line[2:], level=1)
        elif line.startswith("- "):
            doc.add_paragraph(line[2:], style="List Bullet")
        else:
            doc.add_paragraph(line)


def _format_sheet(sheet) -> None:
    if sheet.max_row:
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        sheet.freeze_panes = "A2"
        if sheet.max_column:
            sheet.auto_filter.ref = f"A1:{get_column_letter(sheet.max_column)}{sheet.max_row}"
    for column in range(1, min(sheet.max_column, 50) + 1):
        letter = get_column_letter(column)
        width = 10
        for cell in list(sheet[letter])[:200]:
            width = max(width, min(len(str(cell.value or "")) + 2, 40))
        sheet.column_dimensions[letter].width = width


def create(project: dict, kind: str, relative: str, title: str, content: str, data: list[list]) -> dict:
    path = safe_path(project, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "docx":
        doc = Document()
        doc.add_heading(title, 0)
        _add_word_content(doc, content)
        doc.save(path)
    elif kind == "xlsx":
        book = Workbook()
        sheet = book.active
        sheet.title = title[:31] or "Sheet1"
        for row in data or [[title], [content]]:
            sheet.append(row)
        _format_sheet(sheet)
        book.save(path)
    elif kind == "pptx":
        deck = Presentation()
        sections = [part.strip() for part in content.split("\n---\n") if part.strip()] or [content]
        for index, section in enumerate(sections):
            slide = deck.slides.add_slide(deck.slide_layouts[1])
            lines = section.splitlines()
            slide.shapes.title.text = title if index == 0 else (lines[0][:120] if lines else f"{title} {index + 1}")
            body_lines = lines if index == 0 else lines[1:]
            slide.placeholders[1].text = "\n".join(body_lines)
        deck.save(path)
    else:
        raise ValueError("Unsupported Office output")
    return {"path": relative, "kind": kind, "size": path.stat().st_size}
