"use client";

import { CSSProperties, useEffect, useMemo, useState } from "react";
import { request } from "../lib/api";
import styles from "./PresentationStudio.module.css";

type Preview = Record<string, unknown>;
type Operation = Record<string, unknown>;

function records(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object") : [];
}

function colour(value: unknown, fallback: string): string {
  const text = String(value || "").replace(/^00/, "").replace(/^FF/, "");
  return /^[0-9A-Fa-f]{6}$/.test(text) ? `#${text}` : fallback;
}

export function PresentationStudio({
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
  const slides = useMemo(() => records(preview.slides), [preview]);
  const layouts = useMemo(() => records(preview.layouts), [preview]);
  const slideWidth = Number(preview.slide_width_inches || 13.333);
  const slideHeight = Number(preview.slide_height_inches || 7.5);
  const [slideIndex, setSlideIndex] = useState(0);
  const [shapeIndex, setShapeIndex] = useState(0);
  const [text, setText] = useState("");
  const [left, setLeft] = useState(1);
  const [top, setTop] = useState(1);
  const [width, setWidth] = useState(4);
  const [height, setHeight] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [fillColor, setFillColor] = useState("#ffffff");
  const [lineColor, setLineColor] = useState("#64748b");
  const [fontColor, setFontColor] = useState("#15233a");
  const [fontSize, setFontSize] = useState(18);
  const [status, setStatus] = useState("");
  const [layoutIndex, setLayoutIndex] = useState(1);
  const [newTitle, setNewTitle] = useState("New slide");
  const [newContent, setNewContent] = useState("");
  const [imagePath, setImagePath] = useState("");
  const [shapeType, setShapeType] = useState("rectangle");
  const [background, setBackground] = useState("#ffffff");

  const slide = slides[Math.min(slideIndex, Math.max(0, slides.length - 1))];
  const shapes = useMemo(() => records(slide?.shapes), [slide]);

  useEffect(() => {
    const safeSlide = Math.min(slideIndex, Math.max(0, slides.length - 1));
    if (safeSlide !== slideIndex) setSlideIndex(safeSlide);
    const nextShapes = records(slides[safeSlide]?.shapes);
    const safeShape = Math.min(shapeIndex, Math.max(0, nextShapes.length - 1));
    if (safeShape !== shapeIndex) setShapeIndex(safeShape);
    loadShape(nextShapes[safeShape]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview, slideIndex, shapeIndex]);

  function loadShape(shape?: Record<string, unknown>) {
    if (!shape) {
      setText(""); setLeft(1); setTop(1); setWidth(4); setHeight(1); setRotation(0); return;
    }
    setText(String(shape.text || ""));
    setLeft(Number(shape.left_inches || 0));
    setTop(Number(shape.top_inches || 0));
    setWidth(Number(shape.width_inches || 1));
    setHeight(Number(shape.height_inches || 1));
    setRotation(Number(shape.rotation || 0));
    setFillColor(colour(shape.fill_color, "#ffffff"));
    setLineColor(colour(shape.line_color, "#64748b"));
    const firstParagraph = records(shape.paragraphs)[0];
    const firstRun = records(firstParagraph?.runs)[0];
    setFontSize(Number(firstRun?.font_size || 18));
  }

  function selectSlide(index: number) {
    setSlideIndex(index);
    setShapeIndex(0);
    const nextShapes = records(slides[index]?.shapes);
    loadShape(nextShapes[0]);
  }

  function selectShape(index: number) {
    setShapeIndex(index);
    loadShape(shapes[index]);
  }

  async function send(operations: Operation[], mode: "preview" | "edit", success?: string) {
    setStatus(mode === "preview" ? "Preparing presentation preview…" : "Applying presentation change…");
    try {
      const response = await request<Record<string, unknown>>(`/projects/${projectId}/office`, {
        method: "POST",
        body: JSON.stringify({ kind: mode, path: selectedPath, title: "", content: "", data: operations }),
      });
      const after = response.after;
      if (after && typeof after === "object" && !Array.isArray(after)) onPreviewChanged(after as Preview);
      if (mode === "preview") setStatus(success || "Preview generated. The PPTX file has not been changed.");
      else {
        const backup = String(response.backup_path || "");
        setStatus(success || (backup ? `Applied. Backup: ${backup}` : "Applied with Office history backup."));
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  }

  function shapeStyle(shape: Record<string, unknown>): CSSProperties {
    return {
      left: `${(Number(shape.left_inches || 0) / slideWidth) * 100}%`,
      top: `${(Number(shape.top_inches || 0) / slideHeight) * 100}%`,
      width: `${(Number(shape.width_inches || 1) / slideWidth) * 100}%`,
      height: `${(Number(shape.height_inches || 1) / slideHeight) * 100}%`,
      transform: `rotate(${Number(shape.rotation || 0)}deg)`,
      background: shape.fill_color ? colour(shape.fill_color, "transparent") : undefined,
      borderColor: shape.line_color ? colour(shape.line_color, "transparent") : undefined,
    };
  }

  return <section className={styles.studio}>
    <div><p className="eyebrow">Presentation Studio · Office 0.4</p><h3>Edit {selectedPath}</h3></div>

    <div className={styles.toolbar}>
      <input type="number" step={0.1} value={left} onChange={(event) => setLeft(Number(event.target.value))} aria-label="Left" />
      <input type="number" step={0.1} value={top} onChange={(event) => setTop(Number(event.target.value))} aria-label="Top" />
      <input type="number" step={0.1} value={width} onChange={(event) => setWidth(Number(event.target.value))} aria-label="Width" />
      <input type="number" step={0.1} value={height} onChange={(event) => setHeight(Number(event.target.value))} aria-label="Height" />
      <input type="number" step={1} value={rotation} onChange={(event) => setRotation(Number(event.target.value))} aria-label="Rotation" />
      <input type="color" value={fillColor} onChange={(event) => setFillColor(event.target.value)} aria-label="Fill colour" />
      <input type="color" value={lineColor} onChange={(event) => setLineColor(event.target.value)} aria-label="Line colour" />
      <input type="color" value={fontColor} onChange={(event) => setFontColor(event.target.value)} aria-label="Font colour" />
      <input type="number" min={6} max={96} value={fontSize} onChange={(event) => setFontSize(Number(event.target.value))} aria-label="Font size" />
      <button type="button" onClick={() => send([
        { action: "set_shape_position", slide_index: slideIndex, shape_index: shapeIndex, left, top, width, height, rotation },
        { action: "set_shape_style", slide_index: slideIndex, shape_index: shapeIndex, fill_color: fillColor, line_color: lineColor, font_color: fontColor, font_size: fontSize },
      ], "preview")}>Preview shape</button>
      <button type="button" onClick={() => send([
        { action: "set_shape_position", slide_index: slideIndex, shape_index: shapeIndex, left, top, width, height, rotation },
        { action: "set_shape_style", slide_index: slideIndex, shape_index: shapeIndex, fill_color: fillColor, line_color: lineColor, font_color: fontColor, font_size: fontSize },
      ], "edit", "Shape geometry/style applied with history backup.")}>Apply shape</button>
    </div>

    <div className={styles.layout}>
      <aside className={styles.thumbRail}>
        {slides.map((item, index) => <button type="button" key={index} className={`${styles.thumb} ${slideIndex === index ? styles.active : ""}`} onClick={() => selectSlide(index)}>
          <div className={styles.thumbSlide}>{records(item.shapes).map((shape, shapeIndexValue) => <div key={shapeIndexValue}>{String(shape.text || shape.name || "Shape").slice(0, 50)}</div>)}</div>
          Slide {index + 1}
        </button>)}
      </aside>

      <div className={styles.canvasWrap}>
        <div className={styles.canvas}>
          {shapes.map((shape, index) => <button type="button" key={index} className={`${styles.shape} ${shapeIndex === index ? styles.selected : ""}`} style={shapeStyle(shape)} onClick={() => selectShape(index)}>
            {String(shape.text || shape.name || "Shape")}
          </button>)}
        </div>
      </div>

      <aside className={styles.sidebar}>
        <div className={styles.card}>
          <h4>Selected shape</h4>
          <label>Text<textarea value={text} onChange={(event) => setText(event.target.value)} /></label>
          <button type="button" onClick={() => send([{ action: "set_shape_text", slide_index: slideIndex, shape_index: shapeIndex, text }], "preview")}>Preview text</button>
          <button type="button" onClick={() => send([{ action: "set_shape_text", slide_index: slideIndex, shape_index: shapeIndex, text }], "edit", "Shape text updated with history backup.")}>Apply text</button>
        </div>

        <div className={styles.card}>
          <h4>Slide</h4>
          <label>Layout<select value={layoutIndex} onChange={(event) => setLayoutIndex(Number(event.target.value))}>{layouts.map((layout) => <option key={String(layout.index)} value={Number(layout.index)}>{String(layout.name)}</option>)}</select></label>
          <label>Title<input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} /></label>
          <label>Content<textarea value={newContent} onChange={(event) => setNewContent(event.target.value)} /></label>
          <button type="button" onClick={() => send([{ action: "add_slide", layout_index: layoutIndex, title: newTitle, content: newContent }], "edit", "Slide added with history backup.")}>Add slide</button>
          {slides.length > 1 && <button type="button" onClick={() => send([{ action: "delete_slide", slide_index: slideIndex }], "edit", "Slide deleted with history backup.")}>Delete slide</button>}
          {slideIndex > 0 && <button type="button" onClick={() => send([{ action: "reorder_slide", slide_index: slideIndex, target_index: slideIndex - 1 }], "edit", "Slide moved with history backup.")}>Move up</button>}
          {slideIndex < slides.length - 1 && <button type="button" onClick={() => send([{ action: "reorder_slide", slide_index: slideIndex, target_index: slideIndex + 1 }], "edit", "Slide moved with history backup.")}>Move down</button>}
          <label>Background<input type="color" value={background} onChange={(event) => setBackground(event.target.value)} /></label>
          <button type="button" onClick={() => send([{ action: "set_slide_background", slide_index: slideIndex, color: background }], "edit", "Slide background updated with history backup.")}>Apply background</button>
        </div>

        <div className={styles.card}>
          <h4>Insert</h4>
          <button type="button" onClick={() => send([{ action: "add_textbox", slide_index: slideIndex, left: 1, top: 1, width: 4, height: 1, text: "New text" }], "edit", "Textbox added with history backup.")}>Add textbox</button>
          <label>Shape<select value={shapeType} onChange={(event) => setShapeType(event.target.value)}><option value="rectangle">Rectangle</option><option value="rounded_rectangle">Rounded rectangle</option><option value="oval">Oval</option><option value="chevron">Chevron</option><option value="right_arrow">Right arrow</option><option value="hexagon">Hexagon</option></select></label>
          <button type="button" onClick={() => send([{ action: "add_shape", slide_index: slideIndex, shape: shapeType, left: 1, top: 2, width: 2.5, height: 1.2, text: "Shape", fill_color: fillColor }], "edit", "Shape added with history backup.")}>Add shape</button>
          <label>Project image path<input value={imagePath} onChange={(event) => setImagePath(event.target.value)} placeholder="docs/image.png" /></label>
          <button type="button" onClick={() => send([{ action: "add_image", slide_index: slideIndex, image_path: imagePath, left: 1, top: 1, width: 4 }], "preview", "Image preview generated; source PPTX unchanged.")}>Preview image</button>
          <button type="button" onClick={() => send([{ action: "add_image", slide_index: slideIndex, image_path: imagePath, left: 1, top: 1, width: 4 }], "edit", "Image added with history backup.")}>Insert image</button>
        </div>
      </aside>
    </div>

    <div className={styles.status}>{status}</div>
  </section>;
}
