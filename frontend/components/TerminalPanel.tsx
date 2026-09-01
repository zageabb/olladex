"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { request } from "../lib/api";

type Run = { id: number; command: string; output: string; exit_code: number; status: "pending" | "running" | "completed" | "cancelled" | "timed_out" | "blocked"; created_at?: string };

export function TerminalPanel({ projectId }: { projectId: number }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [command, setCommand] = useState("");
  const [liveInput, setLiveInput] = useState("");
  const [runningId, setRunningId] = useState<number | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    request<Run[]>(`/projects/${projectId}/terminal`).then((data) => {
      const ordered = data.reverse();
      setRuns(ordered);
      const active = ordered.find((run) => run.status === "running");
      if (active) { setRunningId(active.id); poll(active.id); }
    }).catch(() => {});
  }, [projectId]);
  useEffect(() => endRef.current?.scrollIntoView(), [runs]);
  useEffect(() => {
    if (!runningId || !panelRef.current) return;
    const observer = new ResizeObserver(([entry]) => {
      const columns = Math.max(20, Math.min(500, Math.floor(entry.contentRect.width / 8)));
      const rows = Math.max(5, Math.min(200, Math.floor(entry.contentRect.height / 18)));
      request(`/terminal/${runningId}/resize`, { method: "POST", body: JSON.stringify({ columns, rows }) }).catch(() => {});
    });
    observer.observe(panelRef.current);
    return () => observer.disconnect();
  }, [runningId]);

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

  async function sendInput(event: FormEvent) {
    event.preventDefault();
    if (!runningId || !liveInput) return;
    const data = liveInput.endsWith("\n") ? liveInput : `${liveInput}\n`;
    setLiveInput("");
    try { await request(`/terminal/${runningId}/input`, { method: "POST", body: JSON.stringify({ data }) }); }
    catch (error) { setRuns((items) => items.map((item) => item.id === runningId ? { ...item, output: `${item.output}\n${error instanceof Error ? error.message : String(error)}` } : item)); }
  }

  async function sendControl(data: string) {
    if (!runningId) return;
    try { await request(`/terminal/${runningId}/input`, { method: "POST", body: JSON.stringify({ data }) }); }
    catch (error) { setRuns((items) => items.map((item) => item.id === runningId ? { ...item, output: `${item.output}\n${error instanceof Error ? error.message : String(error)}` } : item)); }
  }

  return <div className="terminal-panel" ref={panelRef}>
    <div className="terminal-output">
      <div className="terminal-welcome">Olladex local terminal · /bin/bash · commands run in the selected repository</div>
      {runs.map((run) => <div className="terminal-run" key={run.id}><div><span className="prompt">$</span> {run.command}</div><pre>{run.output || (run.status === "running" ? "Running…" : `(completed with exit code ${run.exit_code})`)}</pre><small className={run.exit_code === 0 ? "ok" : "failed"}>{run.status}{run.exit_code >= 0 ? ` · exit ${run.exit_code}` : ""}</small></div>)}
      <div ref={endRef} />
    </div>
    <div className="terminal-controls">{runningId && <><button onClick={() => sendControl("\u0003")}>Ctrl-C</button><button onClick={() => sendControl("\t")}>Tab</button><button onClick={() => sendControl("\u001b[A")}>↑</button><button onClick={() => sendControl("\u001b[B")}>↓</button><button onClick={() => sendControl("\u001b")}>Esc</button></>}<button onClick={() => setRuns([])}>Clear view</button></div>
    <form className="terminal-input" onSubmit={runningId ? sendInput : execute}><span className="prompt">{runningId ? "›" : "$"}</span><input value={runningId ? liveInput : command} onChange={(e) => runningId ? setLiveInput(e.target.value) : setCommand(e.target.value)} onKeyDown={(event) => { if (runningId && event.ctrlKey && event.key.toLowerCase() === "c") { event.preventDefault(); sendControl("\u0003"); } else if (runningId && event.key === "Tab") { event.preventDefault(); sendControl("\t"); } }} placeholder={runningId ? "Send input to the running command" : "Enter a bash command"} autoComplete="off" />{runningId ? <><button>Send</button><button type="button" onClick={cancel}>Stop</button></> : <button>Run</button>}</form>
  </div>;
}
