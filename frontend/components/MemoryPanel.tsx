"use client";

import { useEffect, useState } from "react";
import { request } from "../lib/api";

type Scope = "personal" | "workspace" | "project" | "conversation";

export function MemoryPanel({ projectName, sessionId }: { projectName: string; sessionId?: number }) {
  const [scope, setScope] = useState<Scope>("conversation");
  const [conversation, setConversation] = useState("");
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");

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

  const staged = scope !== "conversation";

  return <div className="memory-panel">
    <section className="memory-hero">
      <div><p className="eyebrow">Memory v2</p><h2>What Olladex should remember</h2><p>Memory is separated by scope so useful context can persist without every detail being injected into every prompt.</p></div>
      <div className="memory-scope-summary"><span><strong>4</strong> scopes</span><span><strong>1</strong> live</span><span><strong>3</strong> staged</span></div>
    </section>

    <nav className="memory-tabs" aria-label="Memory scope">
      {(["personal", "workspace", "project", "conversation"] as Scope[]).map(item => <button key={item} className={scope === item ? "active" : ""} onClick={() => setScope(item)}>{item}</button>)}
    </nav>

    {scope === "personal" && <section className="memory-scope-card">
      <header><div><p className="eyebrow">Personal memory</p><h3>Preferences that follow you</h3></div><span>Staged</span></header>
      <p>This scope is intended for durable preferences such as response style, preferred tools, common infrastructure and model choices.</p>
      <div className="memory-example-grid"><article><strong>Interaction</strong><small>How you prefer Olladex to communicate and present work.</small></article><article><strong>Development</strong><small>Recurring technical preferences that apply across projects.</small></article></div>
      <p className="memory-stage-note">UI contract only in this phase. Nothing entered here is persisted yet.</p>
    </section>}

    {scope === "workspace" && <section className="memory-scope-card">
      <header><div><p className="eyebrow">Workspace memory</p><h3>Context shared across related projects</h3></div><span>Staged</span></header>
      <p>This will let several repositories share useful context without copying the same notes into every project.</p>
      <div className="memory-example-grid"><article><strong>Shared architecture</strong><small>Services, conventions and dependencies reused by a family of applications.</small></article><article><strong>Shared decisions</strong><small>Choices that should influence more than one repository.</small></article></div>
      <p className="memory-stage-note">Workspace entities and persistent storage are deliberately deferred until the scope model is proven.</p>
    </section>}

    {scope === "project" && <section className="memory-scope-card">
      <header><div><p className="eyebrow">Project memory</p><h3>{projectName}</h3></div><span>Staged</span></header>
      <p>This scope is intended for architecture decisions, project conventions, deployment details and recurring constraints for this repository.</p>
      <div className="memory-example-grid"><article><strong>Architecture</strong><small>Stable facts about how the project is structured.</small></article><article><strong>Decisions</strong><small>Why important implementation choices were made.</small></article></div>
      <p className="memory-stage-note">Project rules remain separate from memory. Existing project instructions are not being repurposed for this.</p>
    </section>}

    {scope === "conversation" && <section className="memory-scope-card live">
      <header><div><p className="eyebrow">Conversation memory</p><h3>Current conversation</h3></div><span>Live</span></header>
      {sessionId ? <>
        <p>This is the existing user-managed memory for the open conversation. It already contributes to model context.</p>
        <textarea value={draft} onChange={event => setDraft(event.target.value)} maxLength={8000} placeholder="Preferences, decisions and facts that should remain available in this conversation…" />
        <div className="memory-actions"><small>{draft.length.toLocaleString()} / 8,000 characters</small><button onClick={() => setDraft(conversation)} disabled={draft === conversation}>Reset</button><button className="primary" onClick={saveConversation} disabled={draft === conversation}>Save memory</button></div>
      </> : <p>Open a conversation to view and edit its memory.</p>}
    </section>}

    {staged && <section className="memory-flow">
      <p className="eyebrow">Planned retrieval model</p>
      <div><span>Personal</span><b>+</b><span>Workspace</span><b>+</b><span>Project</span><b>+</b><span>Conversation</span><b>→</b><strong>Relevant context</strong></div>
      <p>Future retrieval should select only relevant items from each scope rather than placing all stored memory into every model call.</p>
    </section>}

    {notice && <div className="queue-notice">{notice}</div>}
  </div>;
}
