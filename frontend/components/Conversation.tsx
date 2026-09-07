"use client";
import { FormEvent, useEffect, useRef, useState } from "react";
import { request, streamEvents } from "../lib/api";

type Run = { id: number; status: string };
type Event = { id: number; run_id: number; kind: string; payload: any };
const activeStates = ["running", "waiting_for_input", "waiting_for_approval", "stopping"];

export function Conversation({ sessionId, onChanged }: { sessionId: number; onChanged: () => void }) {
  const [runs, setRuns] = useState<Run[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [legacy, setLegacy] = useState<any[]>([]);
  const [memory, setMemory] = useState("");
  const [prompt, setPrompt] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [ready, setReady] = useState(false);
  const tail = useRef<HTMLDivElement>(null);
  const changed = useRef(onChanged); changed.current = onChanged;
  const following = useRef(true);
  const seen = useRef(new Map<number, number>());
  const controllers = useRef(new Map<number, AbortController>());
  const mounted = useRef(true);
  const current = runs[runs.length - 1];
  const active = current && activeStates.includes(current.status);

  useEffect(() => {
    mounted.current = true;
    let disposed = false;
    async function watch(run: Run) {
      if (controllers.current.has(run.id)) return;
      const controller = new AbortController(); controllers.current.set(run.id, controller);
      let completed = false;
      while (!controller.signal.aborted && !completed) {
        try {
          await streamEvents(run.id, seen.current.get(run.id) || 0, controller.signal, event => {
            if (disposed) return;
            if (event.kind === "end") {
              completed = true;
              setRuns(items => items.map(item => item.id === run.id ? { ...item, status: event.payload.status } : item));
              changed.current();
              return;
            }
            if (event.id <= (seen.current.get(run.id) || 0)) return;
            seen.current.set(run.id, event.id);
            setEvents(items => [...items, event]);
            if (event.kind === "memory") setMemory(value => (value + "\n" + event.payload.remembered).trim());
            if (event.kind === "status") setRuns(items => items.map(item => item.id === run.id ? { ...item, status: event.payload.status } : item));
          });
        } catch (e) {
          if (!controller.signal.aborted) setError("Connection interrupted. Reconnecting to saved progress…");
        }
        if (!completed && !controller.signal.aborted) await new Promise(resolve => setTimeout(resolve, 1000));
      }
    }
    async function refresh() {
      try {
        const data = await request<Run[]>(`/sessions/${sessionId}/runs`);
        if (disposed) return;
        setRuns(data); setReady(true);
        for (const run of data) void watch(run);
      } catch (e) { if (!disposed) setError(String(e)); }
    }
    request<any[]>(`/sessions/${sessionId}/messages`).then(data => { if (!disposed) setLegacy(data.filter(item => !item.run_id)); }).catch(e => { if (!disposed) setError(String(e)); });
    request<{ content: string }>(`/sessions/${sessionId}/memory`).then(data => { if (!disposed) setMemory(data.content); }).catch(() => {});
    void refresh();
    const timer = setInterval(refresh, 1500);
    return () => { disposed = true; mounted.current = false; clearInterval(timer); for (const c of controllers.current.values()) c.abort(); controllers.current.clear(); };
  }, [sessionId]);

  useEffect(() => { if (following.current) tail.current?.scrollIntoView({ block: "nearest" }); }, [events]);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!prompt.trim() || sending || !ready) return;
    const content = prompt.trim(); setSending(true); setError("");
    try {
      if (active) await request(`/runs/${current.id}/input`, { method: "POST", body: JSON.stringify({ content }) });
      else {
        const run = await request<Run>(`/sessions/${sessionId}/runs`, { method: "POST", body: JSON.stringify({ content }) });
        if (mounted.current) setRuns(items => [...items.filter(item => item.id !== run.id), run]);
      }
      if (mounted.current) setPrompt("");
    } catch (e) { if (mounted.current) setError(String(e)); }
    finally { if (mounted.current) setSending(false); }
  }

  async function act(path: string, body?: unknown, method = "POST") {
    try { setError(""); await request(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) }); }
    catch (e) { if (mounted.current) setError(String(e)); }
  }

  // Coalesce token events for readable, stable text blocks while retaining tool order.
  const timeline: Event[] = [];
  for (const event of [...events].sort((a, b) => a.id - b.id)) {
    const last = timeline[timeline.length - 1];
    if (["text_delta", "command_output"].includes(event.kind) && last?.kind === event.kind && last.run_id === event.run_id) {
      last.payload = { text: last.payload.text + event.payload.text };
    } else if (!["assistant_start", "assistant_end", "status"].includes(event.kind)) timeline.push({ ...event });
  }
  const decided = new Set(events.filter(e => e.kind === "approval_decided").map(e => e.payload.command_run_id));
  return <>
    <details className="conversation-memory"><summary>Saved preferences and decisions</summary><textarea aria-label="Saved preferences and decisions" value={memory} onChange={e => setMemory(e.target.value)} maxLength={8000} /><button onClick={() => act(`/sessions/${sessionId}/memory`, { content: memory }, "PUT")}>Save context</button></details>
    <div className="messages live-messages" role="log" aria-label="Conversation" onScroll={e => {
      const el = e.currentTarget; following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
    }}>
      {legacy.map(item => <article key={item.id} className={`message ${item.role}`}><div className="bubble">{item.content}</div></article>)}
      {!legacy.length && !timeline.length && <div className="conversation-welcome"><h2>What would you like to work on?</h2><p>Discuss an idea, ask a question, or describe a change. You can add guidance while I work.</p></div>}
      {timeline.map(event => {
        const p = event.payload;
        if (event.kind === "final") {
          if (events.some(e => e.run_id === event.run_id && e.kind === "assistant_end" && e.payload.content === p.content)) return null;
          return <article key={event.id} className="message assistant"><div className="bubble">{p.content}</div></article>;
        }
        if (event.kind === "text_delta" || event.kind === "user_message") return <article key={event.id} className={`message ${event.kind === "user_message" ? "user" : "assistant"}`}><div className="message-avatar">{event.kind === "user_message" ? "You" : "O"}</div><div className="bubble">{p.text || p.content}</div></article>;
        if (event.kind === "command_output") return <pre key={event.id} className="live-command-output">{p.text}</pre>;
        if (event.kind === "tool_started") return <div key={event.id} className="live-progress">{p.tool.replaceAll("_", " ")} {p.arguments?.path || ""}</div>;
        if (event.kind === "tool_result") return <details key={event.id} className="activity-card"><summary>{p.summary}</summary><pre>{JSON.stringify(p.result, null, 2)}</pre></details>;
        if (event.kind === "change_approval") return <section key={event.id} className="interaction-card"><strong>Review {p.path}</strong><pre>{p.diff}</pre>{current?.id === event.run_id && active && !events.some(e => e.kind === "tool_result" && e.payload.result?.change_id === p.change_id) && <div><button onClick={() => act(`/projects/${p.project_id}/changes/${p.change_id}/apply`, {})}>Apply change</button><button onClick={() => act(`/projects/${p.project_id}/changes/${p.change_id}/reject`)}>Reject</button></div>}</section>;
        if (event.kind === "approval") return <section key={event.id} className="interaction-card"><strong>Command approval</strong><pre>{p.command}</pre><small>Working directory: {p.cwd}</small>{!decided.has(p.command_run_id) && current?.id === event.run_id && active ? <div><button onClick={() => act(`/commands/${p.command_run_id}/decision`, { accepted: true })}>Approve once</button><button onClick={() => act(`/commands/${p.command_run_id}/decision`, { accepted: false })}>Decline</button></div> : <p>Approval closed</p>}</section>;
        if (event.kind === "question") return <section key={event.id} className="interaction-card"><strong>{p.question}</strong>{current?.id === event.run_id && current.status === "waiting_for_input" && <p>Reply below to continue.</p>}</section>;
        if (event.kind === "plan") return <ol key={event.id} className="interaction-card">{p.steps.map((s: string, i: number) => <li key={i}>{s}</li>)}</ol>;
        if (event.kind === "error") return <p role="alert" key={event.id}>{p.message}</p>;
        if (event.kind === "memory") return <p key={event.id} className="live-progress">Remembered: {p.remembered}</p>;
        if (event.kind === "progress") return <p key={event.id} className="live-progress">{p.message}</p>;
        return null;
      })}
      {current && <div className="run-status" role="status">{current.status.replaceAll("_", " ")}</div>}
      {current && ["interrupted", "cancelled", "budget_exhausted", "failed"].includes(current.status) && <section className="interaction-card"><p>Completed work is retained. Review the activity before continuing; an interrupted command may have changed files.</p><button onClick={() => act(`/sessions/${sessionId}/runs`, { content: "Continue the task. Inspect saved work and uncertain command outcomes before making further changes.", resume_id: current.id })}>Continue from saved context</button></section>}
      <div ref={tail} />
    </div>
    {error && <p className="conversation-error" role="alert">{error}</p>}
    <form className="composer" onSubmit={send}><textarea aria-label="Message Olladex" value={prompt} onChange={e => setPrompt(e.target.value)} placeholder={active ? "Add guidance, ask a question, or answer below…" : "Discuss an idea or ask Olladex to work on it…"} onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} /><div className="composer-actions"><span>{active ? "Your message will be read at the next safe boundary" : "Local conversation · reviewable changes"}</span>{active && <button type="button" onClick={() => act(`/runs/${current.id}`, undefined, "DELETE")}>Stop</button>}<button className="primary" disabled={!prompt.trim() || sending || !ready}>{active ? current.status === "waiting_for_input" ? "Reply" : "Send guidance" : "Send"}</button></div></form>
  </>;
}
