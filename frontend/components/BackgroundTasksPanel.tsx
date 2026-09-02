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

export function BackgroundTasksPanel({ projectId, onOpenSession }: { projectId: number; onOpenSession: (sessionId: number) => void }) {
  const [tasks, setTasks] = useState<BackgroundTask[]>([]);
  const [worktrees, setWorktrees] = useState<Record<number, WorktreeSummary>>({});
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
      const summary = await request<WorktreeSummary>(`/tasks/${task.id}/worktree`);
      setWorktrees((current) => ({ ...current, [task.id]: summary }));
      setNotice(`Loaded ${summary.branch}`);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusyTask(null); }
  }

  async function commitTask(task: BackgroundTask) {
    const message = window.prompt("Commit message", task.title);
    if (!message?.trim()) return;
    setBusyTask(task.id);
    try {
      const summary = await request<WorktreeSummary>(`/tasks/${task.id}/worktree/commit`, { method: "POST", body: JSON.stringify({ message: message.trim() }) });
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
    const title = window.prompt("Pull request title", task.title);
    if (!title?.trim()) return;
    const body = window.prompt("Pull request description", `Implemented by Olladex background task #${task.id}.`) ?? "";
    setBusyTask(task.id);
    try {
      const result = await request<{ url: string; branch: string }>(`/tasks/${task.id}/worktree/pull-request`, {
        method: "POST", body: JSON.stringify({ title: title.trim(), body, base: "main" }),
      });
      setNotice(result.url ? `Pull request created: ${result.url}` : `Pull request created from ${result.branch}`);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusyTask(null); }
  }

  return <div className="task-queue-panel">
    <section className="queue-compose"><div><p className="eyebrow">Parallel background agents</p><h3>Queue development work</h3><p>Git repositories run queued jobs in isolated task branches and worktrees, so multiple agents can work safely in parallel.</p></div><form onSubmit={enqueue}><textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Describe a task Olladex can work through in the background…" /><button className="primary" disabled={!prompt.trim()}>Queue task</button></form></section>
    <section className="queue-list"><div className="queue-head"><div><p className="eyebrow">Persistent queue</p><h3>{tasks.length} recent tasks</h3></div><span>{tasks.filter((task) => task.status === "queued" || task.status === "running").length} active</span></div>
      {tasks.length ? tasks.map((task) => {
        const worktree = worktrees[task.id];
        return <article key={task.id} className={`queue-task ${task.status}`}>
          <header><div><strong>{task.title}</strong><small>{task.source_kind === "github_issue" ? "GitHub issue" : "Manual task"} · {new Date(task.created_at).toLocaleString()}</small>{task.worktree_branch && <small>Branch · {task.worktree_branch}</small>}</div><span>{task.cancel_requested && task.status === "running" ? "stopping" : task.status}</span></header>
          <p>{task.prompt}</p>{task.result && <pre>{task.result}</pre>}{task.error && <pre className="queue-error">{task.error}</pre>}
          {worktree && <details className="activity-card" open><summary><span>⑂</span><div><strong>{worktree.branch}</strong><small>{worktree.changes.length} working changes · base {worktree.base}</small></div><b>⌄</b></summary><div className="activity-actions"><button onClick={() => inspectWorktree(task)}>Refresh diff</button>{worktree.changes.length > 0 && <button className="primary" onClick={() => commitTask(task)}>Commit approved work</button>}<button onClick={() => pushTask(task)}>Push branch</button><button onClick={() => createPullRequest(task)}>Create PR</button></div>{(worktree.working_diff || worktree.branch_diff) ? <pre>{worktree.working_diff || worktree.branch_diff}</pre> : <p>No diff against {worktree.base}.</p>}</details>}
          <footer><button onClick={() => onOpenSession(task.session_id)}>Open session</button>{task.worktree_path && <button onClick={() => inspectWorktree(task)} disabled={busyTask === task.id}>{busyTask === task.id ? "Working…" : worktree ? "Refresh branch" : "Review branch"}</button>}{(task.status === "queued" || task.status === "running") && <button onClick={() => cancel(task)}>{task.status === "running" ? "Request stop" : "Cancel"}</button>}</footer>
        </article>;
      }) : <div className="empty-panel"><span>◷</span><h3>No queued work</h3><p>Queue a prompt here or import an open GitHub issue from the Changes panel.</p></div>}
    </section>{notice && <div className="queue-notice">{notice}</div>}
  </div>;
}
