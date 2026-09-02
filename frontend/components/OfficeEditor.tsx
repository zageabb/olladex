"use client";

import { useEffect, useMemo, useState } from "react";
import { request } from "../lib/api";
import { WordStudio } from "./WordStudio";

type OfficePreview = Record<string, unknown>;
type OfficeOperation = Record<string, unknown>;

function records(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object") : [];
}

function cellName(row: number, column: number): string {
  let value = column + 1;
  let letters = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    letters = String.fromCharCode(65 + remainder) + letters;
    value = Math.floor((value - 1) / 26);
  }
  return `${letters}${row + 1}`;
}

export function OfficeEditor({
  projectId,
  selectedPath,
  preview,
  onPreviewChanged,
}: {
  projectId: number;
  selectedPath: string;
  preview: OfficePreview;
  onPreviewChanged: (preview: OfficePreview) => void;
}) {
  const kind = String(preview.kind || "");
  const sheets = useMemo(() => records(preview.sheets), [preview]);
  const slides = useMemo(() => records(preview.slides), [preview]);
  const [sheetName, setSheetName] = useState("");
  const [cell, setCell] = useState("A1");
  const [slideIndex, setSlideIndex] = useState(0);
  const [shapeIndex, setShapeIndex] = useState(0);
  const [text, setText] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    setStatus("");
    if (kind === "excel") {
      const first = sheets[0];
      const name = String(first?.name ?? "");
      setSheetName(name);
      setCell("A1");
      const rows = Array.isArray(first?.rows) ? first.rows as unknown[][] : [];
      setText(String(rows[0]?.[0] ?? ""));
    } else if (kind === "powerpoint") {
      setSlideIndex(0);
      const shapes = records(slides[0]?.shapes);
      const firstTextShape = Math.max(0, shapes.findIndex((shape) => typeof shape.text === "string"));
      setShapeIndex(firstTextShape);
      setText(String(shapes[firstTextShape]?.text ?? ""));
    }
  }, [kind, sheets, slides, selectedPath]);

  if (kind === "word") {
    return <WordStudio projectId={projectId} selectedPath={selectedPath} preview={preview} onPreviewChanged={onPreviewChanged} />;
  }

  function selectCell(nextSheet: string, address: string, value: unknown) {
    setSheetName(nextSheet);
    setCell(address);
    setText(String(value ?? ""));
  }

  function selectShape(nextSlide: number, nextShape: number, value: unknown) {
    setSlideIndex(nextSlide);
    setShapeIndex(nextShape);
    setText(String(value ?? ""));
  }

  function operation(): OfficeOperation {
    if (kind === "excel") return { action: "set_cell", sheet: sheetName, cell, value: text };
    if (kind === "powerpoint") return { action: "set_shape_text", slide_index: slideIndex, shape_index: shapeIndex, text };
    throw new Error("This Office file is read-only in the structured editor");
  }

  async function submit(mode: "preview" | "edit") {
    setStatus(mode === "preview" ? "Preparing preview…" : "Applying change…");
    try {
      const response = await request<Record<string, unknown>>(`/projects/${projectId}/office`, {
        method: "POST",
        body: JSON.stringify({ kind: mode, path: selectedPath, title: "", content: "", data: [operation()] }),
      });
      const after = response.after;
      if (after && typeof after === "object" && !Array.isArray(after)) onPreviewChanged(after as OfficePreview);
      if (mode === "preview") setStatus("Preview generated. The file has not been changed.");
      else {
        const backup = String(response.backup_path || "");
        setStatus(backup ? `Applied. Backup: ${backup}` : "Applied with history backup.");
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  if (!selectedPath || !["excel", "powerpoint"].includes(kind)) {
    return <section className="office-create"><p className="eyebrow">Structured editor</p><h3>Read-only preview</h3><p>Editing is currently available for DOCX, XLSX and PPTX files.</p></section>;
  }

  return <section className="office-create">
    <p className="eyebrow">Structured editor</p>
    <h3>Edit {kind === "excel" ? "Excel" : "PowerPoint"}</h3>

    {kind === "excel" && <>
      <label>Sheet
        <select value={sheetName} onChange={(event) => setSheetName(event.target.value)}>
          {sheets.map((sheet) => <option key={String(sheet.name)} value={String(sheet.name)}>{String(sheet.name)}</option>)}
        </select>
      </label>
      <label>Cell<input value={cell} onChange={(event) => setCell(event.target.value.toUpperCase())} /></label>
      <div className="office-preview">
        {sheets.filter((sheet) => String(sheet.name) === sheetName).map((sheet) => {
          const rows = Array.isArray(sheet.rows) ? sheet.rows as unknown[][] : [];
          return <div key={String(sheet.name)}>
            {rows.slice(0, 20).map((row, rowIndex) => <div key={rowIndex} className="segmented">
              {row.slice(0, 12).map((value, columnIndex) => {
                const address = cellName(rowIndex, columnIndex);
                return <button type="button" key={address} className={cell === address ? "active" : ""} onClick={() => selectCell(sheetName, address, value)}>{address}: {String(value ?? "")}</button>;
              })}
            </div>)}
          </div>;
        })}
      </div>
    </>}

    {kind === "powerpoint" && <div className="office-preview">
      {slides.map((slide, nextSlide) => <div key={nextSlide}>
        <strong>Slide {nextSlide + 1}</strong>
        <div className="segmented">
          {records(slide.shapes).map((shape, nextShape) => typeof shape.text === "string" ? <button
            type="button"
            key={`${nextSlide}-${nextShape}`}
            className={slideIndex === nextSlide && shapeIndex === nextShape ? "active" : ""}
            onClick={() => selectShape(nextSlide, nextShape, shape.text)}
          >{String(shape.name || `Shape ${nextShape + 1}`)}: {String(shape.text).slice(0, 70)}</button> : null)}
        </div>
      </div>)}
    </div>}

    <label>{kind === "excel" ? "Cell value" : "Text"}<textarea value={text} onChange={(event) => setText(event.target.value)} /></label>
    <div className="segmented">
      <button type="button" onClick={() => submit("preview")}>Preview change</button>
      <button type="button" className="primary" onClick={() => submit("edit")}>Apply change</button>
    </div>
    <span className="form-status">{status}</span>
  </section>;
}
