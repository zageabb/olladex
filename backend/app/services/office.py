from __future__ import annotations

import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from pptx import Presentation
from pypdf import PdfReader

from .office_excel import inspect_xlsx, mutate_xlsx
from .office_excel_plus import compare_xlsx, export_csv, import_csv, mutate_xlsx_plus, range_context, recalculate, validate_formulas
from .office_powerpoint import inspect_pptx, mutate_pptx
from .office_word import inspect_docx, mutate_docx
from .workspace import project_root, safe_path


EDITABLE_SUFFIXES = {".docx", ".xlsx", ".xlsm", ".pptx"}


def inspect(project: dict, relative: str) -> dict:
    path = safe_path(project, relative)
    return _inspect_path(path)


def _inspect_path(path: Path) -> dict:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return inspect_docx(path)
    if suffix in {".xlsx", ".xlsm"}:
        return inspect_xlsx(path)
    if suffix == ".pptx":
        return inspect_pptx(path)
    if suffix == ".pdf":
        reader = PdfReader(path)
        return {
            "kind": "pdf",
            "pages": [{"number": i + 1, "text": (page.extract_text() or "")[:20_000]} for i, page in enumerate(reader.pages)],
            "page_count": len(reader.pages),
        }
    raise ValueError("Supported Office formats are DOCX, XLSX, XLSM, PPTX and PDF")


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


def create(project: dict, kind: str, relative: str, title: str, content: str, data: list[Any]) -> dict:
    if kind in {"preview", "edit"}:
        if not all(isinstance(item, dict) for item in data):
            raise ValueError("Office edit data must contain structured operation objects")
        operations = [dict(item) for item in data]
        return preview_edit(project, relative, operations) if kind == "preview" else edit(project, relative, operations)

    if kind == "validate":
        source = _editable_path(project, relative)
        if source.suffix.lower() not in {".xlsx", ".xlsm"}:
            raise ValueError("Formula validation is available for Excel workbooks")
        return {"status": "validated", "path": _normalized_relative(project, source), **validate_formulas(source)}

    if kind == "recalculate":
        return recalculate_edit(project, relative)

    if kind == "export_csv":
        source = _editable_path(project, relative)
        if source.suffix.lower() not in {".xlsx", ".xlsm"}:
            raise ValueError("CSV export is available for Excel workbooks")
        options = _options(data)
        preview = inspect_xlsx(source)
        sheets = preview.get("sheets") or []
        sheet = str(options.get("sheet") or (sheets[0].get("name") if sheets else ""))
        if not sheet:
            raise ValueError("Workbook contains no worksheets")
        destination = str(options.get("destination") or f".olladex/exports/{source.stem}-{_slug(sheet)}.csv")
        output = safe_path(project, destination)
        export_csv(source, sheet, output)
        return {"status": "exported", "path": destination, "source": relative, "sheet": sheet, "size": output.stat().st_size}

    if kind == "import_csv":
        return import_csv_edit(project, relative, _options(data))

    if kind == "context":
        return selection_context(project, relative, _options(data))

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
            if not isinstance(row, list):
                raise ValueError("Excel creation data must contain rows")
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


def preview_edit(project: dict, relative: str, operations: list[dict[str, Any]]) -> dict:
    source = _editable_path(project, relative)
    before = _inspect_path(source)
    with tempfile.TemporaryDirectory(prefix="olladex-office-preview-") as directory:
        preview_path = Path(directory) / source.name
        shutil.copy2(source, preview_path)
        _mutate(project, preview_path, operations)
        after = _inspect_path(preview_path)
        comparison = _compare(source, preview_path, before, after)
    return {
        "status": "preview",
        "path": _normalized_relative(project, source),
        "operation_count": len(operations),
        "operations": operations,
        "before": before,
        "after": after,
        "comparison": comparison,
    }


def edit(project: dict, relative: str, operations: list[dict[str, Any]]) -> dict:
    source = _editable_path(project, relative)
    normalized = _normalized_relative(project, source)
    before = _inspect_path(source)
    temporary = source.with_name(f".{source.stem}.olladex-edit-{os.getpid()}{source.suffix}")
    shutil.copy2(source, temporary)
    try:
        _mutate(project, temporary, operations)
        after = _inspect_path(temporary)
        comparison = _compare(source, temporary, before, after)
        backup = _backup_file(project, source, normalized)
        os.replace(temporary, source)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "status": "applied",
        "path": normalized,
        "operation_count": len(operations),
        "operations": operations,
        "backup_path": backup,
        "size": source.stat().st_size,
        "before": before,
        "after": after,
        "comparison": comparison,
    }


def recalculate_edit(project: dict, relative: str) -> dict:
    source = _editable_path(project, relative)
    if source.suffix.lower() != ".xlsx":
        raise ValueError("LibreOffice recalculation currently supports XLSX workbooks only")
    normalized = _normalized_relative(project, source)
    before = _inspect_path(source)
    temporary = source.with_name(f".{source.stem}.olladex-recalc-{os.getpid()}.xlsx")
    shutil.copy2(source, temporary)
    try:
        result = recalculate(temporary)
        if not result.get("recalculated"):
            temporary.unlink(missing_ok=True)
            return {"status": "unchanged", "path": normalized, **result}
        after = _inspect_path(temporary)
        comparison = _compare(source, temporary, before, after)
        backup = _backup_file(project, source, normalized)
        os.replace(temporary, source)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {"status": "applied", "path": normalized, "backup_path": backup, "before": before, "after": after, "comparison": comparison, **result}


def import_csv_edit(project: dict, relative: str, options: dict[str, Any]) -> dict:
    source = _editable_path(project, relative)
    if source.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise ValueError("CSV import is available for Excel workbooks")
    csv_relative = str(options.get("csv_path") or "").strip()
    if not csv_relative:
        raise ValueError("import_csv requires csv_path")
    csv_path = safe_path(project, csv_relative)
    if not csv_path.is_file():
        raise ValueError("CSV file not found in project")
    before = _inspect_path(source)
    sheets = before.get("sheets") or []
    sheet = str(options.get("sheet") or (sheets[0].get("name") if sheets else ""))
    if not sheet:
        raise ValueError("Workbook contains no worksheets")
    start_cell = str(options.get("start_cell") or "A1").upper()
    normalized = _normalized_relative(project, source)
    temporary = source.with_name(f".{source.stem}.olladex-import-{os.getpid()}{source.suffix}")
    shutil.copy2(source, temporary)
    try:
        summary = import_csv(temporary, csv_path, sheet, start_cell)
        after = _inspect_path(temporary)
        comparison = _compare(source, temporary, before, after)
        backup = _backup_file(project, source, normalized)
        os.replace(temporary, source)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {"status": "applied", "path": normalized, "backup_path": backup, "summary": summary, "before": before, "after": after, "comparison": comparison}


def selection_context(project: dict, relative: str, options: dict[str, Any]) -> dict:
    source = safe_path(project, relative)
    suffix = source.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        preview = inspect_xlsx(source)
        sheets = preview.get("sheets") or []
        sheet = str(options.get("sheet") or (sheets[0].get("name") if sheets else ""))
        cell_range = str(options.get("range") or options.get("cell") or "A1").upper()
        text = range_context(source, sheet, cell_range)
        selection = {"sheet": sheet, "range": cell_range}
    elif suffix == ".docx":
        payload = inspect_docx(source)
        paragraphs = payload.get("paragraphs") or []
        start = max(0, int(options.get("paragraph_start", options.get("paragraph_index", 0))))
        end = min(len(paragraphs) - 1, int(options.get("paragraph_end", start))) if paragraphs else -1
        lines = [f"WORD SELECTION: {source.name} paragraphs {start + 1}-{end + 1}"]
        for paragraph in paragraphs[start:end + 1]:
            lines.append(f"[{int(paragraph.get('index', 0)) + 1} · {paragraph.get('style', 'Normal')}] {paragraph.get('text', '')}")
        text = "\n".join(lines)
        selection = {"paragraph_start": start, "paragraph_end": end}
    elif suffix == ".pptx":
        payload = inspect_pptx(source)
        slides = payload.get("slides") or []
        requested = options.get("slide_indices")
        selected_indices = [int(value) for value in requested] if isinstance(requested, list) else [int(options.get("slide_index", 0))]
        lines = [f"POWERPOINT SELECTION: {source.name}"]
        for index in selected_indices:
            if index < 0 or index >= len(slides):
                continue
            slide = slides[index]
            lines.append(f"[Slide {index + 1} · {slide.get('layout', 'Layout')}]\n" + "\n".join(str(value) for value in slide.get("text") or []))
        text = "\n\n".join(lines)
        selection = {"slide_indices": selected_indices}
    else:
        raise ValueError("Selection context is available for DOCX, XLSX/XLSM and PPTX files")
    return {"status": "context", "path": relative, "selection": selection, "context": text}


def _editable_path(project: dict, relative: str) -> Path:
    path = safe_path(project, relative)
    if not path.is_file():
        raise ValueError("Office file not found")
    if path.suffix.lower() not in EDITABLE_SUFFIXES:
        raise ValueError("Structured editing supports DOCX, XLSX, XLSM and PPTX")
    return path


def _normalized_relative(project: dict, path: Path) -> str:
    return path.relative_to(project_root(project)).as_posix()


def _backup_file(project: dict, source: Path, normalized: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_root = project_root(project) / ".olladex" / "history" / stamp
    backup = backup_root / normalized
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup.relative_to(project_root(project)).as_posix()


def _mutate(project: dict, path: Path, operations: list[dict[str, Any]]) -> None:
    if not operations:
        raise ValueError("At least one Office edit operation is required")
    suffix = path.suffix.lower()
    if suffix == ".docx":
        mutate_docx(project, path, operations)
    elif suffix in {".xlsx", ".xlsm"}:
        mutate_xlsx_plus(path, operations)
    elif suffix == ".pptx":
        mutate_pptx(project, path, operations)
    else:
        raise ValueError("Structured editing supports DOCX, XLSX, XLSM and PPTX")


def _compare(before_path: Path, after_path: Path, before: dict, after: dict) -> dict[str, Any]:
    suffix = before_path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return compare_xlsx(before_path, after_path)
    if suffix == ".docx":
        return _compare_records("paragraph", before.get("paragraphs") or [], after.get("paragraphs") or [], extras=(before.get("table_details"), after.get("table_details")))
    if suffix == ".pptx":
        return _compare_records("slide", before.get("slides") or [], after.get("slides") or [])
    return {"changes": [], "truncated": False}


def _compare_records(label: str, before: list[Any], after: list[Any], extras: tuple[Any, Any] | None = None) -> dict[str, Any]:
    changes: list[dict[str, Any]] = []
    for index in range(max(len(before), len(after))):
        old = before[index] if index < len(before) else None
        new = after[index] if index < len(after) else None
        if old != new:
            changes.append({label: index + 1, "before": old, "after": new})
    if extras and extras[0] != extras[1]:
        changes.append({"change": "tables", "before": extras[0], "after": extras[1]})
    return {"changes": changes, "truncated": False}


def _options(data: list[Any]) -> dict[str, Any]:
    if not data:
        return {}
    first = data[0]
    if not isinstance(first, dict):
        raise ValueError("Office utility data must contain an options object")
    return dict(first)


def _slug(value: str) -> str:
    clean = "".join(character if character.isalnum() else "-" for character in value.lower()).strip("-")
    return clean or "sheet"
