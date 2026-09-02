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
- Paragraph alignment and run-level bold, italic, underline, font size and colour operations.
- Paragraph append/insert/delete operations.
- Table creation plus row/column/cell editing support.
- Image and hyperlink insertion.
- Header/footer editing.
- Portrait/landscape sections and margin-aware inspection.
- Rich DOCX inspection including runs, tables, sections and inline-image dimensions.

### Spreadsheet Studio — Office 0.3 foundation complete

- Interactive worksheet grid with sticky row/column headers and worksheet tabs.
- Cell address and formula/value bar with formula preservation and visibility.
- Cell font size, bold, italic, font/fill colour, alignment, wrapping and number-format editing.
- Multi-cell range writes in the backend.
- Add/rename/delete worksheets; insert/delete rows and columns.
- Merge/unmerge ranges, freeze panes and AutoFilter ranges.
- Row height and column width operations.
- Real XLSX ListObject/Table creation with table styles.
- Rich XLSX inspection including formulas, formatting metadata, merges, tables and pane/filter state.

### Presentation Studio — Office 0.4 foundation complete

- Slide thumbnail rail and scaled slide canvas.
- Selectable slide shapes with geometry inspection in inches.
- Shape text editing, position, size, rotation, fill/line colour and text styling.
- Add/delete/reorder slides using available presentation layouts.
- Add textboxes, basic shapes and project images.
- Slide background colour editing.
- Rich PPTX inspection including layouts, slide dimensions, shape geometry and text runs.
- Preview/apply/history-backup workflow shared with Word and Spreadsheet Studio.

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
{"action":"set_shape_position","slide_index":0,"shape_index":0,"left":1,"top":0.5,"width":5,"height":1,"rotation":0}
{"action":"set_shape_style","slide_index":0,"shape_index":0,"fill_color":"D9EAF7","font_color":"112233","font_size":24}
{"action":"add_slide","title":"Next steps","content":"More detail","layout_index":1}
{"action":"add_textbox","slide_index":0,"left":1,"top":2,"width":4,"height":1,"text":"New text"}
{"action":"add_shape","slide_index":0,"shape":"rounded_rectangle","left":7,"top":3,"width":2.5,"height":1.2,"text":"Status"}
{"action":"add_image","slide_index":0,"image_path":"docs/image.png","left":1,"top":1,"width":4}
```

## Development sequence

### Office 0.1 — structured editing foundation — complete

Structured snapshots, preview-without-write, atomic binary writes with history backups, and initial Word/Excel/PowerPoint operations.

### Office 0.2 — Word Studio — foundation complete

Remaining depth work: individual-run selection, richer table UI, image positioning/wrapping/captions, page/section breaks, document-derived styles, comments/tracked changes where practical, and AI Word-object proposals.

### Office 0.3 — Spreadsheet Studio — foundation complete

Remaining depth work: virtualised large-sheet navigation, direct range selection/fill/copy, borders, validation, conditional formatting, named ranges, charts, and a formula calculation/preview strategy.

### Office 0.4 — Presentation Studio — foundation complete

Remaining depth work: drag/resize handles on canvas, shape z-order/grouping, slide notes, charts, richer images, Mermaid/Graphviz assets, theme/master awareness and slide-template workflows.

### Office 0.5 — AI document agent — next integration phase

- Ollama tools operate on structured Office objects rather than regenerating complete files where possible.
- Proposed edits remain reviewable before apply.
- Document-specific change summaries.
- Safe rollback using Office history backups.
- Keep this work isolated from the active core-agent runtime until the Office branch is deliberately integrated.

## Merge strategy

Keep this branch synced against the active Olladex line periodically, but do not merge Office changes into `main` until the Office branch CI is green and the active main development line is ready to accept the feature.
