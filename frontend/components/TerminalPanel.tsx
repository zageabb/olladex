"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { request } from "../lib/api";

type Run = { id: number; command: string; output: string; exit_code: number; status: "pending" | "running" | "completed" | "cancelled" | "timed_out" | "blocked"; created_at?: string };

export function TerminalPanel({ projectId }: { projectId: number }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [command, setCommand] = useState("");
  const [runningId, setRunningId] = useState<number | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    request<Run[]>(`/projects/${projectId}/terminal`).then((data) => {
      const ordered = data.reverse();
      setRuns(ordered);
      const active = ordered.find((run) => run.status === "running");
      if (active) { setRunningId(active.id); poll(active.id); }
    }).catch(() => {});
  }, [projectId]);
  useEffect(() => endRef.current?.scrollIntoView(), [runs]);

  async function execute(event: FormEvent) {
    event.preventDefault();
    if (!command.trim() || runningId) return;
    const sent = command;
    setCommand("");
    try {
      const run = await request<Run>(`/projects/${projectId}/terminal/start`, { method: "POST", body: JSON.stringify({ command: sent }) });
      setRuns((current) => [...current, run]);
      setRunningId(run.id);
      poll(run.id);
    } catch (error) {
      setRuns((current) => [...current, { id: Date.now(), command: sent, output: error instanceof Error ? error.message : String(error), exit_code: 1, status: "completed" }]);
    }
  }

  async function poll(id: number) {
    try {
      const current = await request<Run>(`/terminal/${id}`);
      setRuns((items) => items.map((item) => item.id === id ? { ...item, ...current } : item));
      if (current.status === "running" || current.status === "pending") {
        window.setTimeout(() => poll(id), 350);
      } else {
        setRunningId(null);
      }
    } catch {
      setRunningId(null);
    }
  }

  async function cancel() {
    if (!runningId) return;
    await request(`/terminal/${runningId}`, { method: "DELETE" });
    poll(runningId);
  }

  return <div className="terminal-panel">
    <div className="terminal-output">
      <div className="terminal-welcome">Olladex local terminal · /bin/bash · commands run in the selected repository</div>
      {runs.map((run) => <div className="terminal-run" key={run.id}><div><span className="prompt">$</span> {run.command}</div><pre>{run.output || (run.status === "running" ? "Running…" : `(completed with exit code ${run.exit_code})`)}</pre><small className={run.exit_code === 0 ? "ok" : "failed"}>{run.status}{run.exit_code >= 0 ? ` · exit ${run.exit_code}` : ""}</small></div>)}
      <div ref={endRef} />
    </div>
    <form className="terminal-input" onSubmit={execute}><span className="prompt">$</span><input value={command} onChange={(e) => setCommand(e.target.value)} placeholder="Enter a bash command" autoComplete="off" disabled={Boolean(runningId)} />{runningId ? <button type="button" onClick={cancel}>Stop</button> : <button>Run</button>}</form>
  </div>;
}
