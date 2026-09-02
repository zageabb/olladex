"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { request } from "../lib/api";

type Node = {
  id: number; title: string; status: string; agent_role: string; parent_task_id?: number | null;
  depends_on: number[]; children: number[]; worktree_branch: string; pr_number: number; pr_state: string;
  result?: string; error?: string;
};

type Graph = { project_id: number; nodes: Node[] };
type ReviewItem = { id: number; title: string; agent_role: string; status: string; depends_on: number[]; worktree_branch: string; pull_request_number: number; pull_request_state: string; result?: string; error?: string; branch?: { branch_diff: string; working_diff: string; changes: string[] } | null; branch_error?: string };
type ReviewBundle = { task_id: number; base: string; items: ReviewItem[] };
type Draft = { title: string; prompt: string; role: string; parent: string; dependencies: string };
type LeadDraft = { title: string; objective: string; maxTasks: number };
type LeadResponse = { lead: Node; specialists: unknown[]; reviewer: unknown; plan: { title: string; role: string; prompt: string; depends_on: number[] }[] };

export function TaskOrchestrationPanel({ projectId, onCreated }: { projectId: number; onCreated: () => void }) {
  const [graph, setGraph] = useState<Graph>({ project_id: projectId, nodes: [] });
  const [review, setReview] = useState<ReviewBundle | null>(null);
  const [draft, setDraft] = useState<Draft>({ title: "", prompt: "", role: "worker", parent: "", dependencies: "" });
  const [leadDraft, setLeadDraft] = useState<LeadDraft>({ title: "", objective: "", maxTasks: 6 });
  const [lastPlan, setLastPlan] = useState<LeadResponse["plan"]>([]);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 3000);
    return () => window.clearInterval(timer);
  }, [projectId]);

  async function load() {
    try { setGraph(await request<Graph>(`/projects/${projectId}/orchestration`)); }
    catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  const roots = useMemo(() => graph.nodes.filter((node) => !node.parent_task_id), [graph.nodes]);
  const byId = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes]);

  async function createLead(event: FormEvent) {
    event.preventDefault();
    if (!leadDraft.objective.trim()) return;
    setBusy(true); setNotice(""); setLastPlan([]);
    try {
      const created = await request<LeadResponse>(`/projects/${projectId}/orchestration/lead`, {
        method: "POST",
        body: JSON.stringify({ objective: leadDraft.objective.trim(), title: leadDraft.title.trim(), max_tasks: leadDraft.maxTasks }),
      });
      setLastPlan(created.plan || []);
      setLeadDraft({ title: "", objective: "", maxTasks: 6 });
      setNotice(`Lead task created with ${created.plan.length} specialist tasks and a final reviewer`);
      await load(); onCreated();
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function createTask(event: FormEvent) {
    event.preventDefault();
    if (!draft.prompt.trim()) return;
    const dependencies = draft.dependencies.split(",").map((item) => Number(item.trim())).filter((item) => Number.isInteger(item) && item > 0);
    setBusy(true); setNotice("");
    try {
      await request(`/projects/${projectId}/orchestration/tasks`, {
        method: "POST",
        body: JSON.stringify({ title: draft.title.trim(), prompt: draft.prompt.trim(), agent_role: draft.role.trim() || "worker", parent_task_id: draft.parent ? Number(draft.parent) : null, depends_on: dependencies }),
      });
      setDraft({ title: "", prompt: "", role: "worker", parent: "", dependencies: "" });
      setNotice("Orchestrated task queued"); await load(); onCreated();
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function loadReview(taskId: number) {
    setBusy(true); setNotice("");
    try { setReview(await request<ReviewBundle>(`/tasks/${taskId}/review-bundle`)); }
    catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  function renderNode(node: Node, depth = 0): React.ReactNode {
    return <div key={node.id} className="orchestration-node" style={{ marginLeft: depth * 16 }}>
      <div className="orchestration-node-head"><div><strong>#{node.id} {node.title}</strong><small>{node.agent_role} · {node.status}{node.worktree_branch ? ` · ${node.worktree_branch}` : ""}{node.pr_number ? ` · PR #${node.pr_number} ${node.pr_state || ""}` : ""}</small></div><div><span>{node.children.length} child{node.children.length === 1 ? "" : "ren"}</span>{depth === 0 && <button disabled={busy} onClick={() => loadReview(node.id)}>Review bundle</button>}</div></div>
      {node.depends_on.length > 0 && <small className="orchestration-deps">Depends on {node.depends_on.map((id) => `#${id}`).join(", ")}</small>}
      {depth === 0 && node.agent_role === "lead" && node.status === "completed" && node.result ? <details className="lead-result"><summary>Lead consolidation</summary><pre>{node.result}</pre></details> : null}
      {node.error ? <small className="orchestration-deps">{node.error}</small> : null}
      {node.children.map((id) => byId.get(id)).filter(Boolean).map((child) => renderNode(child as Node, depth + 1))}
    </div>;
  }

  return <section className="orchestration-panel">
    <div className="orchestration-head"><div><p className="eyebrow">Multi-agent orchestration</p><h3>Task graph</h3><p>Give a lead agent one objective and Ollama can decompose it into specialists, dependencies and a final review hand-off.</p></div><span>{graph.nodes.length} tasks</span></div>

    <form onSubmit={createLead} className="autonomous-lead-form">
      <div><p className="eyebrow">Autonomous lead</p><h4>Coordinate a larger implementation</h4><p>Ollama creates a dependency-aware specialist plan. The lead does not consume a worker slot while specialists execute.</p></div>
      <label>Title<input value={leadDraft.title} onChange={(event) => setLeadDraft((current) => ({ ...current, title: event.target.value }))} placeholder="Optional orchestration title" /></label>
      <label>Maximum specialists<select value={leadDraft.maxTasks} onChange={(event) => setLeadDraft((current) => ({ ...current, maxTasks: Number(event.target.value) }))}>{[2,3,4,5,6,7,8,9,10].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <label className="orchestration-prompt">Objective<textarea value={leadDraft.objective} onChange={(event) => setLeadDraft((current) => ({ ...current, objective: event.target.value }))} placeholder="Build the feature end-to-end. Split frontend, backend and testing work where appropriate…" /></label>
      <button className="primary" disabled={busy || !leadDraft.objective.trim()}>{busy ? "Planning…" : "Start autonomous lead"}</button>
    </form>

    {lastPlan.length > 0 && <details className="activity-card lead-plan" open><summary><span>✦</span><div><strong>Generated specialist plan</strong><small>{lastPlan.length} tasks</small></div><b>⌄</b></summary>{lastPlan.map((item, index) => <article key={`${index}-${item.title}`}><strong>{index + 1}. {item.title}</strong><small>{item.role}{item.depends_on.length ? ` · after ${item.depends_on.map((dep) => dep + 1).join(", ")}` : " · can start immediately"}</small><p>{item.prompt}</p></article>)}</details>}

    <div className="orchestration-grid">
      <div className="orchestration-tree">{roots.length ? roots.map((node) => renderNode(node)) : <p>No orchestration graph yet.</p>}</div>
      <form onSubmit={createTask} className="orchestration-form">
        <p className="eyebrow">Manual specialist</p>
        <label>Title<input value={draft.title} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} placeholder="Frontend specialist" /></label>
        <label>Role<select value={draft.role} onChange={(event) => setDraft((current) => ({ ...current, role: event.target.value }))}><option value="worker">Worker</option><option value="frontend">Frontend</option><option value="backend">Backend</option><option value="researcher">Researcher</option><option value="reviewer">Reviewer</option><option value="tester">Tester</option></select></label>
        <label>Parent<select value={draft.parent} onChange={(event) => setDraft((current) => ({ ...current, parent: event.target.value }))}><option value="">No parent</option>{graph.nodes.map((node) => <option key={node.id} value={node.id}>#{node.id} {node.title}</option>)}</select></label>
        <label>Depends on<input value={draft.dependencies} onChange={(event) => setDraft((current) => ({ ...current, dependencies: event.target.value }))} placeholder="12, 13" /></label>
        <label className="orchestration-prompt">Task prompt<textarea value={draft.prompt} onChange={(event) => setDraft((current) => ({ ...current, prompt: event.target.value }))} placeholder="Describe the specialist task and expected hand-off…" /></label>
        <button className="primary" disabled={busy || !draft.prompt.trim()}>{busy ? "Working…" : "Queue specialist task"}</button>
      </form>
    </div>
    {review && <details className="activity-card orchestration-review" open><summary><span>◎</span><div><strong>Lead task #{review.task_id} review bundle</strong><small>{review.items.length} branches/tasks against {review.base}</small></div><b>⌄</b></summary>{review.items.map((item) => <article key={item.id}><header><strong>#{item.id} {item.title}</strong><small>{item.agent_role} · {item.status}{item.pull_request_number ? ` · PR #${item.pull_request_number} ${item.pull_request_state}` : ""}</small></header>{item.result && <p>{item.result}</p>}{item.error && <p>{item.error}</p>}{item.branch_error && <p>{item.branch_error}</p>}{item.branch ? <pre>{item.branch.working_diff || item.branch.branch_diff || "No diff"}</pre> : !item.branch_error && <p>No worktree available.</p>}</article>)}</details>}
    {notice && <div className="queue-notice">{notice}</div>}
  </section>;
}
