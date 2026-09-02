# Olladex Office Editors

This branch develops Office editing independently from the main Olladex agent/runtime line.

## Safety and integration boundary

- Development branch: `feature/office-editors`.
- No Office editor commits are written to `main` until explicitly merged.
- Existing `/api/projects/{project_id}/office` inspection and creation behavior remains compatible.
- Structured edits use the existing Office POST endpoint with `kind: "preview"` or `kind: "edit"`, avoiding changes to the shared FastAPI routing file while other Olladex development continues.
- Preview mode mutates a temporary copy only.
- Apply mode validates and writes a temporary copy, creates a timestamped binary backup under `.olladex/history`, then atomically replaces the source file.

## Structured operation contract

All indexes are zero-based.

### Word / DOCX

```json
{"action":"set_paragraph","paragraph_index":1,"text":"Updated text"}
{"action":"append_paragraph","text":"New paragraph","style":"Normal"}
{"action":"set_table_cell","table_index":0,"row_index":1,"column_index":2,"text":"Updated cell"}
```

### Excel / XLSX

```json
{"action":"set_cell","sheet":"Data","cell":"B2","value":42}
{"action":"add_sheet","name":"Summary"}
{"action":"rename_sheet","sheet":"Sheet1","name":"Data"}
```

### PowerPoint / PPTX

```json
{"action":"set_shape_text","slide_index":0,"shape_index":0,"text":"Updated title"}
{"action":"add_slide","title":"Next steps","content":"More detail","layout_index":1}
```

## Current editor surface

The Office workspace now provides a first structured editor UI:

- Word: select a paragraph, edit its text, preview, then apply.
- Excel: select a worksheet and visible cell or type a cell address, edit the value, preview, then apply.
- PowerPoint: select a slide text shape, edit its text, preview, then apply.
- PDF remains read-only.

The underlying engine already supports additional operations that can be surfaced by later toolbar and canvas work.

## Development sequence

### Office 0.1 — structured editing foundation

- Structured document snapshots.
- Preview-without-write workflow.
- Atomic binary writes with history backups.
- Word paragraph/table operations.
- Excel cell/sheet operations.
- PowerPoint text/slide operations.
- Initial editor UI.
- Branch-only backend and frontend CI.

### Office 0.2 — Word Studio

- Page-like document surface.
- Paragraph styles, headings and lists.
- Run-level bold/italic/underline/font controls.
- Table creation and row/column editing.
- Images and links.
- Header/footer and section awareness.
- AI proposals shown as document changes before apply.

### Office 0.3 — Spreadsheet Studio

- Dedicated grid component with efficient large-sheet navigation.
- Formula editing and formula visibility.
- Formatting, number formats and alignment.
- Multiple sheets, insert/delete rows and columns.
- Tables, filters, validation and conditional formatting.
- Charts and named ranges.
- Reuse suitable concepts from the AI Spreadsheet project.

### Office 0.4 — Presentation Studio

- Slide thumbnail rail.
- Editable slide canvas.
- Text, images, shapes and layout selection.
- Add/remove/reorder slides.
- Charts and Mermaid/Graphviz output as presentation assets.
- Theme and master awareness.

### Office 0.5 — AI document agent

- Ollama tools operate on structured Office objects rather than regenerating complete files where possible.
- Proposed edits remain reviewable before apply.
- Document-specific change summaries.
- Safe rollback using Office history backups.

## Merge strategy

Keep this branch rebased/merged against the active Olladex line periodically, but do not merge Office changes into `main` until the Office foundation CI is green and the current main development line is ready to accept the feature.
