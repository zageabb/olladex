"use client";

import { FormEvent, useEffect, useState } from "react";
import { request } from "../lib/api";

export function OfficePanel({ projectId, selectedPath, onCreated }: { projectId: number; selectedPath?: string; onCreated: () => void }) {
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [kind, setKind] = useState<"docx" | "xlsx" | "pptx">("docx");
  const [path, setPath] = useState("docs/olladex-document.docx");
  const [title, setTitle] = useState("Olladex document");
  const [content, setContent] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    setPreview(null);
    if (selectedPath && /\.(docx|xlsx|pptx|pdf)$/i.test(selectedPath)) {
      request<Record<string, unknown>>(`/projects/${projectId}/office?path=${encodeURIComponent(selectedPath)}`).then(setPreview).catch((error) => setStatus(error.message));
    }
  }, [projectId, selectedPath]);

  function changeKind(next: "docx" | "xlsx" | "pptx") {
    setKind(next);
    setPath(`docs/olladex-${next === "docx" ? "document" : next === "xlsx" ? "workbook" : "presentation"}.${next}`);
  }

  async function create(event: FormEvent) {
    event.preventDefault(); setStatus("Creating…");
    try {
      await request(`/projects/${projectId}/office`, { method: "POST", body: JSON.stringify({ kind, path, title, content, data: kind === "xlsx" ? content.split("\n").map((row) => row.split(",")) : [] }) });
      setStatus(`Created ${path}`); onCreated();
    } catch (error) { setStatus(error instanceof Error ? error.message : String(error)); }
  }

  return <div className="office-panel">
    {preview && <section className="office-preview"><div className="office-badge">{String(preview.kind || "office")}</div><h3>{selectedPath}</h3><pre>{JSON.stringify(preview, null, 2)}</pre></section>}
    <section className="office-create"><p className="eyebrow">Create Office file</p><h3>New Word, Excel or PowerPoint file</h3>
      <form onSubmit={create}>
        <div className="segmented"><button type="button" className={kind === "docx" ? "active" : ""} onClick={() => changeKind("docx")}>Word</button><button type="button" className={kind === "xlsx" ? "active" : ""} onClick={() => changeKind("xlsx")}>Excel</button><button type="button" className={kind === "pptx" ? "active" : ""} onClick={() => changeKind("pptx")}>PowerPoint</button></div>
        <label>File path<input value={path} onChange={(e) => setPath(e.target.value)} /></label>
        <label>Title<input value={title} onChange={(e) => setTitle(e.target.value)} /></label>
        <label>{kind === "xlsx" ? "Comma-separated rows" : "Content"}<textarea value={content} onChange={(e) => setContent(e.target.value)} /></label>
        <button className="primary">Create {kind.toUpperCase()}</button><span className="form-status">{status}</span>
      </form>
    </section>
  </div>;
}

