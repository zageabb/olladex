"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { request } from "../lib/api";

type Run = { id: number; command: string; output: string; exit_code: number; created_at?: string };

export function TerminalPanel({ projectId }: { projectId: number }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [command, setCommand] = useState("");
  const [running, setRunning] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { request<Run[]>(`/projects/${projectId}/terminal`).then((data) => setRuns(data.reverse())).catch(() => {}); }, [projectId]);
  useEffect(() => endRef.current?.scrollIntoView(), [runs]);

  async function execute(event: FormEvent) {
    event.preventDefault();
    if (!command.trim() || running) return;
    const sent = command;
    setCommand(""); setRunning(true);
    try {
      const run = await request<Run>(`/projects/${projectId}/terminal`, { method: "POST", body: JSON.stringify({ command: sent }) });
      setRuns((current) => [...current, run]);
    } catch (error) {
      setRuns((current) => [...current, { id: Date.now(), command: sent, output: error instanceof Error ? error.message : String(error), exit_code: 1 }]);
    } finally { setRunning(false); }
  }

  return <div className="terminal-panel">
    <div className="terminal-output">
      <div className="terminal-welcome">Olladex local terminal · /bin/bash · commands run in the selected repository</div>
      {runs.map((run) => <div className="terminal-run" key={run.id}><div><span className="prompt">$</span> {run.command}</div><pre>{run.output || `(completed with exit code ${run.exit_code})`}</pre><small className={run.exit_code === 0 ? "ok" : "failed"}>exit {run.exit_code}</small></div>)}
      {running && <div className="terminal-run"><span className="prompt">$</span> running…</div>}
      <div ref={endRef} />
    </div>
    <form className="terminal-input" onSubmit={execute}><span className="prompt">$</span><input value={command} onChange={(e) => setCommand(e.target.value)} placeholder="Enter a bash command" autoComplete="off" /><button disabled={running}>Run</button></form>
  </div>;
}

