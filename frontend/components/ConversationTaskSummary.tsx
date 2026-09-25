"use client";

import { useEffect, useState } from "react";
import { request } from "../lib/api";

type Run = { id: number; status: string };
type Event = { id: number; run_id: number; kind: string; payload: any };

const activeStates = new Set(["running", "waiting_for_input", "waiting_for_approval", "stopping"]);

function phase(status: string) {
  if (status === "running") return "Working";
  if (status === "waiting_for_input") return "Needs input";
  if (status === "waiting_for_approval") return "Needs approval";
  if (status === "completed") return "Complete";
  if (status === "cancelled") return "Stopped";
  if (status === "interrupted") return "Paused";
  if (status === "budget_exhausted") return "Partial";
  if (status === "failed") return "Failed";
  if (status === "stopping") return "Stopping";
  return status.replaceAll("_", " ");
}

export function ConversationTaskSummary({ sessionId, title, onOpenConversation }: { sessionId: number; title: string; onOpenConversation: () => void }) {
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let disposed = false;
    async function refresh() {
      try {
        const runs = await request<Run[]>(`/sessions/${sessionId}/runs`);
        if (disposed) return;
        const latest = runs[runs.length - 1] || null;
        setRun(latest);
        if (!latest) return;
      } catch (e) {
        if (!disposed) setError(e instanceof Error ? e.message : String(e));
      }
    }
    void refresh();
    const timer = window.setInterval(refresh, 2500);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [sessionId]);

  if (!run) return null;

  const toolStarts = events.filter(event => event.kind === "tool_started");
  const approvals = events.filter(event => event.kind === "approval");
  const questions = events.filter(event => event.kind === "question");
  const latestTool = toolStarts[toolStarts.length - 1]?.payload;
  const active = activeStates.has(run.status);

  return <section className={`conversation-task-summary ${active ? "active" : ""}`}>
    <header>
      <div>
        <p className="eyebrow">Conversation task</p>
        <h3>{title || "Current conversation"}</h3>
        <small>Foreground task · run #{run.id}</small>
      </div>
      <span>{phase(run.status)}</span>
    </header>
    <div className="conversation-task-body">
      <div className="conversation-task-metrics">
        <article><span>Phase</span><strong>{phase(run.status)}</strong></article>
        <article><span>Execution</span><strong>Foreground</strong></article>
        <article><span>Attention</span><strong>{run.status === "waiting_for_input" ? "Input needed" : run.status === "waiting_for_approval" ? "Approval needed" : "None"}</strong></article>
      </div>
      {latestTool ? <p className="conversation-task-now">Now: {String(latestTool.tool || "working").replaceAll("_", " ")}{latestTool.arguments?.path ? ` · ${latestTool.arguments.path}` : ""}</p> : null}
      {expanded && <div className="conversation-task-details">
        <div><span>Approvals</span><strong>{approvals.length}</strong></div>
        <div><span>Questions</span><strong>{questions.length}</strong></div>
        <div><span>Execution</span><strong>Foreground conversation</strong></div>
        <p>This task is driven by the open conversation. Steering, approvals and follow-up messages stay in chat while its status is mirrored here.</p>
      </div>}
      {error && <p className="conversation-error">{error}</p>}
    </div>
    <footer>
      <button onClick={() => setExpanded(value => !value)}>{expanded ? "Hide details" : "View task"}</button>
      <button onClick={onOpenConversation}>Open conversation</button>
    </footer>
  </section>;
}
