# Olladex / Context Studio Office convergence

This branch applies the reusable Office-engine lessons from Context Studio back into Olladex without importing Context Studio's portfolio, Knowledge, governance or business-rule layers.

## Ported from Context Studio

### Excel

- Formula-aware range fill using `openpyxl.formula.translate.Translator`.
- Multi-cell range formatting.
- Range sorting with header support.
- Bar, line and pie chart creation.
- Formula validation, including broken references and missing worksheet references.
- Optional headless LibreOffice recalculation.
- CSV export and project-file CSV import.
- Cell-level before/after comparisons for Office previews and edits.
- Selected-range context extraction for LLM use.
- XLSM-safe editing with `keep_vba=True` in the unified spreadsheet editor.

### Word and PowerPoint

- Structured before/after comparison is now returned from the existing Office preview/edit API.
- Selection-context extraction is available for Word paragraph ranges and PowerPoint slide selections through `kind: "context"`.

## Olladex architecture retained

Olladex remains repository-focused:

- Office edits still use the existing Olladex preview/apply workflow.
- Applied edits retain `.olladex/history` backups.
- No Context Studio portfolio hierarchy is introduced.
- No Context Studio Knowledge, rule inheritance, permissions or ChangeSet database model is introduced.
- The existing Word Studio and Presentation Studio remain the richer freeform Office editors developed in Olladex.

## Office utility API

The existing `POST /api/projects/{project_id}/office` endpoint now supports these additional `kind` values:

- `validate` — validate workbook formulas.
- `recalculate` — recalculate an XLSX workbook with LibreOffice when available, with backup before replacement.
- `export_csv` — export a worksheet to CSV.
- `import_csv` — import a project CSV file into a worksheet at a chosen start cell, with backup.
- `context` — extract a bounded Word, Excel or PowerPoint selection for LLM context.

`preview` and `edit` responses now also include a `comparison` payload.

## Advanced spreadsheet operations

The unified Excel editor supports the existing Olladex operations plus:

- `set_cells`
- `fill`
- `format`
- `sort`
- `chart`

These operations work alongside existing cell, range, worksheet, merge, pane, filter, dimension and table operations.

## UI

Spreadsheet Studio exposes the reverse-port features directly:

- formula-aware fill
- range formatting
- ascending/descending sort
- chart creation
- formula validation
- LibreOffice recalculation
- CSV import/export
- selected-range LLM context preview

## Verification

The Office CI workflow runs the backend Office tests and the frontend production build. `test_office_excel.py` includes regression coverage for formula translation, sorting, comparison output, formula validation, range context and CSV interchange.
