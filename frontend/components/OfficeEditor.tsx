"use client";

import { PresentationStudio } from "./PresentationStudio";
import { SpreadsheetStudio } from "./SpreadsheetStudio";
import { WordStudio } from "./WordStudio";

type OfficePreview = Record<string, unknown>;

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

  if (kind === "word") {
    return <WordStudio projectId={projectId} selectedPath={selectedPath} preview={preview} onPreviewChanged={onPreviewChanged} />;
  }
  if (kind === "excel") {
    return <SpreadsheetStudio projectId={projectId} selectedPath={selectedPath} preview={preview} onPreviewChanged={onPreviewChanged} />;
  }
  if (kind === "powerpoint") {
    return <PresentationStudio projectId={projectId} selectedPath={selectedPath} preview={preview} onPreviewChanged={onPreviewChanged} />;
  }

  return <section className="office-create">
    <p className="eyebrow">Structured editor</p>
    <h3>Read-only preview</h3>
    <p>Editing is currently available for DOCX, XLSX and PPTX files. PDF remains read-only.</p>
  </section>;
}
