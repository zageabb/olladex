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
{"action":"set_paragraph","paragraph_index":1,"text":"Updated text","style":"Heading 2","alignment":"center"}
{"action":"set_run","paragraph_index":1,"run_index":0,"bold":true,"italic":false,"underline":false,"font_size":14,"color":"1768E5"}
{"action":"append_paragraph","text":"New paragraph","style":"Normal"}
{"action":"insert_paragraph_after","paragraph_index":1,"text":"Inserted paragraph","style":"List Bullet"}
{"action":"delete_paragraph","paragraph_index":2}
{"action":"set_table_cell","table_index":0,"row_index":1,"column_index":2,"text":"Updated cell"}
{"action":"add_table","rows":3,"columns":2,"style":"Table Grid"}
{"action":"add_table_row","table_index":0,"values":["New","Row"]}
{"action":"add_table_column","table_index":0,"width_inches":1.25}
{"action":"add_image","paragraph_index":1,"image_path":"docs/image.png","width_inches":4}
{"action":"add_hyperlink","paragraph_index":1,"text":"Open link","url":"https://example.com"}
{"action":"set_section","section_index":0,"orientation":"landscape","left_margin":0.75,"right_margin":0.75}
{"action":"set_header","section_index":0,"text":"Header text"}
{"action":"set_footer","section_index":0,"text":"Footer text"}
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

The Office workspace now routes DOCX files into **Word Studio** and retains the structured Excel and PowerPoint editors.

Word Studio currently provides:

- Page-like document canvas with selectable paragraphs.
- Paragraph styles including Title, Subtitle, Heading 1–3, bullets and numbered lists.
- Paragraph alignment controls.
- Whole-paragraph bold, italic, underline, font size and colour editing through run formatting.
- Paragraph insertion/deletion and append workflows.
- Table insertion plus backend row/column/cell operations.
- Image insertion from project files with preview-before-apply support.
- Hyperlink insertion.
- Header and footer editing.
- Portrait/landscape section orientation and margin-aware inspection.
- Rich DOCX inspection including runs, tables, page sections and inline image dimensions.
- The existing Office preview/apply/history-backup safety model.

Excel currently supports worksheet/cell selection and value editing. PowerPoint currently supports slide text-shape selection and text editing. PDF remains read-only.

## Development sequence

### Office 0.1 — structured editing foundation — complete

- Structured document snapshots.
- Preview-without-write workflow.
- Atomic binary writes with history backups.
- Word paragraph/table operations.
- Excel cell/sheet operations.
- PowerPoint text/slide operations.
- Initial editor UI.
- Branch-only backend and frontend CI.

### Office 0.2 — Word Studio — foundation complete

Completed in this pass:

- Page-like document surface.
- Paragraph styles, headings and lists.
- Run-level bold/italic/underline/font-size/colour controls.
- Table creation and backend row/column editing.
- Images and links.
- Header/footer and section awareness.
- Dedicated `office_word` service to isolate Word-specific OOXML work from Excel/PowerPoint.
- Word-specific backend regression suite.

Still to deepen before considering Word Studio feature-complete:

- Direct selection/editing of individual runs rather than formatting the whole selected paragraph.
- Rich table cell UI and row/column controls on the page canvas.
- Image positioning, wrapping, captions and replacement.
- Header/footer first/different-page options.
- Page breaks, section breaks and columns.
- Styles gallery derived from the document rather than a fixed built-in shortlist.
- Comments, tracked changes and document properties where OOXML support is practical.
- AI proposals shown as Word-object changes before apply.

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
