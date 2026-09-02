"use client";

import { CSSProperties, useEffect, useMemo, useState } from "react";
import { request } from "../lib/api";
import styles from "./WordStudio.module.css";

type Preview = Record<string, unknown>;
type Operation = Record<string, unknown>;

function records(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object") : [];
}

function paragraphClass(styleName: string): string {
  const style = styleName.toLowerCase();
  if (style === "title") return styles.title;
  if (style === "subtitle") return styles.subtitle;
  if (style.startsWith("heading 1")) return styles.heading1;
  if (style.startsWith("heading 2")) return styles.heading2;
  if (style.startsWith("heading 3")) return styles.heading3;
  if (style.startsWith("list ")) return styles.list;
  return "";
}

function textAlign(value: unknown): CSSProperties["textAlign"] {
  const alignment = String(value || "left");
  return (["left", "center", "right", "justify"] as const).includes(alignment as "left" | "center" | "right" | "justify")
    ? alignment as CSSProperties["textAlign"]
    : "left";
}

export function WordStudio({
  projectId,
  selectedPath,
  preview,
  onPreviewChanged,
}: {
  projectId: number;
  selectedPath: string;
  preview: Preview;
  onPreviewChanged: (preview: Preview) => void;
}) {
  const paragraphs = useMemo(() => records(preview.paragraphs), [preview]);
  const tables = useMemo(() => records(preview.table_details), [preview]);
  const sections = useMemo(() => records(preview.sections), [preview]);
  const [paragraphIndex, setParagraphIndex] = useState(0);
  const [text, setText] = useState("");
  const [styleName, setStyleName] = useState("Normal");
  const [alignment, setAlignment] = useState("left");
  const [bold, setBold] = useState(false);
  const [italic, setItalic] = useState(false);
  const [underline, setUnderline] = useState(false);
  const [fontSize, setFontSize] = useState(11);
  const [color, setColor] = useState("#202124");
  const [status, setStatus] = useState("");
  const [newParagraph, setNewParagraph] = useState("");
  const [newParagraphStyle, setNewParagraphStyle] = useState("Normal");
  const [tableRows, setTableRows] = useState(2);
  const [tableColumns, setTableColumns] = useState(2);
  const [imagePath, setImagePath] = useState("");
  const [imageWidth, setImageWidth] = useState(4);
  const [linkText, setLinkText] = useState("");
  const [linkUrl, setLinkUrl] = useState("");
  const [header, setHeader] = useState("");
  const [footer, setFooter] = useState("");
  const [orientation, setOrientation] = useState("portrait");

  useEffect(() => {
    const safeIndex = Math.min(paragraphIndex, Math.max(0, paragraphs.length - 1));
    const paragraph = paragraphs[safeIndex];
    if (!paragraph) return;
    setParagraphIndex(safeIndex);
    setText(String(paragraph.text ?? ""));
    setStyleName(String(paragraph.style || "Normal"));
    setAlignment(String(paragraph.alignment || "left"));
    const run = records(paragraph.runs)[0];
    setBold(Boolean(run?.bold));
    setItalic(Boolean(run?.italic));
    setUnderline(Boolean(run?.underline));
    setFontSize(Number(run?.font_size || 11));
    setColor(run?.color ? `#${String(run.color)}` : "#202124");
  }, [paragraphs, paragraphIndex]);

  useEffect(() => {
    const section = sections[0];
    if (!section) return;
    setHeader(String(section.header || ""));
    setFooter(String(section.footer || ""));
    setOrientation(String(section.orientation || "portrait"));
  }, [sections]);

  function selectParagraph(index: number) {
    setParagraphIndex(index);
    const paragraph = paragraphs[index];
    if (!paragraph) return;
    setText(String(paragraph.text ?? ""));
    setStyleName(String(paragraph.style || "Normal"));
    setAlignment(String(paragraph.alignment || "left"));
    const run = records(paragraph.runs)[0];
    setBold(Boolean(run?.bold));
    setItalic(Boolean(run?.italic));
    setUnderline(Boolean(run?.underline));
    setFontSize(Number(run?.font_size || 11));
    setColor(run?.color ? `#${String(run.color)}` : "#202124");
  }

  async function send(operations: Operation[], mode: "preview" | "edit", success?: string) {
    setStatus(mode === "preview" ? "Preparing Word preview…" : "Applying Word change…");
    try {
      const response = await request<Record<string, unknown>>(`/projects/${projectId}/office`, {
        method: "POST",
        body: JSON.stringify({ kind: mode, path: selectedPath, title: "", content: "", data: operations }),
      });
      const after = response.after;
      if (after && typeof after === "object" && !Array.isArray(after)) onPreviewChanged(after as Preview);
      if (mode === "preview") {
        setStatus(success || "Preview generated. The DOCX file has not been changed.");
      } else {
        const backup = String(response.backup_path || "");
        setStatus(success || (backup ? `Applied. Backup: ${backup}` : "Applied with Office history backup."));
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  function paragraphOperations(): Operation[] {
    const operations: Operation[] = [{
      action: "set_paragraph",
      paragraph_index: paragraphIndex,
      text,
      style: styleName,
      alignment,
    }];
    if (text.length > 0) {
      operations.push({
        action: "set_run",
        paragraph_index: paragraphIndex,
        run_index: 0,
        bold,
        italic,
        underline,
        font_size: fontSize,
        color: color.replace("#", ""),
      });
    }
    return operations;
  }

  const section = sections[0];

  return <section className={styles.studio}>
    <div>
      <p className="eyebrow">Word Studio · Office 0.2</p>
      <h3>Edit {selectedPath}</h3>
    </div>

    <div className={styles.toolbar}>
      <select aria-label="Paragraph style" value={styleName} onChange={(event) => setStyleName(event.target.value)}>
        {["Normal", "Title", "Subtitle", "Heading 1", "Heading 2", "Heading 3", "List Bullet", "List Number"].map((name) => <option key={name}>{name}</option>)}
      </select>
      <button type="button" className={bold ? styles.active : ""} onClick={() => setBold((value) => !value)}><strong>B</strong></button>
      <button type="button" className={italic ? styles.active : ""} onClick={() => setItalic((value) => !value)}><em>I</em></button>
      <button type="button" className={underline ? styles.active : ""} onClick={() => setUnderline((value) => !value)}><u>U</u></button>
      <input aria-label="Font size" type="number" min={6} max={72} value={fontSize} onChange={(event) => setFontSize(Number(event.target.value))} />
      <input aria-label="Text color" type="color" value={color} onChange={(event) => setColor(event.target.value)} />
      <select aria-label="Alignment" value={alignment} onChange={(event) => setAlignment(event.target.value)}>
        <option value="left">Left</option><option value="center">Centre</option><option value="right">Right</option><option value="justify">Justify</option>
      </select>
    </div>

    <div className={styles.workspace}>
      <div className={styles.canvas}>
        <div className={styles.page}>
          {paragraphs.map((paragraph, index) => {
            const runs = records(paragraph.runs);
            return <button
              type="button"
              key={index}
              className={`${styles.paragraph} ${paragraphClass(String(paragraph.style || ""))} ${paragraphIndex === index ? styles.selected : ""}`}
              style={{ textAlign: textAlign(paragraph.alignment) }}
              onClick={() => selectParagraph(index)}
            >
              {runs.length ? runs.map((run, runIndex) => <span key={runIndex} style={{
                fontWeight: run.bold ? 700 : undefined,
                fontStyle: run.italic ? "italic" : undefined,
                textDecoration: run.underline ? "underline" : undefined,
                fontFamily: run.font_name ? String(run.font_name) : undefined,
                fontSize: run.font_size ? `${Number(run.font_size)}pt` : undefined,
                color: run.color ? `#${String(run.color)}` : undefined,
              }}>{String(run.text ?? "")}</span>) : String(paragraph.text ?? "") || " "}
            </button>;
          })}

          {tables.map((table, tableIndex) => <div className={styles.tablePreview} key={tableIndex}>
            <table><tbody>
              {(Array.isArray(table.rows) ? table.rows as unknown[][] : []).map((row, rowIndex) => <tr key={rowIndex}>
                {row.map((value, columnIndex) => <td key={columnIndex}>{String(value ?? "")}</td>)}
              </tr>)}
            </tbody></table>
          </div>)}
        </div>
      </div>

      <aside className={styles.sidebar}>
        <div className={styles.card}>
          <h4>Document</h4>
          <div>Paragraphs: {paragraphs.length}</div>
          <div>Tables: {tables.length}</div>
          <div>Images: {Array.isArray(preview.inline_shapes) ? preview.inline_shapes.length : 0}</div>
          {section && <div>{String(section.orientation || "portrait")} · {String(section.page_width_inches || "?")} × {String(section.page_height_inches || "?")} in</div>}
        </div>

        <div className={styles.card}>
          <h4>Add paragraph</h4>
          <label>Style<select value={newParagraphStyle} onChange={(event) => setNewParagraphStyle(event.target.value)}><option>Normal</option><option>Heading 1</option><option>Heading 2</option><option>List Bullet</option><option>List Number</option></select></label>
          <label>Text<textarea value={newParagraph} onChange={(event) => setNewParagraph(event.target.value)} /></label>
          <button type="button" onClick={() => send([{ action: "append_paragraph", text: newParagraph, style: newParagraphStyle }], "edit", "Paragraph added with history backup.")}>Add paragraph</button>
        </div>

        <div className={styles.card}>
          <h4>Insert table</h4>
          <label>Rows<input type="number" min={1} max={30} value={tableRows} onChange={(event) => setTableRows(Number(event.target.value))} /></label>
          <label>Columns<input type="number" min={1} max={20} value={tableColumns} onChange={(event) => setTableColumns(Number(event.target.value))} /></label>
          <button type="button" onClick={() => send([{ action: "add_table", rows: tableRows, columns: tableColumns, style: "Table Grid" }], "edit", "Table added with history backup.")}>Add table</button>
        </div>

        <div className={styles.card}>
          <h4>Insert image</h4>
          <label>Project image path<input value={imagePath} onChange={(event) => setImagePath(event.target.value)} placeholder="docs/image.png" /></label>
          <label>Width (inches)<input type="number" min={0.5} max={10} step={0.25} value={imageWidth} onChange={(event) => setImageWidth(Number(event.target.value))} /></label>
          <button type="button" onClick={() => send([{ action: "add_image", image_path: imagePath, width_inches: imageWidth, paragraph_index: paragraphIndex }], "preview", "Image preview generated; source DOCX unchanged.")}>Preview image</button>
          <button type="button" onClick={() => send([{ action: "add_image", image_path: imagePath, width_inches: imageWidth, paragraph_index: paragraphIndex }], "edit", "Image inserted with history backup.")}>Insert image</button>
        </div>

        <div className={styles.card}>
          <h4>Add link</h4>
          <label>Text<input value={linkText} onChange={(event) => setLinkText(event.target.value)} /></label>
          <label>URL<input value={linkUrl} onChange={(event) => setLinkUrl(event.target.value)} placeholder="https://…" /></label>
          <button type="button" onClick={() => send([{ action: "add_hyperlink", paragraph_index: paragraphIndex, text: linkText, url: linkUrl }], "edit", "Link inserted with history backup.")}>Insert link</button>
        </div>

        <div className={styles.card}>
          <h4>Page and section</h4>
          <label>Orientation<select value={orientation} onChange={(event) => setOrientation(event.target.value)}><option value="portrait">Portrait</option><option value="landscape">Landscape</option></select></label>
          <button type="button" onClick={() => send([{ action: "set_section", section_index: 0, orientation }], "edit", "Page orientation updated with history backup.")}>Apply orientation</button>
          <label>Header<input value={header} onChange={(event) => setHeader(event.target.value)} /></label>
          <button type="button" onClick={() => send([{ action: "set_header", section_index: 0, text: header }], "edit", "Header updated with history backup.")}>Save header</button>
          <label>Footer<input value={footer} onChange={(event) => setFooter(event.target.value)} /></label>
          <button type="button" onClick={() => send([{ action: "set_footer", section_index: 0, text: footer }], "edit", "Footer updated with history backup.")}>Save footer</button>
        </div>
      </aside>
    </div>

    <div className={styles.editor}>
      <label>Selected paragraph {paragraphIndex + 1}<textarea value={text} onChange={(event) => setText(event.target.value)} /></label>
      <div className={styles.actions}>
        <button type="button" onClick={() => send(paragraphOperations(), "preview")}>Preview paragraph change</button>
        <button type="button" className="primary" onClick={() => send(paragraphOperations(), "edit")}>Apply paragraph change</button>
        <button type="button" onClick={() => send([{ action: "insert_paragraph_after", paragraph_index: paragraphIndex, text: "New paragraph", style: "Normal" }], "edit", "Paragraph inserted with history backup.")}>Insert after</button>
        {paragraphs.length > 1 && <button type="button" onClick={() => send([{ action: "delete_paragraph", paragraph_index: paragraphIndex }], "edit", "Paragraph deleted with history backup.")}>Delete paragraph</button>}
        <span>{status}</span>
      </div>
    </div>
  </section>;
}
