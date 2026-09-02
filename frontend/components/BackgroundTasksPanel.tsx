"use client";

import { FormEvent, useEffect, useState } from "react";
import { request } from "../lib/api";

type BackgroundTask = {
  id: number; session_id: number; title: string; prompt: string; source_kind: string; source_ref: string;
  status: "queued" | "running" | "completed" | "cancelled" | "failed"; result: string; error: string;
  cancel_requested: number; created_at: string; started_at: string; completed_at: string;
};

export function BackgroundTasksPanel({ projectId, onOpenSession }: { projectId: number; onOpenSession: (sessionId: number) => void }) {
  const [tasks, setTasks] = useState<BackgroundTask[]>([]);
  const [prompt, setPrompt] = useState("");
  const [notice, setNotice] = useState("");

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
      setTasks((current) => [created, ...current]); setPrompt(""); setNotice("Task queued");
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function cancel(task: BackgroundTask) {
    try {
      const updated = await request<BackgroundTask>(`/tasks/${task.id}`, { method: "DELETE" });
      setTasks((items) => items.map((item) => item.id === task.id ? updated : item));
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  return <div className="task-queue-panel">
    <section className="queue-compose"><div><p className="eyebrow">Background agent</p><h3>Queue development work</h3><p>Tasks run one at a time and keep their own persistent session history.</p></div><form onSubmit={enqueue}><textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Describe a task Olladex can work through in the background…" /><button className="primary" disabled={!prompt.trim()}>Queue task</button></form></section>
    <section className="queue-list"><div className="queue-head"><div><p className="eyebrow">Persistent queue</p><h3>{tasks.length} recent tasks</h3></div><span>{tasks.filter((task) => task.status === "queued" || task.status === "running").length} active</span></div>
      {tasks.length ? tasks.map((task) => <article key={task.id} className={`queue-task ${task.status}`}><header><div><strong>{task.title}</strong><small>{task.source_kind === "github_issue" ? "GitHub issue" : "Manual task"} · {new Date(task.created_at).toLocaleString()}</small></div><span>{task.cancel_requested && task.status === "running" ? "stopping" : task.status}</span></header><p>{task.prompt}</p>{task.result && <pre>{task.result}</pre>}{task.error && <pre className="queue-error">{task.error}</pre>}<footer><button onClick={() => onOpenSession(task.session_id)}>Open session</button>{(task.status === "queued" || task.status === "running") && <button onClick={() => cancel(task)}>{task.status === "running" ? "Request stop" : "Cancel"}</button>}</footer></article>) : <div className="empty-panel"><span>◷</span><h3>No queued work</h3><p>Queue a prompt here or import an open GitHub issue from the Changes panel.</p></div>}
    </section>{notice && <div className="queue-notice">{notice}</div>}
  </div>;
}
