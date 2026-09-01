"use client";

import { FormEvent, useEffect, useState } from "react";
import { request } from "../lib/api";

type Project = { id: number; name: string; path: string; model: string; approval_mode: "review" | "assisted" | "autonomous"; instructions: string; git_author_name: string; git_author_email: string };
type Intelligence = { name: string; path: string; file_count: number; total_bytes: number; languages: { extension: string; files: number }[]; frameworks: string[]; test_commands: string[]; build_commands: string[]; symbols: { name: string; kind: string; path: string; line: number; parser: string }[]; instructions_configured: boolean };
type ContextItem = { path: string; score: number; semantic_score: number; start_line: number; strategy: "hybrid" | "lexical"; excerpt: string };

export function ProjectPanel({ project, onUpdated }: { project: Project; onUpdated: (project: Project) => void }) {
  const [intelligence, setIntelligence] = useState<Intelligence | null>(null);
  const [model, setModel] = useState(project.model);
  const [mode, setMode] = useState(project.approval_mode || "assisted");
  const [instructions, setInstructions] = useState(project.instructions || "");
  const [gitName, setGitName] = useState(project.git_author_name || "Olladex User");
  const [gitEmail, setGitEmail] = useState(project.git_author_email || "olladex@local");
  const [notice, setNotice] = useState("");
  const [contextQuery, setContextQuery] = useState("");
  const [contextItems, setContextItems] = useState<ContextItem[]>([]);

  useEffect(() => {
    setModel(project.model); setMode(project.approval_mode || "assisted"); setInstructions(project.instructions || ""); setGitName(project.git_author_name || "Olladex User"); setGitEmail(project.git_author_email || "olladex@local");
    request<Intelligence>(`/projects/${project.id}/intelligence`).then(setIntelligence).catch((error) => setNotice(error.message));
  }, [project.id, project.model, project.approval_mode, project.instructions, project.git_author_name, project.git_author_email]);

  async function save(event: FormEvent) {
    event.preventDefault(); setNotice("Saving…");
    try {
      const updated = await request<Project>(`/projects/${project.id}/settings`, { method: "PATCH", body: JSON.stringify({ model, approval_mode: mode, instructions, git_author_name: gitName, git_author_email: gitEmail }) });
      onUpdated(updated); setNotice("Project settings saved");
      const map = await request<Intelligence>(`/projects/${project.id}/intelligence`); setIntelligence(map);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function previewContext(event: FormEvent) {
    event.preventDefault(); if (!contextQuery.trim()) return;
    setNotice("Ranking repository context…");
    try { setContextItems(await request<ContextItem[]>(`/projects/${project.id}/context-preview?q=${encodeURIComponent(contextQuery)}`)); setNotice(""); }
    catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  return <div className="project-panel">
    <section className="project-summary-card"><div><p className="eyebrow">Repository intelligence</p><h2>{project.name}</h2><p>{project.path}</p></div><div className="project-metrics"><span><strong>{intelligence?.file_count || 0}</strong>files</span><span><strong>{formatBytes(intelligence?.total_bytes || 0)}</strong>indexed</span><span><strong>{intelligence?.symbols.length || 0}</strong>symbols</span></div></section>
    <div className="project-columns">
      <section><p className="eyebrow">Detected stack</p><h3>Languages & frameworks</h3><div className="tag-list">{intelligence?.frameworks.map((item) => <span key={item}>{item}</span>)}{intelligence?.languages.map((item) => <span key={item.extension}>{item.extension} · {item.files}</span>)}</div><h4>Suggested checks</h4>{[...(intelligence?.test_commands || []), ...(intelligence?.build_commands || [])].map((item) => <code key={item}>{item}</code>)}</section>
      <section><p className="eyebrow">Agent configuration</p><h3>Project rules</h3><form onSubmit={save}><label>Ollama model<input value={model} onChange={(e) => setModel(e.target.value)} /></label><label>Approval mode<select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}><option value="review">Review — approve every command</option><option value="assisted">Assisted — safe checks run automatically</option><option value="autonomous">Autonomous — commands run automatically</option></select></label><label>Instructions<textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="Use Python 3.12. Run tests before completion. Never modify deployment secrets…" /></label><div className="git-identity"><label>Git author<input value={gitName} onChange={(e) => setGitName(e.target.value)} /></label><label>Git email<input type="email" value={gitEmail} onChange={(e) => setGitEmail(e.target.value)} /></label></div><div><button className="primary">Save settings</button><span>{notice}</span></div></form></section>
    </div>
    <section className="context-lens"><p className="eyebrow">Context engine</p><h3>Preview task-ranked context</h3><form onSubmit={previewContext}><input value={contextQuery} onChange={(event) => setContextQuery(event.target.value)} placeholder="e.g. Where is authentication state validated?" /><button className="primary" disabled={!contextQuery.trim()}>Rank files</button></form>{contextItems.length > 0 && <div>{contextItems.map((item) => <article key={item.path}><span><strong>{item.path}</strong><small>line {item.start_line} · {item.strategy} · {item.score.toFixed(3)}</small></span><i>{item.semantic_score > 0 ? `semantic ${item.semantic_score.toFixed(3)}` : "lexical fallback"}</i></article>)}</div>}</section>
    <section className="symbol-map"><p className="eyebrow">Repository map</p><h3>Detected symbols</h3><div>{intelligence?.symbols.slice(0, 120).map((symbol) => <article key={`${symbol.path}:${symbol.line}:${symbol.name}`}><strong>{symbol.name}</strong><span>{symbol.path}:{symbol.line}</span><i>{symbol.kind} · {symbol.parser}</i></article>)}</div></section>
  </div>;
}

function formatBytes(value: number) { return value > 1_000_000 ? `${(value / 1_000_000).toFixed(1)} MB` : value > 1_000 ? `${Math.round(value / 1_000)} KB` : `${value} B`; }
