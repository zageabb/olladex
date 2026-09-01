"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { DiagramStudio } from "../components/DiagramStudio";
import { FileTree, TreeNode } from "../components/FileTree";
import { OfficePanel } from "../components/OfficePanel";
import { TerminalPanel } from "../components/TerminalPanel";
import { request } from "../lib/api";

type Project = { id: number; name: string; path: string; model: string };
type Session = { id: number; project_id: number; title: string; updated_at: string };
type Activity = { tool: string; summary: string; arguments?: Record<string, unknown>; result?: unknown };
type Message = { id?: number; role: "user" | "assistant"; content: string; activities?: Activity[] };
type Status = { version: string; shell: string; ollama: { connected: boolean; url: string; models: string[]; error?: string } };
type Change = { id: number; path: string; diff: string; status: string; created_at: string };
type GitSummary = { repository: boolean; branch: string; changes: { status: string; path: string }[]; recent: { sha: string; subject: string; age: string }[] };
type Tab = "files" | "changes" | "terminal" | "diagrams" | "office";

const WELCOME: Message = { role: "assistant", content: "Welcome to Olladex. Open a local repository, then ask me to inspect, change and test it. Repository tools, Bash, diagrams and Office files stay on your machine." };

export default function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [selected, setSelected] = useState<TreeNode | null>(null);
  const [fileContent, setFileContent] = useState("");
  const [fileDraft, setFileDraft] = useState("");
  const [changes, setChanges] = useState<Change[]>([]);
  const [git, setGit] = useState<GitSummary | null>(null);
  const [gitDiff, setGitDiff] = useState("");
  const [tab, setTab] = useState<Tab>("files");
  const [status, setStatus] = useState<Status | null>(null);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [openPath, setOpenPath] = useState("");
  const [showOpen, setShowOpen] = useState(false);
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    request<Project[]>("/projects").then((data) => { setProjects(data); if (data.length) setProject(data[0]); }).catch((e) => setNotice(e.message));
    request<Status>("/status").then(setStatus).catch(() => {});
  }, []);

  useEffect(() => {
    if (!project) return;
    refreshTree();
    request<Session[]>(`/projects/${project.id}/sessions`).then((data) => { setSessions(data); setSession(data[0] || null); });
    request<Change[]>(`/projects/${project.id}/changes`).then(setChanges).catch(() => {});
    request<GitSummary>(`/projects/${project.id}/git`).then(setGit).catch(() => setGit(null));
    request<{ diff: string }>(`/projects/${project.id}/git/diff`).then((data) => setGitDiff(data.diff)).catch(() => setGitDiff(""));
  }, [project?.id]);

  useEffect(() => {
    if (!session) { setMessages([WELCOME]); return; }
    request<Message[]>(`/sessions/${session.id}/messages`).then((data) => setMessages(data.length ? data : [WELCOME])).catch(() => setMessages([WELCOME]));
  }, [session?.id]);

  async function refreshTree() {
    if (project) setTree(await request<TreeNode[]>(`/projects/${project.id}/tree`));
  }

  async function openProject(event: FormEvent) {
    event.preventDefault();
    try {
      const created = await request<Project>("/projects", { method: "POST", body: JSON.stringify({ path: openPath }) });
      setProjects((current) => [created, ...current.filter((item) => item.id !== created.id)]); setProject(created); setShowOpen(false); setOpenPath("");
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function createSession() {
    if (!project) return;
    const created = await request<Session>(`/projects/${project.id}/sessions`, { method: "POST", body: JSON.stringify({ title: "New task" }) });
    setSessions((current) => [created, ...current]); setSession(created); setMessages([WELCOME]);
  }

  async function selectFile(item: TreeNode) {
    setSelected(item);
    if (item.type !== "file" || !project) return;
    if (/\.(docx|xlsx|pptx|pdf)$/i.test(item.path)) { setTab("office"); return; }
    if (/\.(mmd|mermaid)$/i.test(item.path)) setTab("diagrams");
    else if (/\.dot$/i.test(item.path)) setTab("diagrams");
    else setTab("files");
    try {
      const data = await request<{ content: string }>(`/projects/${project.id}/files?path=${encodeURIComponent(item.path)}`);
      setFileContent(data.content); setFileDraft(data.content);
    } catch (error) { setFileContent(""); setFileDraft(""); setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function saveFile() {
    if (!project || !selected || selected.type !== "file") return;
    const result = await request<{ diff: string }>(`/projects/${project.id}/files?path=${encodeURIComponent(selected.path)}`, { method: "PUT", body: JSON.stringify({ content: fileDraft, session_id: session?.id }) });
    setFileContent(fileDraft); setChanges((current) => [{ id: Date.now(), path: selected.path, diff: result.diff, status: "applied", created_at: new Date().toISOString() }, ...current]); setNotice(`Saved ${selected.path}`);
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    if (!prompt.trim() || !session || !project || busy) return;
    const content = prompt; setPrompt(""); setBusy(true); setMessages((current) => [...current, { role: "user", content }]);
    try {
      const answer = await request<Message>(`/sessions/${session.id}/messages`, { method: "POST", body: JSON.stringify({ content }) });
      setMessages((current) => [...current, answer]); await refreshTree();
      if (answer.activities?.some((a) => a.tool === "write_file")) request<Change[]>(`/projects/${project.id}/changes`).then(setChanges);
    } catch (error) { setMessages((current) => [...current, { role: "assistant", content: `I couldn't complete that request: ${error instanceof Error ? error.message : String(error)}` }]); }
    finally { setBusy(false); }
  }

  const filteredTree = useMemo(() => search.trim() ? filterTree(tree, search.toLowerCase()) : tree, [tree, search]);
  const diagramSource = selected && /\.(mmd|mermaid|dot)$/i.test(selected.path) ? fileDraft : undefined;
  const diagramEngine = selected && /\.dot$/i.test(selected.path) ? "dot" as const : "mermaid" as const;

  return <main className="app-shell">
    <header className="topbar">
      <div className="brand"><span className="brand-mark">O</span><span>Olladex</span><em>v0.1</em></div>
      <div className="project-selector"><span>Repository</span><select value={project?.id || ""} onChange={(e) => setProject(projects.find((p) => p.id === Number(e.target.value)) || null)}><option value="">Open a repository</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
      <button className="global-search" onClick={() => setTab("files")}>⌕ Search this repository <kbd>⌘ K</kbd></button>
      <div className={`connection ${status?.ollama.connected ? "online" : ""}`}><i />{status?.ollama.connected ? `${project?.model || status.ollama.models[0] || "Ollama"}` : "Ollama offline"}</div>
      <button className="avatar">GA</button>
    </header>

    <aside className="rail">
      <button className="active"><span>✦</span><small>Agent</small></button>
      <button onClick={() => setTab("files")}><span>▦</span><small>Files</small></button>
      <button onClick={() => setTab("terminal")}><span>⌘</span><small>Terminal</small></button>
      <button onClick={() => setTab("diagrams")}><span>◇</span><small>Diagrams</small></button>
      <button onClick={() => setTab("office")}><span>▤</span><small>Office</small></button>
      <div className="rail-bottom"><button><span>⚙</span><small>Settings</small></button></div>
    </aside>

    <div className="workspace">
      <aside className="task-sidebar">
        <div className="task-actions"><button className="primary" onClick={createSession} disabled={!project}>＋ New task</button><button onClick={() => setShowOpen(true)}>Open</button></div>
        <div className="section-label">Projects</div>
        {projects.map((item) => <button key={item.id} className={`project-row ${project?.id === item.id ? "selected" : ""}`} onClick={() => setProject(item)}><span>▣</span><div><strong>{item.name}</strong><small>{item.path}</small></div></button>)}
        <div className="section-label sessions-label">Recent tasks</div>
        {sessions.map((item) => <button key={item.id} className={`session-row ${session?.id === item.id ? "selected" : ""}`} onClick={() => setSession(item)}><span>⌁</span><div><strong>{item.title}</strong><small>{new Date(item.updated_at).toLocaleDateString()}</small></div></button>)}
      </aside>

      <section className="conversation-panel">
        <div className="panel-head"><div><p className="eyebrow">Local development agent</p><h1>{session?.title || "Start a task"}</h1></div><div className="approval-mode"><span>Mode</span><strong>Assisted</strong></div></div>
        <div className="messages">
          {messages.map((message, index) => <article className={`message ${message.role}`} key={`${message.role}-${message.id || index}`}><div className="message-avatar">{message.role === "assistant" ? "O" : "G"}</div><div className="message-stack"><div className="bubble">{message.content}</div>{message.activities?.map((activity, i) => <details className="activity-card" key={i}><summary><span>{activityIcon(activity.tool)}</span><div><strong>{activity.tool.replaceAll("_", " ")}</strong><small>{activity.summary}</small></div><b>⌄</b></summary><pre>{JSON.stringify(activity.result || activity.arguments, null, 2)}</pre></details>)}</div></article>)}
          {busy && <article className="message assistant"><div className="message-avatar">O</div><div className="typing"><i/><i/><i/></div></article>}
        </div>
        <form className="composer" onSubmit={send}><textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={project ? "Ask Olladex to inspect, change or test this repository…" : "Open a repository to begin…"} disabled={!project || !session} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} /><div className="composer-actions"><div><button type="button" onClick={() => setTab("files")}>＋ Context</button><button type="button" onClick={() => setTab("terminal")}>⌘ Bash</button></div><div className="model-chip">{project?.model || "qwen3:14b"}</div><button className="send primary" disabled={busy || !prompt.trim()}>➤</button></div></form>
      </section>

      <section className="inspector-panel">
        <div className="inspector-tabs">{(["files", "changes", "terminal", "diagrams", "office"] as Tab[]).map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item}{item === "changes" && changes.length ? <span>{changes.length}</span> : null}</button>)}</div>
        {project ? <>
          {tab === "files" && <div className="file-workspace"><aside className="file-sidebar"><div className="file-search"><span>⌕</span><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Filter files" /></div><FileTree items={filteredTree} selected={selected?.path} onSelect={selectFile} /></aside><div className="editor-pane">{selected?.type === "file" ? <><div className="editor-head"><div><span className="file-icon">□</span><strong>{selected.path}</strong>{fileDraft !== fileContent && <i>Modified</i>}</div><button className="primary" onClick={saveFile} disabled={fileDraft === fileContent}>Save</button></div><textarea className="code-editor" value={fileDraft} onChange={(e) => setFileDraft(e.target.value)} spellCheck={false} /></> : <EmptyWorkspace onOpen={() => setShowOpen(true)} />}</div></div>}
          {tab === "changes" && <div className="changes-panel">
            <div className="git-card"><div><p className="eyebrow">Git repository</p><h3>{git?.repository ? git.branch : "Not initialised"}</h3></div><span>{git?.changes.length || 0} working changes</span></div>
            {gitDiff && <article><header><div><strong>Current Git diff</strong><small>Working tree and staged changes</small></div><span>git</span></header><pre>{gitDiff}</pre></article>}
            {changes.length ? changes.map((change) => <article key={change.id}><header><div><strong>{change.path}</strong><small>{new Date(change.created_at).toLocaleString()}</small></div><span>{change.status}</span></header><pre>{change.diff || "No textual diff"}</pre></article>) : !gitDiff && <div className="empty-panel"><span>◫</span><h3>No changes yet</h3><p>Edits made by you or Olladex will appear here for review.</p></div>}
          </div>}
          {tab === "terminal" && <TerminalPanel projectId={project.id} />}
          {tab === "diagrams" && <DiagramStudio initialSource={diagramSource} initialEngine={diagramEngine} />}
          {tab === "office" && <OfficePanel projectId={project.id} selectedPath={selected?.path} onCreated={refreshTree} />}
        </> : <EmptyWorkspace onOpen={() => setShowOpen(true)} />}
      </section>
    </div>

    {showOpen && <div className="modal-backdrop" onMouseDown={() => setShowOpen(false)}><div className="modal" onMouseDown={(e) => e.stopPropagation()}><div className="modal-head"><div><p className="eyebrow">Local repository</p><h2>Open in Olladex</h2></div><button onClick={() => setShowOpen(false)}>×</button></div><form onSubmit={openProject}><label>Absolute directory path<input autoFocus value={openPath} onChange={(e) => setOpenPath(e.target.value)} placeholder="/home/gez/projects/my-app" /></label><p>Olladex will be confined to this directory. It can read files, create backups, execute Bash commands and work with its Git repository.</p><div><button type="button" onClick={() => setShowOpen(false)}>Cancel</button><button className="primary">Open repository</button></div></form></div></div>}
    {notice && <button className="toast" onClick={() => setNotice("")}>{notice}</button>}
  </main>;
}

function activityIcon(tool: string) { return tool === "run_command" ? "⌘" : tool === "write_file" ? "✎" : tool === "search_code" ? "⌕" : tool === "read_file" ? "□" : "▦"; }

function filterTree(items: TreeNode[], query: string): TreeNode[] {
  return items.flatMap((item) => {
    const children = item.children ? filterTree(item.children, query) : [];
    return item.name.toLowerCase().includes(query) || children.length ? [{ ...item, children }] : [];
  });
}

function EmptyWorkspace({ onOpen }: { onOpen: () => void }) {
  return <div className="empty-workspace"><div className="empty-logo">O</div><h2>Local code, visible work</h2><p>Open a repository to explore files, run Bash commands, create Mermaid and Graphviz diagrams, and work with Office documents.</p><button className="primary" onClick={onOpen}>Open repository</button></div>;
}
