"use client";

import { CSSProperties, useEffect, useMemo, useState } from "react";
import { request } from "../lib/api";
import styles from "./SpreadsheetStudio.module.css";

type Preview = Record<string, unknown>;
type Operation = Record<string, unknown>;

function records(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object") : [];
}

function columnName(index: number): string {
  let value = index + 1;
  let letters = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    letters = String.fromCharCode(65 + remainder) + letters;
    value = Math.floor((value - 1) / 26);
  }
  return letters;
}

function cellAddress(row: number, column: number): string {
  return `${columnName(column)}${row + 1}`;
}

function colour(value: unknown, fallback: string): string {
  const text = String(value || "").replace(/^00/, "").replace(/^FF/, "");
  return /^[0-9A-Fa-f]{6}$/.test(text) ? `#${text}` : fallback;
}

export function SpreadsheetStudio({
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
  const sheets = useMemo(() => records(preview.sheets), [preview]);
  const [sheetName, setSheetName] = useState("");
  const [cell, setCell] = useState("A1");
  const [value, setValue] = useState("");
  const [bold, setBold] = useState(false);
  const [italic, setItalic] = useState(false);
  const [wrap, setWrap] = useState(false);
  const [fontSize, setFontSize] = useState(11);
  const [fontColor, setFontColor] = useState("#15233a");
  const [fillColor, setFillColor] = useState("#ffffff");
  const [horizontal, setHorizontal] = useState("general");
  const [numberFormat, setNumberFormat] = useState("General");
  const [status, setStatus] = useState("");
  const [newSheetName, setNewSheetName] = useState("Summary");
  const [range, setRange] = useState("A1:B3");
  const [tableName, setTableName] = useState("Table1");
  const [rowIndex, setRowIndex] = useState(2);
  const [columnIndex, setColumnIndex] = useState(2);

  const sheet = useMemo(() => sheets.find((item) => String(item.name) === sheetName) || sheets[0], [sheets, sheetName]);
  const rows = useMemo(() => Array.isArray(sheet?.rows) ? sheet.rows as unknown[][] : [], [sheet]);
  const details = useMemo(() => records(sheet?.cells), [sheet]);
  const detailMap = useMemo(() => new Map(details.map((item) => [String(item.cell), item])), [details]);

  useEffect(() => {
    if (!sheetName && sheets[0]) setSheetName(String(sheets[0].name || ""));
    if (sheetName && !sheets.some((item) => String(item.name) === sheetName) && sheets[0]) setSheetName(String(sheets[0].name || ""));
  }, [sheets, sheetName]);

  useEffect(() => {
    loadCell(cell);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sheetName, preview]);

  function loadCell(address: string) {
    const normalized = address.toUpperCase();
    setCell(normalized);
    const detail = detailMap.get(normalized);
    if (detail) {
      setValue(String(detail.value ?? ""));
      setBold(Boolean(detail.bold));
      setItalic(Boolean(detail.italic));
      setWrap(Boolean(detail.wrap_text));
      setFontSize(Number(detail.font_size || 11));
      setFontColor(colour(detail.font_color, "#15233a"));
      setFillColor(colour(detail.fill_color, "#ffffff"));
      setHorizontal(String(detail.horizontal || "general"));
      setNumberFormat(String(detail.number_format || "General"));
      return;
    }
    const match = normalized.match(/^([A-Z]+)(\d+)$/);
    if (match) {
      let column = 0;
      for (const letter of match[1]) column = column * 26 + letter.charCodeAt(0) - 64;
      const row = Number(match[2]);
      setValue(String(rows[row - 1]?.[column - 1] ?? ""));
    } else setValue("");
    setBold(false); setItalic(false); setWrap(false); setFontSize(11); setFontColor("#15233a"); setFillColor("#ffffff"); setHorizontal("general"); setNumberFormat("General");
  }

  async function send(operations: Operation[], mode: "preview" | "edit", success?: string) {
    setStatus(mode === "preview" ? "Preparing spreadsheet preview…" : "Applying spreadsheet change…");
    try {
      const response = await request<Record<string, unknown>>(`/projects/${projectId}/office`, {
        method: "POST",
        body: JSON.stringify({ kind: mode, path: selectedPath, title: "", content: "", data: operations }),
      });
      const after = response.after;
      if (after && typeof after === "object" && !Array.isArray(after)) onPreviewChanged(after as Preview);
      if (mode === "preview") setStatus(success || "Preview generated. The XLSX file has not been changed.");
      else {
        const backup = String(response.backup_path || "");
        setStatus(success || (backup ? `Applied. Backup: ${backup}` : "Applied with Office history backup."));
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  const maxColumns = Math.max(12, Math.min(24, Number(sheet?.max_column || 12)));
  const visibleRows = Math.max(25, Math.min(80, Number(sheet?.max_row || 25)));

  function cellStyle(address: string): CSSProperties {
    const detail = detailMap.get(address);
    if (!detail) return {};
    return {
      fontWeight: detail.bold ? 700 : undefined,
      fontStyle: detail.italic ? "italic" : undefined,
      fontSize: detail.font_size ? `${Number(detail.font_size)}pt` : undefined,
      color: colour(detail.font_color, "#15233a"),
      background: colour(detail.fill_color, "#ffffff"),
      textAlign: ["left", "center", "right", "justify"].includes(String(detail.horizontal)) ? String(detail.horizontal) as CSSProperties["textAlign"] : undefined,
      whiteSpace: detail.wrap_text ? "normal" : undefined,
    };
  }

  return <section className={styles.studio}>
    <div><p className="eyebrow">Spreadsheet Studio · Office 0.3</p><h3>Edit {selectedPath}</h3></div>

    <div className={styles.sheetTabs}>
      {sheets.map((item) => <button type="button" key={String(item.name)} className={sheetName === String(item.name) ? styles.active : ""} onClick={() => { setSheetName(String(item.name)); setCell("A1"); }}>{String(item.name)}</button>)}
    </div>

    <div className={styles.toolbar}>
      <button type="button" className={bold ? styles.active : ""} onClick={() => setBold((item) => !item)}><strong>B</strong></button>
      <button type="button" className={italic ? styles.active : ""} onClick={() => setItalic((item) => !item)}><em>I</em></button>
      <button type="button" className={wrap ? styles.active : ""} onClick={() => setWrap((item) => !item)}>Wrap</button>
      <input aria-label="Font size" type="number" min={6} max={72} value={fontSize} onChange={(event) => setFontSize(Number(event.target.value))} />
      <input aria-label="Font colour" type="color" value={fontColor} onChange={(event) => setFontColor(event.target.value)} />
      <input aria-label="Fill colour" type="color" value={fillColor} onChange={(event) => setFillColor(event.target.value)} />
      <select value={horizontal} onChange={(event) => setHorizontal(event.target.value)}><option value="general">General</option><option value="left">Left</option><option value="center">Centre</option><option value="right">Right</option></select>
      <input value={numberFormat} onChange={(event) => setNumberFormat(event.target.value)} placeholder="Number format" />
      <button type="button" onClick={() => send([{ action: "set_cell_format", sheet: sheetName, cell, bold, italic, wrap_text: wrap, font_size: fontSize, font_color: fontColor, fill_color: fillColor, horizontal, number_format: numberFormat }], "preview")}>Preview format</button>
      <button type="button" onClick={() => send([{ action: "set_cell_format", sheet: sheetName, cell, bold, italic, wrap_text: wrap, font_size: fontSize, font_color: fontColor, fill_color: fillColor, horizontal, number_format: numberFormat }], "edit", "Cell formatting applied with history backup.")}>Apply format</button>
    </div>

    <div className={styles.formulaBar}>
      <input aria-label="Cell address" value={cell} onChange={(event) => setCell(event.target.value.toUpperCase())} onBlur={() => loadCell(cell)} />
      <input aria-label="Cell value or formula" value={value} onChange={(event) => setValue(event.target.value)} placeholder="Value or =formula" />
      <button type="button" onClick={() => send([{ action: "set_cell", sheet: sheetName, cell, value }], "preview")}>Preview</button>
      <button type="button" className="primary" onClick={() => send([{ action: "set_cell", sheet: sheetName, cell, value }], "edit")}>Apply</button>
    </div>

    <div className={styles.gridWrap}>
      <table className={styles.grid}>
        <thead><tr><th></th>{Array.from({ length: maxColumns }, (_, column) => <th key={column}>{columnName(column)}</th>)}</tr></thead>
        <tbody>
          {Array.from({ length: visibleRows }, (_, rowIndexValue) => <tr key={rowIndexValue}>
            <th>{rowIndexValue + 1}</th>
            {Array.from({ length: maxColumns }, (_, columnIndexValue) => {
              const address = cellAddress(rowIndexValue, columnIndexValue);
              const raw = rows[rowIndexValue]?.[columnIndexValue];
              return <td key={address}><button type="button" className={`${styles.cell} ${cell === address ? styles.selected : ""}`} style={cellStyle(address)} onClick={() => loadCell(address)}>{String(raw ?? "")}</button></td>;
            })}
          </tr>)}
        </tbody>
      </table>
    </div>

    <div className={styles.lower}>
      <div className={styles.card}>
        <h4>Sheet controls</h4>
        <div className={styles.meta}>
          <span>Rows: {String(sheet?.max_row || 0)}</span><span>Columns: {String(sheet?.max_column || 0)}</span><span>Formulas: {Array.isArray(sheet?.formulas) ? sheet.formulas.length : 0}</span>
          <span>Merges: {Array.isArray(sheet?.merged_ranges) ? sheet.merged_ranges.length : 0}</span><span>Freeze: {String(sheet?.freeze_panes || "none")}</span><span>Tables: {Array.isArray(sheet?.tables) ? sheet.tables.length : 0}</span>
        </div>
        <label>Row index<input type="number" min={1} value={rowIndex} onChange={(event) => setRowIndex(Number(event.target.value))} /></label>
        <button type="button" onClick={() => send([{ action: "insert_rows", sheet: sheetName, index: rowIndex, amount: 1 }], "edit", "Row inserted with history backup.")}>Insert row</button>
        <button type="button" onClick={() => send([{ action: "delete_rows", sheet: sheetName, index: rowIndex, amount: 1 }], "edit", "Row deleted with history backup.")}>Delete row</button>
        <label>Column index<input type="number" min={1} value={columnIndex} onChange={(event) => setColumnIndex(Number(event.target.value))} /></label>
        <button type="button" onClick={() => send([{ action: "insert_columns", sheet: sheetName, index: columnIndex, amount: 1 }], "edit", "Column inserted with history backup.")}>Insert column</button>
        <button type="button" onClick={() => send([{ action: "delete_columns", sheet: sheetName, index: columnIndex, amount: 1 }], "edit", "Column deleted with history backup.")}>Delete column</button>
        <button type="button" onClick={() => send([{ action: "freeze_panes", sheet: sheetName, cell }], "edit", "Freeze panes updated with history backup.")}>Freeze at {cell}</button>
      </div>

      <aside className={styles.card}>
        <h4>Workbook tools</h4>
        <label>Sheet name<input value={newSheetName} onChange={(event) => setNewSheetName(event.target.value)} /></label>
        <button type="button" onClick={() => send([{ action: "add_sheet", name: newSheetName }], "edit", "Worksheet added with history backup.")}>Add sheet</button>
        <button type="button" onClick={() => send([{ action: "rename_sheet", sheet: sheetName, name: newSheetName }], "edit", "Worksheet renamed with history backup.")}>Rename current</button>
        {sheets.length > 1 && <button type="button" onClick={() => send([{ action: "delete_sheet", sheet: sheetName }], "edit", "Worksheet deleted with history backup.")}>Delete current</button>}
        <label>Range<input value={range} onChange={(event) => setRange(event.target.value.toUpperCase())} placeholder="A1:B5" /></label>
        <button type="button" onClick={() => send([{ action: "merge_cells", sheet: sheetName, range }], "edit", "Cells merged with history backup.")}>Merge range</button>
        <button type="button" onClick={() => send([{ action: "unmerge_cells", sheet: sheetName, range }], "edit", "Cells unmerged with history backup.")}>Unmerge range</button>
        <label>Table name<input value={tableName} onChange={(event) => setTableName(event.target.value)} /></label>
        <button type="button" onClick={() => send([{ action: "add_table", sheet: sheetName, range, name: tableName, style: "TableStyleMedium2" }], "edit", "Excel table created with history backup.")}>Create table from range</button>
        <button type="button" onClick={() => send([{ action: "set_auto_filter", sheet: sheetName, range }], "edit", "AutoFilter updated with history backup.")}>Set filter range</button>
      </aside>
    </div>

    <div className={styles.status}>{status}</div>
  </section>;
}
