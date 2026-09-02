"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { request } from "../lib/api";

type Node = {
  id: number; title: string; status: string; agent_role: string; parent_task_id?: number | null;
  depends_on: number[]; children: number[]; worktree_branch: string; pr_number: number; pr_state: string;
};

type Graph = { project_id: number; nodes: Node[] };
type ReviewItem = { id: number; title: string; agent_role: string; status: string; depends_on: number[]; worktree_branch: string; pull_request_number: number; pull_request_state: string; branch?: { branch_diff: string; working_diff: string; changes: string[] } | null; branch_error?: string };
type ReviewBundle = { task_id: number; base: string; items: ReviewItem[] };
type Draft = { title: string; prompt: string; role: string; parent: string; dependencies: string };

export function TaskOrchestrationPanel({ projectId, onCreated }: { projectId: number; onCreated: () => void }) {
  const [graph, setGraph] = useState<Graph>({ project_id: projectId, nodes: [] });
  const [review, setReview] = useState<ReviewBundle | null>(null);
  const [draft, setDraft] = useState<Draft>({ title: "", prompt: "", role: "worker", parent: "", dependencies: "" });
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { load(); }, [projectId]);

  async function load() {
    try { setGraph(await request<Graph>(`/projects/${projectId}/orchestration`)); }
    catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  const roots = useMemo(() => graph.nodes.filter((node) => !node.parent_task_id), [graph.nodes]);
  const byId = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes]);

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
      {node.children.map((id) => byId.get(id)).filter(Boolean).map((child) => renderNode(child as Node, depth + 1))}
    </div>;
  }

  return <section className="orchestration-panel">
    <div className="orchestration-head"><div><p className="eyebrow">Multi-agent orchestration</p><h3>Task graph</h3><p>Lead and specialist agents can be linked by parent/child relationships and explicit prerequisites.</p></div><span>{graph.nodes.length} tasks</span></div>
    <div className="orchestration-grid">
      <div className="orchestration-tree">{roots.length ? roots.map((node) => renderNode(node)) : <p>No orchestration graph yet.</p>}</div>
      <form onSubmit={createTask} className="orchestration-form">
        <label>Title<input value={draft.title} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} placeholder="Frontend specialist" /></label>
        <label>Role<select value={draft.role} onChange={(event) => setDraft((current) => ({ ...current, role: event.target.value }))}><option value="lead">Lead</option><option value="worker">Worker</option><option value="frontend">Frontend</option><option value="backend">Backend</option><option value="reviewer">Reviewer</option><option value="tester">Tester</option></select></label>
        <label>Parent<select value={draft.parent} onChange={(event) => setDraft((current) => ({ ...current, parent: event.target.value }))}><option value="">No parent</option>{graph.nodes.map((node) => <option key={node.id} value={node.id}>#{node.id} {node.title}</option>)}</select></label>
        <label>Depends on<input value={draft.dependencies} onChange={(event) => setDraft((current) => ({ ...current, dependencies: event.target.value }))} placeholder="12, 13" /></label>
        <label className="orchestration-prompt">Task prompt<textarea value={draft.prompt} onChange={(event) => setDraft((current) => ({ ...current, prompt: event.target.value }))} placeholder="Describe the specialist task and expected hand-off…" /></label>
        <button className="primary" disabled={busy || !draft.prompt.trim()}>{busy ? "Working…" : "Queue orchestrated task"}</button>
      </form>
    </div>
    {review && <details className="activity-card orchestration-review" open><summary><span>◎</span><div><strong>Lead task #{review.task_id} review bundle</strong><small>{review.items.length} branches/tasks against {review.base}</small></div><b>⌄</b></summary>{review.items.map((item) => <article key={item.id}><header><strong>#{item.id} {item.title}</strong><small>{item.agent_role} · {item.status}{item.pull_request_number ? ` · PR #${item.pull_request_number} ${item.pull_request_state}` : ""}</small></header>{item.branch_error && <p>{item.branch_error}</p>}{item.branch ? <pre>{item.branch.working_diff || item.branch.branch_diff || "No diff"}</pre> : !item.branch_error && <p>No worktree available.</p>}</article>)}</details>}
    {notice && <div className="queue-notice">{notice}</div>}
  </section>;
}
