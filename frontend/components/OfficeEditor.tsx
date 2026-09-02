"use client";

import { useEffect, useMemo, useState } from "react";
import { request } from "../lib/api";
import { SpreadsheetStudio } from "./SpreadsheetStudio";
import { WordStudio } from "./WordStudio";

type OfficePreview = Record<string, unknown>;

function records(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object") : [];
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
  const slides = useMemo(() => records(preview.slides), [preview]);
  const [slideIndex, setSlideIndex] = useState(0);
  const [shapeIndex, setShapeIndex] = useState(0);
  const [text, setText] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    setStatus("");
    if (kind === "powerpoint") {
      setSlideIndex(0);
      const shapes = records(slides[0]?.shapes);
      const firstTextShape = Math.max(0, shapes.findIndex((shape) => typeof shape.text === "string"));
      setShapeIndex(firstTextShape);
      setText(String(shapes[firstTextShape]?.text ?? ""));
    }
  }, [kind, slides, selectedPath]);

  if (kind === "word") return <WordStudio projectId={projectId} selectedPath={selectedPath} preview={preview} onPreviewChanged={onPreviewChanged} />;
  if (kind === "excel") return <SpreadsheetStudio projectId={projectId} selectedPath={selectedPath} preview={preview} onPreviewChanged={onPreviewChanged} />;

  function selectShape(nextSlide: number, nextShape: number, value: unknown) {
    setSlideIndex(nextSlide);
    setShapeIndex(nextShape);
    setText(String(value ?? ""));
  }

  async function submit(mode: "preview" | "edit") {
    setStatus(mode === "preview" ? "Preparing preview…" : "Applying change…");
    try {
      const response = await request<Record<string, unknown>>(`/projects/${projectId}/office`, {
        method: "POST",
        body: JSON.stringify({ kind: mode, path: selectedPath, title: "", content: "", data: [{ action: "set_shape_text", slide_index: slideIndex, shape_index: shapeIndex, text }] }),
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

  if (!selectedPath || kind !== "powerpoint") {
    return <section className="office-create"><p className="eyebrow">Structured editor</p><h3>Read-only preview</h3><p>Editing is currently available for DOCX, XLSX and PPTX files.</p></section>;
  }

  return <section className="office-create">
    <p className="eyebrow">Structured editor</p>
    <h3>Edit PowerPoint</h3>
    <div className="office-preview">
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
    </div>
    <label>Text<textarea value={text} onChange={(event) => setText(event.target.value)} /></label>
    <div className="segmented">
      <button type="button" onClick={() => submit("preview")}>Preview change</button>
      <button type="button" className="primary" onClick={() => submit("edit")}>Apply change</button>
    </div>
    <span className="form-status">{status}</span>
  </section>;
}
