"use client";

import { useEffect, useState } from "react";
import { request } from "../lib/api";

type Scope = "personal" | "workspace" | "project" | "conversation";

type ScopedMemory = { scope: string; scope_key: string; content: string; updated_at: string };

export function MemoryPanel({ projectId, projectName, sessionId }: { projectId: number; projectName: string; sessionId?: number }) {
  const [scope, setScope] = useState<Scope>("conversation");
  const [conversation, setConversation] = useState("");
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");
  const [scoped, setScoped] = useState<Record<Exclude<Scope, "conversation">, string>>({ personal: "", workspace: "", project: "" });
  const [scopedDraft, setScopedDraft] = useState<Record<Exclude<Scope, "conversation">, string>>({ personal: "", workspace: "", project: "" });

  useEffect(() => {
    if (!sessionId) {
      setConversation("");
      setDraft("");
      return;
    }
    let disposed = false;
    request<{ content: string }>(`/sessions/${sessionId}/memory`)
      .then(data => {
        if (disposed) return;
        setConversation(data.content || "");
        setDraft(data.content || "");
      })
      .catch(error => { if (!disposed) setNotice(error instanceof Error ? error.message : String(error)); });
    return () => { disposed = true; };
  }, [sessionId]);


  useEffect(() => {
    let disposed = false;
    async function loadScoped() {
      try {
        const [personal, workspace, project] = await Promise.all([
          request<ScopedMemory>("/memory/personal"),
          request<ScopedMemory>(`/projects/${projectId}/workspace`).then(async workspace => workspace?.id ? request<ScopedMemory>(`/memory/workspace?workspace_id=${workspace.id}`) : ({ scope: "workspace", scope_key: "", content: "", updated_at: "" } as ScopedMemory)),
          request<ScopedMemory>(`/memory/project?project_id=${projectId}`),
        ]);
        if (disposed) return;
        const next = { personal: personal.content || "", workspace: workspace.content || "", project: project.content || "" };
        setScoped(next); setScopedDraft(next);
      } catch (error) {
        if (!disposed) setNotice(error instanceof Error ? error.message : String(error));
      }
    }
    void loadScoped();
    return () => { disposed = true; };
  }, [projectId]);

  async function saveScoped(scopeName: Exclude<Scope, "conversation">) {
    setNotice("Saving…");
    try {
      let suffix = scopeName === "project" ? `?project_id=${projectId}` : "";
      if (scopeName === "workspace") {
        const workspace = await request<{ id: number } | null>(`/projects/${projectId}/workspace`);
        if (!workspace?.id) { setNotice("Assign this project to a workspace first"); return; }
        suffix = `?workspace_id=${workspace.id}`;
      }
      const result = await request<ScopedMemory>(`/memory/${scopeName}${suffix}`, { method: "PUT", body: JSON.stringify({ content: scopedDraft[scopeName] }) });
      setScoped(current => ({ ...current, [scopeName]: result.content }));
      setScopedDraft(current => ({ ...current, [scopeName]: result.content }));
      setNotice(`${scopeName[0].toUpperCase() + scopeName.slice(1)} memory saved`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    }
  }

  async function saveConversation() {
    if (!sessionId) return;
    setNotice("Saving…");
    try {
      const result = await request<{ content: string }>(`/sessions/${sessionId}/memory`, { method: "PUT", body: JSON.stringify({ content: draft }) });
      setConversation(result.content);
      setDraft(result.content);
      setNotice("Conversation memory saved");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    }
  }


  return <div className="memory-panel">
    <section className="memory-hero">
      <div><p className="eyebrow">Memory v2</p><h2>What Olladex should remember</h2><p>Memory is separated by scope so useful context can persist without every detail being injected into every prompt.</p></div>
      <div className="memory-scope-summary"><span><strong>4</strong> scopes</span><span><strong>4</strong> persistent</span><span><strong>3</strong> reusable</span></div>
    </section>

    <nav className="memory-tabs" aria-label="Memory scope">
      {(["personal", "workspace", "project", "conversation"] as Scope[]).map(item => <button key={item} className={scope === item ? "active" : ""} onClick={() => setScope(item)}>{item}</button>)}
    </nav>

    {scope === "personal" && <section className="memory-scope-card live">
      <header><div><p className="eyebrow">Personal memory</p><h3>Preferences that follow you</h3></div><span>Live</span></header>
      <p>Durable preferences that apply across projects. This memory is included in model context for all conversations.</p>
      <textarea value={scopedDraft.personal} onChange={event => setScopedDraft(current => ({ ...current, personal: event.target.value }))} maxLength={8000} placeholder="Response style, preferred tools, common infrastructure, model choices…" />
      <div className="memory-actions"><small>{scopedDraft.personal.length.toLocaleString()} / 8,000 characters</small><button onClick={() => setScopedDraft(current => ({ ...current, personal: scoped.personal }))} disabled={scopedDraft.personal === scoped.personal}>Reset</button><button className="primary" onClick={() => saveScoped("personal")} disabled={scopedDraft.personal === scoped.personal}>Save memory</button></div>
    </section>}

    {scope === "workspace" && <section className="memory-scope-card live">
      <header><div><p className="eyebrow">Workspace memory</p><h3>Assigned workspace</h3></div><span>Live</span></header>
      <p>Workspace memory is now injected only when this project belongs to a named workspace.</p>
      <textarea value={scopedDraft.workspace} onChange={event => setScopedDraft(current => ({ ...current, workspace: event.target.value }))} maxLength={8000} placeholder="Shared architecture, reusable services, cross-project decisions…" />
      <div className="memory-actions"><small>{scopedDraft.workspace.length.toLocaleString()} / 8,000 characters</small><button onClick={() => setScopedDraft(current => ({ ...current, workspace: scoped.workspace }))} disabled={scopedDraft.workspace === scoped.workspace}>Reset</button><button className="primary" onClick={() => saveScoped("workspace")} disabled={scopedDraft.workspace === scoped.workspace}>Save memory</button></div>
    </section>}

    {scope === "project" && <section className="memory-scope-card live">
      <header><div><p className="eyebrow">Project memory</p><h3>{projectName}</h3></div><span>Live</span></header>
      <p>Architecture decisions, conventions, deployment details and recurring constraints for this repository. This memory is included in model context for this project.</p>
      <textarea value={scopedDraft.project} onChange={event => setScopedDraft(current => ({ ...current, project: event.target.value }))} maxLength={8000} placeholder="Architecture, decisions, conventions, deployment details…" />
      <div className="memory-actions"><small>{scopedDraft.project.length.toLocaleString()} / 8,000 characters</small><button onClick={() => setScopedDraft(current => ({ ...current, project: scoped.project }))} disabled={scopedDraft.project === scoped.project}>Reset</button><button className="primary" onClick={() => saveScoped("project")} disabled={scopedDraft.project === scoped.project}>Save memory</button></div>
    </section>}

    {scope === "conversation" && <section className="memory-scope-card live">
      <header><div><p className="eyebrow">Conversation memory</p><h3>Current conversation</h3></div><span>Live</span></header>
      {sessionId ? <>
        <p>This is the existing user-managed memory for the open conversation. It already contributes to model context.</p>
        <textarea value={draft} onChange={event => setDraft(event.target.value)} maxLength={8000} placeholder="Preferences, decisions and facts that should remain available in this conversation…" />
        <div className="memory-actions"><small>{draft.length.toLocaleString()} / 8,000 characters</small><button onClick={() => setDraft(conversation)} disabled={draft === conversation}>Reset</button><button className="primary" onClick={saveConversation} disabled={draft === conversation}>Save memory</button></div>
      </> : <p>Open a conversation to view and edit its memory.</p>}
    </section>}

    {<section className="memory-flow">
      <p className="eyebrow">Planned retrieval model</p>
      <div><span>Personal</span><b>+</b><span>Workspace</span><b>+</b><span>Project</span><b>+</b><span>Conversation</span><b>→</b><strong>Relevant context</strong></div>
      <p>Future retrieval should select only relevant items from each scope rather than placing all stored memory into every model call.</p>
    </section>}

    {notice && <div className="queue-notice">{notice}</div>}
  </div>;
}
