"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { DiagramStudio } from "../components/DiagramStudio";
import { BackgroundJobs } from "../components/BackgroundJobs";
import { FileTree, TreeNode } from "../components/FileTree";
import { GitControls, GitSummary } from "../components/GitControls";
import { GitHubPanel } from "../components/GitHubPanel";
import { OfficePanel } from "../components/OfficePanel";
import { ProjectPanel } from "../components/ProjectPanel";
import { TerminalPanel } from "../components/TerminalPanel";
import { request } from "../lib/api";

type Project = { id: number; name: string; path: string; model: string; approval_mode: "review" | "assisted" | "autonomous"; instructions: string; git_author_name: string; git_author_email: string; model_profile_id?: number; profile_name?: string; profile_chat_model?: string; profile_embedding_model?: string; profile_temperature?: number; profile_max_steps?: number; profile_context_files?: number; profile_context_chars?: number };
type Session = { id: number; project_id: number; title: string; updated_at: string; summary: string };
type Activity = { tool: string; summary: string; arguments?: Record<string, unknown>; result?: Record<string, any> };
type Message = { id?: number; role: "user" | "assistant"; content: string; activities?: Activity[] };
type Status = { version: string; shell: string; ollama: { connected: boolean; url: string; models: string[]; error?: string } };
type Hunk = { index: number; header: string; lines: string[]; changes: number };
type Change = { id: number; path: string; diff: string; hunks: Hunk[]; status: "proposed" | "applied" | "rejected" | "reverted"; created_at: string; updated_at: string };
type Tab = "files" | "changes" | "terminal" | "jobs" | "diagrams" | "office" | "project";

const WELCOME: Message = { role: "assistant", content: "Welcome to Olladex. Open a local repository, then ask me to inspect, change and test it. Repository tools, your local shell, diagrams and Office files stay on your machine." };

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
  const [selectedHunks, setSelectedHunks] = useState<Record<number, number[]>>({});
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
  const [backgroundMode, setBackgroundMode] = useState(false);

  useEffect(() => {
    request<Project[]>("/projects").then((data) => { setProjects(data); if (data.length) setProject(data[0]); }).catch((e) => setNotice(e.message));
    request<Status>("/status").then(setStatus).catch(() => {});
  }, []);

  useEffect(() => {
    if (!project) return;
    refreshTree();
    request<Session[]>(`/projects/${project.id}/sessions`).then((data) => { setSessions(data); setSession(data[0] || null); });
    refreshChanges(project.id);
    refreshGit(project.id);
  }, [project?.id]);

  useEffect(() => {
    if (!session) { setMessages([WELCOME]); return; }
    request<Message[]>(`/sessions/${session.id}/messages`).then((data) => setMessages(data.length ? data : [WELCOME])).catch(() => setMessages([WELCOME]));
  }, [session?.id]);

  async function refreshTree() {
    if (project) setTree(await request<TreeNode[]>(`/projects/${project.id}/tree`));
  }

  async function refreshChanges(projectId = project?.id) {
    if (!projectId) return;
    const data = await request<Change[]>(`/projects/${projectId}/changes`);
    setChanges(data);
    setSelectedHunks((current) => {
      const next = { ...current };
      for (const change of data) if (change.status === "proposed" && next[change.id] === undefined) next[change.id] = change.hunks.map((hunk) => hunk.index);
      return next;
    });
  }

  async function refreshGit(projectId = project?.id) {
    if (!projectId) return;
    const [summary, currentDiff] = await Promise.all([
      request<GitSummary>(`/projects/${projectId}/git`),
      request<{ diff: string }>(`/projects/${projectId}/git/diff`),
    ]);
    setGit(summary); setGitDiff(currentDiff.diff);
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
    setFileContent(fileDraft); await refreshChanges(project.id); setNotice(`Saved ${selected.path}`);
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    if (!prompt.trim() || !session || !project || busy) return;
    const content = prompt; setPrompt(""); setBusy(true); setMessages((current) => [...current, { role: "user", content }]);
    try {
      if (backgroundMode) {
        await request(`/projects/${project.id}/jobs`, { method: "POST", body: JSON.stringify({ session_id: session.id, prompt: content, source: "composer" }) });
        setMessages((current) => [...current, { role: "assistant", content: "This task is queued in the background. You can continue using Olladex and open the result from Jobs when it completes." }]);
        setTab("jobs"); return;
      }
      const answer = await request<Message>(`/sessions/${session.id}/messages`, { method: "POST", body: JSON.stringify({ content }) });
      setMessages((current) => [...current, answer]); await refreshTree();
      request<{ summary: string }>(`/sessions/${session.id}/summary`).then((summary) => {
        setSession((current) => current ? { ...current, summary: summary.summary } : current);
        setSessions((current) => current.map((item) => item.id === session.id ? { ...item, summary: summary.summary } : item));
      }).catch(() => {});
      if (answer.activities?.some((a) => a.tool === "write_file")) { await refreshChanges(project.id); setTab("changes"); }
    } catch (error) { setMessages((current) => [...current, { role: "assistant", content: `I couldn't complete that request: ${error instanceof Error ? error.message : String(error)}` }]); }
    finally { setBusy(false); }
  }

  async function openSessionById(sessionId: number, targetTab: Tab = "files") {
    if (!project) return;
    const data = await request<Session[]>(`/projects/${project.id}/sessions`);
    setSessions(data);
    const target = data.find((item) => item.id === sessionId);
    if (target) setSession(target);
    setTab(targetTab);
  }

  const filteredTree = useMemo(() => search.trim() ? filterTree(tree, search.toLowerCase()) : tree, [tree, search]);
  const diagramSource = selected && /\.(mmd|mermaid|dot)$/i.test(selected.path) ? fileDraft : undefined;
  const diagramEngine = selected && /\.dot$/i.test(selected.path) ? "dot" as const : "mermaid" as const;

  function toggleHunk(changeId: number, hunkIndex: number) {
    setSelectedHunks((current) => ({ ...current, [changeId]: current[changeId]?.includes(hunkIndex) ? current[changeId].filter((item) => item !== hunkIndex) : [...(current[changeId] || []), hunkIndex] }));
  }

  async function changeAction(change: Change, action: "apply" | "reject" | "revert") {
    if (!project) return;
    const options: RequestInit = { method: "POST" };
    if (action === "apply") options.body = JSON.stringify({ hunk_indexes: selectedHunks[change.id] || [] });
    try {
      await request(`/projects/${project.id}/changes/${change.id}/${action}`, options);
      await Promise.all([refreshChanges(project.id), refreshTree()]);
      refreshGit(project.id);
      setNotice(`${change.path} ${action === "apply" ? "applied" : action === "reject" ? "rejected" : "reverted"}`);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function approveCommand(activity: Activity) {
    if (!project || !activity.result?.command_run_id) return;
    try {
      await request(`/projects/${project.id}/terminal/${activity.result.command_run_id}/approve`, { method: "POST" });
      setTab("terminal"); setNotice("Command approved and started");
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  return <main className="app-shell">
    <header className="topbar">
      <div className="brand"><span className="brand-mark">O</span><span>Olladex</span><em>v{status?.version || "0.7 dev"}</em></div>
      <div className="project-selector"><span>Repository</span><select value={project?.id || ""} onChange={(e) => setProject(projects.find((p) => p.id === Number(e.target.value)) || null)}><option value="">Open a repository</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
      <button className="global-search" onClick={() => setTab("files")}>⌕ Search this repository <kbd>⌘ K</kbd></button>
      <div className={`connection ${status?.ollama.connected ? "online" : ""}`}><i />{status?.ollama.connected ? `${project?.profile_chat_model || project?.model || status.ollama.models[0] || "Ollama"}` : "Ollama offline"}</div>
      <button className="avatar">GA</button>
    </header>

    <aside className="rail">
      <button className="active"><span>✦</span><small>Agent</small></button>
      <button onClick={() => setTab("files")}><span>▦</span><small>Files</small></button>
      <button onClick={() => setTab("terminal")}><span>⌘</span><small>Terminal</small></button>
      <button onClick={() => setTab("jobs")}><span>◷</span><small>Jobs</small></button>
      <button onClick={() => setTab("diagrams")}><span>◇</span><small>Diagrams</small></button>
      <button onClick={() => setTab("office")}><span>▤</span><small>Office</small></button>
      <div className="rail-bottom"><button onClick={() => setTab("project")}><span>⚙</span><small>Project</small></button></div>
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
        <div className="panel-head"><div><p className="eyebrow">Local development agent</p><h1>{session?.title || "Start a task"}</h1></div><button className="approval-mode" onClick={() => setTab("project")}><span>Mode</span><strong>{project?.approval_mode || "assisted"}</strong></button></div>
        <div className="messages">
          {session?.summary && <details className="session-summary"><summary><span>✦</span><div><strong>Persistent session context</strong><small>Compact memory carried into the next Ollama request</small></div><b>⌄</b></summary><pre>{session.summary}</pre></details>}
          {messages.map((message, index) => <article className={`message ${message.role}`} key={`${message.role}-${message.id || index}`}><div className="message-avatar">{message.role === "assistant" ? "O" : "G"}</div><div className="message-stack"><div className="bubble">{message.content}</div>{message.activities?.map((activity, i) => <details className="activity-card" key={i}><summary><span>{activityIcon(activity.tool)}</span><div><strong>{activity.tool.replaceAll("_", " ")}</strong><small>{activity.summary}</small></div><b>⌄</b></summary><pre>{JSON.stringify(activity.result || activity.arguments, null, 2)}</pre>{activity.tool === "run_command" && activity.result?.status === "pending" && <div className="activity-actions"><button className="primary" onClick={() => approveCommand(activity)}>Approve command</button><button onClick={() => setTab("terminal")}>Open terminal</button></div>}{activity.tool === "write_file" && activity.result?.change_id && <div className="activity-actions"><button className="primary" onClick={() => setTab("changes")}>Review proposed change</button></div>}</details>)}</div></article>)}
          {busy && <article className="message assistant"><div className="message-avatar">O</div><div className="typing"><i/><i/><i/></div></article>}
        </div>
        <form className="composer" onSubmit={send}><textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder={project ? "Ask Olladex to inspect, change or test this repository…" : "Open a repository to begin…"} disabled={!project || !session} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} /><div className="composer-actions"><div><button type="button" onClick={() => setTab("files")}>＋ Context</button><button type="button" onClick={() => setTab("terminal")}>⌘ Shell</button><button type="button" className={backgroundMode ? "active" : ""} onClick={() => setBackgroundMode((value) => !value)}>◷ Background</button></div><div className="model-chip">{project?.profile_chat_model || project?.model || "qwen3:14b"}</div><button className="send primary" disabled={busy || !prompt.trim()}>➤</button></div></form>
      </section>

      <section className="inspector-panel">
        <div className="inspector-tabs">{(["files", "changes", "terminal", "jobs", "diagrams", "office", "project"] as Tab[]).map((item) => <button key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item}{item === "changes" && changes.filter((change) => change.status === "proposed").length ? <span>{changes.filter((change) => change.status === "proposed").length}</span> : null}</button>)}</div>
        {project ? <>
          {tab === "files" && <div className="file-workspace"><aside className="file-sidebar"><div className="file-search"><span>⌕</span><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Filter files" /></div><FileTree items={filteredTree} selected={selected?.path} onSelect={selectFile} /></aside><div className="editor-pane">{selected?.type === "file" ? <><div className="editor-head"><div><span className="file-icon">□</span><strong>{selected.path}</strong>{fileDraft !== fileContent && <i>Modified</i>}</div><button className="primary" onClick={saveFile} disabled={fileDraft === fileContent}>Save</button></div><textarea className="code-editor" value={fileDraft} onChange={(e) => setFileDraft(e.target.value)} spellCheck={false} /></> : <EmptyWorkspace onOpen={() => setShowOpen(true)} />}</div></div>}
          {tab === "changes" && <div className="changes-panel">
            <GitControls projectId={project.id} git={git} onRefresh={() => refreshGit(project.id)} />
            {git?.repository && <GitHubPanel projectId={project.id} git={git} onJobCreated={(sessionId) => openSessionById(sessionId, "jobs")} />}
            {gitDiff && <article><header><div><strong>Current Git diff</strong><small>Working tree and staged changes</small></div><span>git</span></header><pre>{gitDiff}</pre></article>}
            {changes.length ? changes.map((change) => <article className={change.status === "proposed" ? "proposed-change" : ""} key={change.id}><header><div><strong>{change.path}</strong><small>{new Date(change.created_at).toLocaleString()}</small></div><span className={`change-status ${change.status}`}>{change.status}</span></header>{change.status === "proposed" ? <div className="hunk-list">{change.hunks.map((hunk) => <label className="diff-hunk" key={hunk.index}><div><input type="checkbox" checked={(selectedHunks[change.id] || []).includes(hunk.index)} onChange={() => toggleHunk(change.id, hunk.index)} /><strong>{hunk.header}</strong><span>{hunk.changes} changed lines</span></div><pre>{hunk.lines.join("\n")}</pre></label>)}<div className="change-actions"><button className="primary" disabled={!(selectedHunks[change.id] || []).length} onClick={() => changeAction(change, "apply")}>Apply selected hunks</button><button onClick={() => changeAction(change, "reject")}>Reject proposal</button></div></div> : <><pre>{change.diff || "No textual diff"}</pre>{change.status === "applied" && <div className="change-actions"><button onClick={() => changeAction(change, "revert")}>Revert safely</button></div>}</>}</article>) : !gitDiff && <div className="empty-panel"><span>◫</span><h3>No changes yet</h3><p>Edits made by you or Olladex will appear here for review.</p></div>}
          </div>}
          {tab === "terminal" && <TerminalPanel projectId={project.id} />}
          {tab === "jobs" && <BackgroundJobs projectId={project.id} onOpenSession={(sessionId) => openSessionById(sessionId, "files")} />}
          {tab === "diagrams" && <DiagramStudio initialSource={diagramSource} initialEngine={diagramEngine} />}
          {tab === "office" && <OfficePanel projectId={project.id} selectedPath={selected?.path} onCreated={refreshTree} />}
          {tab === "project" && <ProjectPanel project={project} onUpdated={(updated) => { setProject(updated); setProjects((items) => items.map((item) => item.id === updated.id ? updated : item)); }} />}
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
