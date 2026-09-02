"use client";

import { FormEvent, useEffect, useState } from "react";
import { request } from "../lib/api";

type Project = { id: number; name: string; path: string; model: string; approval_mode: "review" | "assisted" | "autonomous"; instructions: string; git_author_name: string; git_author_email: string; model_profile_id?: number; profile_name?: string; profile_chat_model?: string; profile_embedding_model?: string; profile_temperature?: number; profile_max_steps?: number; profile_context_files?: number; profile_context_chars?: number };
type Intelligence = { name: string; path: string; file_count: number; total_bytes: number; languages: { extension: string; files: number }[]; frameworks: string[]; test_commands: string[]; build_commands: string[]; symbols: { name: string; kind: string; path: string; line: number; parser: string }[]; instructions_configured: boolean };
type ContextItem = { path: string; score: number; semantic_score: number; start_line: number; strategy: "hybrid" | "lexical" | "indexed-hybrid" | "indexed-lexical"; excerpt: string };
type ModelProfile = { id: number; name: string; chat_model: string; embedding_model: string; temperature: number; max_steps: number; context_files: number; context_chars: number; is_builtin: number };
type IndexStatus = { files: number; embedded: number; updated_at?: string; changed?: number; removed?: number; embedded_now?: number };

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
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [profileId, setProfileId] = useState(project.model_profile_id ? String(project.model_profile_id) : "");
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null);
  const [profileName, setProfileName] = useState("");
  const [profileEmbedding, setProfileEmbedding] = useState(project.profile_embedding_model || "nomic-embed-text");
  const [profileTemperature, setProfileTemperature] = useState(project.profile_temperature ?? 0.2);
  const [profileSteps, setProfileSteps] = useState(project.profile_max_steps ?? 8);
  const [profileFiles, setProfileFiles] = useState(project.profile_context_files ?? 8);
  const [profileChars, setProfileChars] = useState(project.profile_context_chars ?? 32000);

  useEffect(() => {
    const selected = profiles.find((profile) => String(profile.id) === profileId);
    if (!selected) return;
    setProfileName(selected.name); setModel(selected.chat_model); setProfileEmbedding(selected.embedding_model); setProfileTemperature(selected.temperature); setProfileSteps(selected.max_steps); setProfileFiles(selected.context_files); setProfileChars(selected.context_chars);
  }, [profileId, profiles]);

  useEffect(() => {
    setModel(project.model); setMode(project.approval_mode || "assisted"); setInstructions(project.instructions || ""); setGitName(project.git_author_name || "Olladex User"); setGitEmail(project.git_author_email || "olladex@local"); setProfileId(project.model_profile_id ? String(project.model_profile_id) : "");
    request<Intelligence>(`/projects/${project.id}/intelligence`).then(setIntelligence).catch((error) => setNotice(error.message));
    request<ModelProfile[]>("/model-profiles").then(setProfiles).catch(() => {});
    request<IndexStatus>(`/projects/${project.id}/index`).then(setIndexStatus).catch(() => {});
  }, [project.id, project.model, project.approval_mode, project.instructions, project.git_author_name, project.git_author_email]);

  async function save(event: FormEvent) {
    event.preventDefault(); setNotice("Saving…");
    try {
      const updated = await request<Project>(`/projects/${project.id}/settings`, { method: "PATCH", body: JSON.stringify({ model, approval_mode: mode, instructions, git_author_name: gitName, git_author_email: gitEmail, model_profile_id: profileId ? Number(profileId) : null }) });
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

  async function refreshIndex() {
    setNotice("Updating repository index…");
    try { setIndexStatus(await request<IndexStatus>(`/projects/${project.id}/index`, { method: "POST" })); setNotice("Repository index updated"); }
    catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function createProfile() {
    if (!profileName.trim() || !model.trim()) return;
    try {
      const created = await request<ModelProfile>("/model-profiles", { method: "POST", body: JSON.stringify({ name: profileName.trim(), chat_model: model.trim(), embedding_model: profileEmbedding.trim(), temperature: profileTemperature, max_steps: profileSteps, context_files: profileFiles, context_chars: profileChars }) });
      setProfiles((items) => [...items, created].sort((a, b) => a.name.localeCompare(b.name))); setProfileId(String(created.id)); setProfileName(""); setNotice("Model profile created — save project settings to apply it");
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function updateProfile() {
    if (!profileId || !profileName.trim() || !model.trim()) return;
    try {
      const updated = await request<ModelProfile>(`/model-profiles/${profileId}`, { method: "PUT", body: JSON.stringify({ name: profileName.trim(), chat_model: model.trim(), embedding_model: profileEmbedding.trim(), temperature: profileTemperature, max_steps: profileSteps, context_files: profileFiles, context_chars: profileChars }) });
      setProfiles((items) => items.map((item) => item.id === updated.id ? updated : item).sort((a, b) => a.name.localeCompare(b.name))); setNotice("Model profile updated");
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function deleteProfile() {
    const selected = profiles.find((profile) => String(profile.id) === profileId);
    if (!selected || selected.is_builtin) return;
    try {
      await request(`/model-profiles/${selected.id}`, { method: "DELETE" });
      setProfiles((items) => items.filter((item) => item.id !== selected.id)); setProfileId(""); setProfileName(""); setNotice("Custom model profile deleted");
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  function newProfile() {
    setProfileId(""); setProfileName(""); setNotice("Enter a name and settings for the new profile");
  }

  return <div className="project-panel">
    <section className="project-summary-card"><div><p className="eyebrow">Repository intelligence</p><h2>{project.name}</h2><p>{project.path}</p></div><div className="project-metrics"><span><strong>{intelligence?.file_count || 0}</strong>files</span><span><strong>{formatBytes(intelligence?.total_bytes || 0)}</strong>indexed</span><span><strong>{intelligence?.symbols.length || 0}</strong>symbols</span></div></section>
    <div className="project-columns">
      <section><p className="eyebrow">Detected stack</p><h3>Languages & frameworks</h3><div className="tag-list">{intelligence?.frameworks.map((item) => <span key={item}>{item}</span>)}{intelligence?.languages.map((item) => <span key={item.extension}>{item.extension} · {item.files}</span>)}</div><h4>Suggested checks</h4>{[...(intelligence?.test_commands || []), ...(intelligence?.build_commands || [])].map((item) => <code key={item}>{item}</code>)}</section>
      <section><p className="eyebrow">Agent configuration</p><h3>Project rules</h3><form onSubmit={save}><label>Model profile<select value={profileId} onChange={(e) => setProfileId(e.target.value)}><option value="">Project model only</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name} · {profile.chat_model}</option>)}</select></label><label>Ollama model<input value={model} onChange={(e) => setModel(e.target.value)} /></label><details className="profile-builder"><summary>{profileId ? "Edit selected model profile" : "Create reusable profile"}</summary><div className="profile-title"><label>Profile name<input value={profileName} disabled={Boolean(profiles.find((profile) => String(profile.id) === profileId)?.is_builtin)} onChange={(e) => setProfileName(e.target.value)} placeholder="My coding profile" /></label>{profileId && <button type="button" onClick={newProfile}>New profile</button>}</div><div><label>Embedding model<input value={profileEmbedding} onChange={(e) => setProfileEmbedding(e.target.value)} /></label><label>Temperature<input type="number" min="0" max="2" step="0.05" value={profileTemperature} onChange={(e) => setProfileTemperature(Number(e.target.value))} /></label></div><div><label>Tool steps<input type="number" min="1" max="30" value={profileSteps} onChange={(e) => setProfileSteps(Number(e.target.value))} /></label><label>Context files<input type="number" min="1" max="30" value={profileFiles} onChange={(e) => setProfileFiles(Number(e.target.value))} /></label><label>Context characters<input type="number" min="4000" max="200000" step="1000" value={profileChars} onChange={(e) => setProfileChars(Number(e.target.value))} /></label></div><div className="profile-actions">{profileId ? <><button type="button" onClick={updateProfile}>Save profile</button>{!profiles.find((profile) => String(profile.id) === profileId)?.is_builtin && <button type="button" onClick={deleteProfile}>Delete custom profile</button>}</> : <button type="button" onClick={createProfile}>Create profile</button>}</div></details><label>Approval mode<select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}><option value="review">Review — approve every command</option><option value="assisted">Assisted — safe checks run automatically</option><option value="autonomous">Autonomous — commands run automatically</option></select></label><label>Instructions<textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="Use Python 3.12. Run tests before completion. Never modify deployment secrets…" /></label><div className="git-identity"><label>Git author<input value={gitName} onChange={(e) => setGitName(e.target.value)} /></label><label>Git email<input type="email" value={gitEmail} onChange={(e) => setGitEmail(e.target.value)} /></label></div><div><button className="primary">Save settings</button><span>{notice}</span></div></form></section>
    </div>
    <section className="context-lens"><div className="context-head"><div><p className="eyebrow">Persistent context engine</p><h3>Preview task-ranked context</h3></div><div><span>{indexStatus?.files || 0} indexed</span><span>{indexStatus?.embedded || 0} embedded</span><button type="button" onClick={refreshIndex}>Refresh index</button></div></div><form onSubmit={previewContext}><input value={contextQuery} onChange={(event) => setContextQuery(event.target.value)} placeholder="e.g. Where is authentication state validated?" /><button className="primary" disabled={!contextQuery.trim()}>Rank files</button></form>{contextItems.length > 0 && <div>{contextItems.map((item) => <article key={item.path}><span><strong>{item.path}</strong><small>line {item.start_line} · {item.strategy} · {item.score.toFixed(3)}</small></span><i>{item.semantic_score > 0 ? `semantic ${item.semantic_score.toFixed(3)}` : "lexical fallback"}</i></article>)}</div>}</section>
    <section className="symbol-map"><p className="eyebrow">Repository map</p><h3>Detected symbols</h3><div>{intelligence?.symbols.slice(0, 120).map((symbol) => <article key={`${symbol.path}:${symbol.line}:${symbol.name}`}><strong>{symbol.name}</strong><span>{symbol.path}:{symbol.line}</span><i>{symbol.kind} · {symbol.parser}</i></article>)}</div></section>
  </div>;
}

function formatBytes(value: number) { return value > 1_000_000 ? `${(value / 1_000_000).toFixed(1)} MB` : value > 1_000 ? `${Math.round(value / 1_000)} KB` : `${value} B`; }
