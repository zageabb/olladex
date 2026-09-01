from __future__ import annotations

from pathlib import Path

from docx import Document
from openpyxl import Workbook, load_workbook
from pptx import Presentation
from pptx.util import Inches
from pypdf import PdfReader

from .workspace import safe_path


def inspect(project: dict, relative: str) -> dict:
    path = safe_path(project, relative)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        doc = Document(path)
        return {"kind": "word", "paragraphs": [p.text for p in doc.paragraphs], "tables": [[[c.text for c in row.cells] for row in table.rows] for table in doc.tables]}
    if suffix == ".xlsx":
        book = load_workbook(path, read_only=True, data_only=False)
        sheets = []
        for sheet in book.worksheets:
            rows = [[cell.value for cell in row] for row in list(sheet.iter_rows())[:100]]
            sheets.append({"name": sheet.title, "rows": rows, "max_row": sheet.max_row, "max_column": sheet.max_column})
        book.close()
        return {"kind": "excel", "sheets": sheets}
    if suffix == ".pptx":
        deck = Presentation(path)
        slides = []
        for index, slide in enumerate(deck.slides, 1):
            slides.append({"number": index, "text": [shape.text for shape in slide.shapes if hasattr(shape, "text") and shape.text]})
        return {"kind": "powerpoint", "slides": slides}
    if suffix == ".pdf":
        reader = PdfReader(path)
        return {"kind": "pdf", "pages": [{"number": i + 1, "text": (page.extract_text() or "")[:20_000]} for i, page in enumerate(reader.pages)]}
    raise ValueError("Supported Office formats are DOCX, XLSX, PPTX and PDF")


def create(project: dict, kind: str, relative: str, title: str, content: str, data: list[list]) -> dict:
    path = safe_path(project, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "docx":
        doc = Document()
        doc.add_heading(title, 0)
        for paragraph in content.split("\n\n"):
            doc.add_paragraph(paragraph)
        doc.save(path)
    elif kind == "xlsx":
        book = Workbook()
        sheet = book.active
        sheet.title = title[:31] or "Sheet1"
        for row in data or [[title], [content]]:
            sheet.append(row)
        book.save(path)
    elif kind == "pptx":
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = content
        deck.save(path)
    else:
        raise ValueError("Unsupported Office output")
    return {"path": relative, "kind": kind, "size": path.stat().st_size}

