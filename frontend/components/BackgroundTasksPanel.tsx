"use client";

import { FormEvent, useEffect, useState } from "react";
import { request } from "../lib/api";

type BackgroundTask = {
  id: number; session_id: number; title: string; prompt: string; source_kind: string; source_ref: string;
  status: "queued" | "running" | "completed" | "cancelled" | "failed"; result: string; error: string;
  cancel_requested: number; created_at: string; started_at: string; completed_at: string;
  worktree_path?: string; worktree_branch?: string;
};

type WorktreeSummary = {
  task_id: number; path: string; branch: string; head: string; base: string; base_sha: string;
  changes: string[]; branch_diff: string; working_diff: string;
};

type PromotionDraft = { commit: string; title: string; body: string; base: string };

export function BackgroundTasksPanel({ projectId, onOpenSession }: { projectId: number; onOpenSession: (sessionId: number) => void }) {
  const [tasks, setTasks] = useState<BackgroundTask[]>([]);
  const [worktrees, setWorktrees] = useState<Record<number, WorktreeSummary>>({});
  const [drafts, setDrafts] = useState<Record<number, PromotionDraft>>({});
  const [prompt, setPrompt] = useState("");
  const [notice, setNotice] = useState("");
  const [busyTask, setBusyTask] = useState<number | null>(null);

  useEffect(() => {
    let disposed = false;
    async function refresh() {
      try {
        const data = await request<BackgroundTask[]>(`/projects/${projectId}/tasks`);
        if (disposed) return;
        setTasks(data);
        setDrafts((current) => {
          const next = { ...current };
          for (const task of data) if (!next[task.id]) next[task.id] = { commit: task.title, title: task.title, body: `Implemented by Olladex background task #${task.id}.`, base: "main" };
          return next;
        });
      } catch (error) {
        if (!disposed) setNotice(error instanceof Error ? error.message : String(error));
      }
    }
    refresh();
    const timer = window.setInterval(refresh, 1000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [projectId]);

  async function enqueue(event: FormEvent) {
    event.preventDefault();
    if (!prompt.trim()) return;
    try {
      const created = await request<BackgroundTask>(`/projects/${projectId}/tasks`, { method: "POST", body: JSON.stringify({ prompt: prompt.trim() }) });
      setTasks((current) => [created, ...current]); setPrompt(""); setNotice("Task queued in an isolated agent workspace");
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function cancel(task: BackgroundTask) {
    try {
      const updated = await request<BackgroundTask>(`/tasks/${task.id}`, { method: "DELETE" });
      setTasks((items) => items.map((item) => item.id === task.id ? updated : item));
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function inspectWorktree(task: BackgroundTask) {
    setBusyTask(task.id);
    try {
      const summary = await request<WorktreeSummary>(`/tasks/${task.id}/worktree?base=${encodeURIComponent(drafts[task.id]?.base || "main")}`);
      setWorktrees((current) => ({ ...current, [task.id]: summary }));
      setNotice(`Loaded ${summary.branch}`);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusyTask(null); }
  }

  function updateDraft(taskId: number, field: keyof PromotionDraft, value: string) {
    setDrafts((current) => ({ ...current, [taskId]: { ...(current[taskId] || { commit: "", title: "", body: "", base: "main" }), [field]: value } }));
  }

  async function commitTask(task: BackgroundTask) {
    const message = drafts[task.id]?.commit.trim();
    if (!message) return;
    setBusyTask(task.id);
    try {
      const summary = await request<WorktreeSummary>(`/tasks/${task.id}/worktree/commit`, { method: "POST", body: JSON.stringify({ message }) });
      setWorktrees((current) => ({ ...current, [task.id]: summary }));
      setNotice(`Committed ${summary.branch}`);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusyTask(null); }
  }

  async function pushTask(task: BackgroundTask) {
    setBusyTask(task.id);
    try {
      const result = await request<{ branch: string }>(`/tasks/${task.id}/worktree/push`, { method: "POST", body: JSON.stringify({ remote: "origin" }) });
      setNotice(`Pushed ${result.branch} to origin`);
      await inspectWorktree(task);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); setBusyTask(null); }
  }

  async function createPullRequest(task: BackgroundTask) {
    const draft = drafts[task.id];
    if (!draft?.title.trim()) return;
    setBusyTask(task.id);
    try {
      const result = await request<{ url: string; branch: string }>(`/tasks/${task.id}/worktree/pull-request`, {
        method: "POST", body: JSON.stringify({ title: draft.title.trim(), body: draft.body, base: draft.base || "main" }),
      });
      setNotice(result.url ? `Pull request created: ${result.url}` : `Pull request created from ${result.branch}`);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusyTask(null); }
  }

  async function cleanupTask(task: BackgroundTask, force = false) {
    setBusyTask(task.id);
    try {
      await request(`/tasks/${task.id}/worktree/cleanup`, { method: "POST", body: JSON.stringify({ force }) });
      setTasks((current) => current.map((item) => item.id === task.id ? { ...item, worktree_path: "", worktree_branch: "" } : item));
      setWorktrees((current) => { const next = { ...current }; delete next[task.id]; return next; });
      setNotice(`Cleaned up task #${task.id} worktree`);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusyTask(null); }
  }

  return <div className="task-queue-panel">
    <section className="queue-compose"><div><p className="eyebrow">Parallel background agents</p><h3>Queue development work</h3><p>Git repositories run queued jobs in isolated task branches and worktrees, so multiple agents can work safely in parallel.</p></div><form onSubmit={enqueue}><textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Describe a task Olladex can work through in the background…" /><button className="primary" disabled={!prompt.trim()}>Queue task</button></form></section>
    <section className="queue-list"><div className="queue-head"><div><p className="eyebrow">Persistent queue</p><h3>{tasks.length} recent tasks</h3></div><span>{tasks.filter((task) => task.status === "queued" || task.status === "running").length} active</span></div>
      {tasks.length ? tasks.map((task) => {
        const worktree = worktrees[task.id]; const draft = drafts[task.id];
        return <article key={task.id} className={`queue-task ${task.status}`}>
          <header><div><strong>{task.title}</strong><small>{task.source_kind === "github_issue" ? "GitHub issue" : "Manual task"} · {new Date(task.created_at).toLocaleString()}</small>{task.worktree_branch && <small>Branch · {task.worktree_branch}</small>}</div><span>{task.cancel_requested && task.status === "running" ? "stopping" : task.status}</span></header>
          <p>{task.prompt}</p>{task.result && <pre>{task.result}</pre>}{task.error && <pre className="queue-error">{task.error}</pre>}
          {worktree && <details className="activity-card" open><summary><span>⑂</span><div><strong>{worktree.branch}</strong><small>{worktree.changes.length} working changes · base {worktree.base}</small></div><b>⌄</b></summary>
            <div className="task-promotion-form">
              <label>Commit message<input value={draft?.commit || ""} onChange={(event) => updateDraft(task.id, "commit", event.target.value)} /></label>
              <div className="activity-actions"><button disabled={busyTask === task.id || worktree.changes.length === 0 || !draft?.commit.trim()} className="primary" onClick={() => commitTask(task)}>Commit approved work</button><button disabled={busyTask === task.id} onClick={() => pushTask(task)}>Push branch</button></div>
              <label>PR title<input value={draft?.title || ""} onChange={(event) => updateDraft(task.id, "title", event.target.value)} /></label>
              <label>Base<input value={draft?.base || "main"} onChange={(event) => updateDraft(task.id, "base", event.target.value)} /></label>
              <label>Description<textarea value={draft?.body || ""} onChange={(event) => updateDraft(task.id, "body", event.target.value)} /></label>
              <div className="activity-actions"><button disabled={busyTask === task.id || !draft?.title.trim()} onClick={() => createPullRequest(task)}>Create PR</button>{task.status !== "running" && task.status !== "queued" && <button disabled={busyTask === task.id} onClick={() => cleanupTask(task)}>Clean up worktree</button>}</div>
            </div>
            {(worktree.working_diff || worktree.branch_diff) ? <pre>{worktree.working_diff || worktree.branch_diff}</pre> : <p>No diff against {worktree.base}.</p>}
          </details>}
          <footer><button onClick={() => onOpenSession(task.session_id)}>Open session</button>{task.worktree_path && <button onClick={() => inspectWorktree(task)} disabled={busyTask === task.id}>{busyTask === task.id ? "Working…" : worktree ? "Refresh branch" : "Review branch"}</button>}{(task.status === "queued" || task.status === "running") && <button onClick={() => cancel(task)}>{task.status === "running" ? "Request stop" : "Cancel"}</button>}</footer>
        </article>;
      }) : <div className="empty-panel"><span>◷</span><h3>No queued work</h3><p>Queue a prompt here or import an open GitHub issue from the Changes panel.</p></div>}
    </section>{notice && <div className="queue-notice">{notice}</div>}
  </div>;
}
