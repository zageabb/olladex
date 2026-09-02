# Olladex Office Editors

This branch develops Office editing independently from the main Olladex agent/runtime line.

## Safety and integration boundary

- Development branch: `feature/office-editors`.
- No Office editor commits are written to `main` until explicitly merged.
- Existing `/api/projects/{project_id}/office` inspection and creation behavior remains compatible.
- Structured edits use the existing Office POST endpoint with `kind: "preview"` or `kind: "edit"`, avoiding changes to the shared FastAPI routing file while other Olladex development continues.
- Preview mode mutates a temporary copy only.
- Apply mode validates and writes a temporary copy, creates a timestamped binary backup under `.olladex/history`, then atomically replaces the source file.

## Current editor surfaces

### Word Studio — Office 0.2 foundation complete

- Page-like document canvas with selectable paragraphs.
- Title, Subtitle, Heading 1–3, bullets and numbered-list styles.
- Paragraph alignment.
- Run-level bold, italic, underline, font size and colour operations.
- Paragraph append/insert/delete operations.
- Table creation plus row/column/cell editing support.
- Image insertion from project files.
- Hyperlink insertion.
- Header/footer editing.
- Portrait/landscape section orientation and margin-aware inspection.
- Rich DOCX inspection including runs, tables, page sections and inline-image dimensions.

### Spreadsheet Studio — Office 0.3 foundation complete

- Interactive worksheet grid with sticky row/column headers.
- Worksheet tabs.
- Cell address and formula/value bar.
- Formula preservation and visibility.
- Cell font size, bold, italic, font colour, fill colour, alignment, wrapping and number-format editing.
- Preview-before-apply for values and formats.
- Multi-cell range writes in the backend.
- Add/rename/delete worksheets.
- Insert/delete rows and columns.
- Merge/unmerge ranges.
- Freeze panes.
- AutoFilter range editing.
- Row height and column width operations.
- Real XLSX ListObject/Table creation with table styles.
- Rich XLSX inspection including formulas, formatting metadata, merges, tables and pane/filter state.

### PowerPoint editor — Office 0.4 next

PowerPoint currently supports structured text-shape selection/editing plus slide creation in the backend. The next dedicated surface is Presentation Studio with a thumbnail rail and editable slide canvas.

### PDF

PDF remains read-only.

## Structured operation examples

All indexes are zero-based unless the Office format uses native 1-based row/column coordinates.

### Word / DOCX

```json
{"action":"set_paragraph","paragraph_index":1,"text":"Updated text","style":"Heading 2","alignment":"center"}
{"action":"set_run","paragraph_index":1,"run_index":0,"bold":true,"font_size":14,"color":"1768E5"}
{"action":"add_table","rows":3,"columns":2,"style":"Table Grid"}
{"action":"add_image","paragraph_index":1,"image_path":"docs/image.png","width_inches":4}
{"action":"set_section","section_index":0,"orientation":"landscape"}
```

### Excel / XLSX

```json
{"action":"set_cell","sheet":"Data","cell":"B2","value":"=SUM(B3:B10)"}
{"action":"set_cell_format","sheet":"Data","cell":"B2","bold":true,"fill_color":"FFF2CC","number_format":"0.00"}
{"action":"set_range_values","sheet":"Data","start_cell":"C1","values":[["Status"],["Open"]]}
{"action":"insert_rows","sheet":"Data","index":2,"amount":1}
{"action":"merge_cells","sheet":"Data","range":"D1:E1"}
{"action":"freeze_panes","sheet":"Data","cell":"A2"}
{"action":"add_table","sheet":"Data","range":"A1:C20","name":"DataTable","style":"TableStyleMedium2"}
```

### PowerPoint / PPTX

```json
{"action":"set_shape_text","slide_index":0,"shape_index":0,"text":"Updated title"}
{"action":"add_slide","title":"Next steps","content":"More detail","layout_index":1}
```

## Development sequence

### Office 0.1 — structured editing foundation — complete

- Structured document snapshots.
- Preview-without-write workflow.
- Atomic binary writes with history backups.
- Initial Word, Excel and PowerPoint operations and editor UI.
- Branch-only backend/frontend CI.

### Office 0.2 — Word Studio — foundation complete

Remaining depth work:

- Direct individual-run selection in the UI.
- Rich table-cell/row/column controls on the page canvas.
- Image positioning, wrapping, captions and replacement.
- Page/section breaks, columns and richer header/footer options.
- Document-derived styles gallery.
- Comments/tracked changes where OOXML support is practical.
- AI proposals shown as Word-object changes before apply.

### Office 0.3 — Spreadsheet Studio — foundation complete

Remaining depth work:

- Virtualised navigation for very large worksheets.
- Direct range selection and fill/copy workflows.
- Borders and richer cell styles.
- Data validation and conditional formatting.
- Named ranges and workbook properties UI.
- Charts and chart editing.
- Formula calculation/preview strategy for functions openpyxl does not calculate.
- Reuse suitable concepts from the AI Spreadsheet project where they improve the grid/editor experience.

### Office 0.4 — Presentation Studio — next

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

Keep this branch synced against the active Olladex line periodically, but do not merge Office changes into `main` until the Office branch CI is green and the active main development line is ready to accept the feature.
