"use client";

import { FormEvent, useEffect, useState } from "react";
import { request } from "../lib/api";

type Project = { id: number; name: string; path: string; model: string; approval_mode: "review" | "assisted" | "autonomous"; instructions: string };
type Intelligence = { name: string; path: string; file_count: number; total_bytes: number; languages: { extension: string; files: number }[]; frameworks: string[]; test_commands: string[]; build_commands: string[]; symbols: { name: string; path: string; line: number }[]; instructions_configured: boolean };

export function ProjectPanel({ project, onUpdated }: { project: Project; onUpdated: (project: Project) => void }) {
  const [intelligence, setIntelligence] = useState<Intelligence | null>(null);
  const [model, setModel] = useState(project.model);
  const [mode, setMode] = useState(project.approval_mode || "assisted");
  const [instructions, setInstructions] = useState(project.instructions || "");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    setModel(project.model); setMode(project.approval_mode || "assisted"); setInstructions(project.instructions || "");
    request<Intelligence>(`/projects/${project.id}/intelligence`).then(setIntelligence).catch((error) => setNotice(error.message));
  }, [project.id, project.model, project.approval_mode, project.instructions]);

  async function save(event: FormEvent) {
    event.preventDefault(); setNotice("Saving…");
    try {
      const updated = await request<Project>(`/projects/${project.id}/settings`, { method: "PATCH", body: JSON.stringify({ model, approval_mode: mode, instructions }) });
      onUpdated(updated); setNotice("Project settings saved");
      const map = await request<Intelligence>(`/projects/${project.id}/intelligence`); setIntelligence(map);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  return <div className="project-panel">
    <section className="project-summary-card"><div><p className="eyebrow">Repository intelligence</p><h2>{project.name}</h2><p>{project.path}</p></div><div className="project-metrics"><span><strong>{intelligence?.file_count || 0}</strong>files</span><span><strong>{formatBytes(intelligence?.total_bytes || 0)}</strong>indexed</span><span><strong>{intelligence?.symbols.length || 0}</strong>symbols</span></div></section>
    <div className="project-columns">
      <section><p className="eyebrow">Detected stack</p><h3>Languages & frameworks</h3><div className="tag-list">{intelligence?.frameworks.map((item) => <span key={item}>{item}</span>)}{intelligence?.languages.map((item) => <span key={item.extension}>{item.extension} · {item.files}</span>)}</div><h4>Suggested checks</h4>{[...(intelligence?.test_commands || []), ...(intelligence?.build_commands || [])].map((item) => <code key={item}>{item}</code>)}</section>
      <section><p className="eyebrow">Agent configuration</p><h3>Project rules</h3><form onSubmit={save}><label>Ollama model<input value={model} onChange={(e) => setModel(e.target.value)} /></label><label>Approval mode<select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}><option value="review">Review — approve every command</option><option value="assisted">Assisted — safe checks run automatically</option><option value="autonomous">Autonomous — commands run automatically</option></select></label><label>Instructions<textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="Use Python 3.12. Run tests before completion. Never modify deployment secrets…" /></label><div><button className="primary">Save settings</button><span>{notice}</span></div></form></section>
    </div>
    <section className="symbol-map"><p className="eyebrow">Repository map</p><h3>Detected symbols</h3><div>{intelligence?.symbols.slice(0, 120).map((symbol) => <article key={`${symbol.path}:${symbol.line}:${symbol.name}`}><strong>{symbol.name}</strong><span>{symbol.path}:{symbol.line}</span></article>)}</div></section>
  </div>;
}

function formatBytes(value: number) { return value > 1_000_000 ? `${(value / 1_000_000).toFixed(1)} MB` : value > 1_000 ? `${Math.round(value / 1_000)} KB` : `${value} B`; }
