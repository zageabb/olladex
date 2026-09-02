"use client";

import { useEffect, useState } from "react";
import { request } from "../lib/api";

type JobStatus = "queued" | "running" | "paused" | "completed" | "failed" | "cancelled";
type Job = { id: number; session_id: number; prompt: string; source: string; status: JobStatus; result_message_id?: number; error: string; created_at: string; started_at: string; completed_at: string };
type Capacity = { workers: number; active: number; available: number };

export function BackgroundJobs({ projectId, onOpenSession }: { projectId: number; onOpenSession: (sessionId: number) => void }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [capacity, setCapacity] = useState<Capacity>({ workers: 0, active: 0, available: 0 });
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const [data, workerCapacity] = await Promise.all([
          request<Job[]>(`/projects/${projectId}/jobs`),
          request<Capacity>(`/projects/${projectId}/jobs-capacity`),
        ]);
        if (active) { setJobs(data); setCapacity(workerCapacity); }
      }
      catch (error) { if (active) setNotice(error instanceof Error ? error.message : String(error)); }
    }
    refresh();
    const timer = window.setInterval(refresh, 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [projectId]);

  async function action(job: Job, action: "pause" | "resume" | "cancel") {
    try {
      await request(`/projects/${projectId}/jobs/${job.id}${action === "cancel" ? "" : `/${action}`}`, { method: action === "cancel" ? "DELETE" : "POST" });
      setJobs(await request<Job[]>(`/projects/${projectId}/jobs`));
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  return <div className="jobs-panel">
    <header><div><p className="eyebrow">Persistent local queue</p><h3>Background agent jobs</h3></div><span>{capacity.active}/{capacity.workers} workers</span></header>
    {notice && <div className="job-notice">{notice}</div>}
    <div className="job-list">{jobs.length ? jobs.map((job) => <article key={job.id} className={`job-card ${job.status}`}>
      <div className="job-state"><i /><strong>{job.status}</strong><small>{job.source.replace("github-issue:", "issue #")}</small></div>
      <p>{job.prompt}</p>
      {job.error && <pre>{job.error}</pre>}
      <footer><span>{new Date(job.created_at).toLocaleString()}</span><div className="job-actions">
        {job.status === "running" && <button onClick={() => action(job, "pause")}>Pause</button>}
        {job.status === "paused" && <button className="primary" onClick={() => action(job, "resume")}>Resume</button>}
        {(job.status === "queued" || job.status === "running" || job.status === "paused") && <button onClick={() => action(job, "cancel")}>Cancel</button>}
        {job.status === "completed" && <button className="primary" onClick={() => onOpenSession(job.session_id)}>Open result</button>}
      </div></footer>
    </article>) : <div className="empty-panel"><span>◷</span><h3>No background jobs</h3><p>Enable Background in the composer or import a GitHub issue to keep work running while you use another task.</p></div>}</div>
  </div>;
}
