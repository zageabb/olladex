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
type IntegrationState = { lead_task_id: number; path: string; branch: string; base: string; diff?: string; changes?: string[]; check_command?: string; check_status?: string; check_output?: string; pull_request_number?: number; pull_request_url?: string; pull_request_state?: string };
type IntegrationPreflight = { lead_task_id: number; task_ids: number[]; base: string; branches: string[]; files_by_branch: Record<string, string[]>; overlaps: { path: string; branches: string[] }[] };

export function TaskOrchestrationPanel({ projectId, onCreated }: { projectId: number; onCreated: () => void }) {
  const [graph, setGraph] = useState<Graph>({ project_id: projectId, nodes: [] });
  const [review, setReview] = useState<ReviewBundle | null>(null);
  const [draft, setDraft] = useState<Draft>({ title: "", prompt: "", role: "worker", parent: "", dependencies: "" });
  const [leadDraft, setLeadDraft] = useState<LeadDraft>({ title: "", objective: "", maxTasks: 6 });
  const [lastPlan, setLastPlan] = useState<LeadResponse["plan"]>([]);
  const [selectedLead, setSelectedLead] = useState<number | null>(null);
  const [selectedTasks, setSelectedTasks] = useState<number[]>([]);
  const [integration, setIntegration] = useState<IntegrationState | null>(null);
  const [preflight, setPreflight] = useState<IntegrationPreflight | null>(null);
  const [checkCommand, setCheckCommand] = useState("pytest -q && cd frontend && npm run build");
  const [prTitle, setPrTitle] = useState("");
  const [prBody, setPrBody] = useState("Integrated and validated by Olladex multi-agent orchestration.");
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
  const integrationChildren = useMemo(() => selectedLead ? graph.nodes.filter((node) => node.parent_task_id === selectedLead && node.agent_role !== "reviewer") : [], [graph.nodes, selectedLead]);

  async function createLead(event: FormEvent) {
    event.preventDefault(); if (!leadDraft.objective.trim()) return;
    setBusy(true); setNotice(""); setLastPlan([]);
    try {
      const created = await request<LeadResponse>(`/projects/${projectId}/orchestration/lead`, { method: "POST", body: JSON.stringify({ objective: leadDraft.objective.trim(), title: leadDraft.title.trim(), max_tasks: leadDraft.maxTasks }) });
      setLastPlan(created.plan || []); setLeadDraft({ title: "", objective: "", maxTasks: 6 });
      setNotice(`Lead task created with ${created.plan.length} specialist tasks and a final reviewer`); await load(); onCreated();
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function createTask(event: FormEvent) {
    event.preventDefault(); if (!draft.prompt.trim()) return;
    const dependencies = draft.dependencies.split(",").map((item) => Number(item.trim())).filter((item) => Number.isInteger(item) && item > 0);
    setBusy(true); setNotice("");
    try {
      await request(`/projects/${projectId}/orchestration/tasks`, { method: "POST", body: JSON.stringify({ title: draft.title.trim(), prompt: draft.prompt.trim(), agent_role: draft.role.trim() || "worker", parent_task_id: draft.parent ? Number(draft.parent) : null, depends_on: dependencies }) });
      setDraft({ title: "", prompt: "", role: "worker", parent: "", dependencies: "" }); setNotice("Orchestrated task queued"); await load(); onCreated();
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function loadReview(taskId: number) {
    setBusy(true); setNotice("");
    try { setReview(await request<ReviewBundle>(`/tasks/${taskId}/review-bundle`)); }
    catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function openIntegration(lead: Node) {
    setSelectedLead(lead.id); setPreflight(null); setSelectedTasks([]); setPrTitle(`Integrate: ${lead.title}`);
    try { setIntegration(await request<IntegrationState>(`/tasks/${lead.id}/integration`)); }
    catch { setIntegration(null); }
  }

  function toggleIntegrationTask(id: number) {
    setSelectedTasks((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  async function preflightIntegration() {
    if (!selectedLead || !selectedTasks.length) return;
    setBusy(true); setNotice("");
    try {
      const result = await request<IntegrationPreflight>(`/tasks/${selectedLead}/integration/preflight`, { method: "POST", body: JSON.stringify({ task_ids: selectedTasks, base: "main" }) });
      setPreflight(result); setNotice(result.overlaps.length ? `${result.overlaps.length} overlapping file(s) need review` : "No file overlaps detected");
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function createIntegration() {
    if (!selectedLead || !selectedTasks.length) return;
    setBusy(true); setNotice("");
    try {
      const result = await request<IntegrationState>(`/tasks/${selectedLead}/integration`, { method: "POST", body: JSON.stringify({ task_ids: selectedTasks, base: "main" }) });
      setIntegration(result); setNotice(`Created ${result.branch}`);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function runChecks() {
    if (!selectedLead || !checkCommand.trim()) return;
    setBusy(true); setNotice("");
    try {
      const result = await request<{ passed: boolean; output: string; command: string }>(`/tasks/${selectedLead}/integration/checks`, { method: "POST", body: JSON.stringify({ command: checkCommand.trim() }) });
      setIntegration((current) => current ? { ...current, check_command: result.command, check_status: result.passed ? "passed" : "failed", check_output: result.output } : current);
      setNotice(result.passed ? "Combined checks passed" : "Combined checks failed");
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function pushIntegration() {
    if (!selectedLead) return;
    setBusy(true); setNotice("");
    try { const result = await request<{ branch: string }>(`/tasks/${selectedLead}/integration/push`, { method: "POST", body: JSON.stringify({ remote: "origin" }) }); setNotice(`Pushed ${result.branch}`); }
    catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function createIntegrationPr() {
    if (!selectedLead || !prTitle.trim()) return;
    setBusy(true); setNotice("");
    try {
      const result = await request<{ url: string; pull_request_number: number }>(`/tasks/${selectedLead}/integration/pull-request`, { method: "POST", body: JSON.stringify({ title: prTitle.trim(), body: prBody, base: "main" }) });
      setIntegration((current) => current ? { ...current, pull_request_number: result.pull_request_number, pull_request_url: result.url, pull_request_state: "OPEN" } : current);
      setNotice(`Final integration PR #${result.pull_request_number} created`);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  function renderNode(node: Node, depth = 0): React.ReactNode {
    return <div key={node.id} className="orchestration-node" style={{ marginLeft: depth * 16 }}>
      <div className="orchestration-node-head"><div><strong>#{node.id} {node.title}</strong><small>{node.agent_role} · {node.status}{node.worktree_branch ? ` · ${node.worktree_branch}` : ""}{node.pr_number ? ` · PR #${node.pr_number} ${node.pr_state || ""}` : ""}</small></div><div><span>{node.children.length} child{node.children.length === 1 ? "" : "ren"}</span>{depth === 0 && <button disabled={busy} onClick={() => loadReview(node.id)}>Review bundle</button>}{depth === 0 && node.agent_role === "lead" && <button disabled={busy} onClick={() => openIntegration(node)}>Integrate</button>}</div></div>
      {node.depends_on.length > 0 && <small className="orchestration-deps">Depends on {node.depends_on.map((id) => `#${id}`).join(", ")}</small>}
      {depth === 0 && node.agent_role === "lead" && node.status === "completed" && node.result ? <details className="lead-result"><summary>Lead consolidation</summary><pre>{node.result}</pre></details> : null}
      {node.error ? <small className="orchestration-deps">{node.error}</small> : null}
      {node.children.map((id) => byId.get(id)).filter(Boolean).map((child) => renderNode(child as Node, depth + 1))}
    </div>;
  }

  return <section className="orchestration-panel">
    <div className="orchestration-head"><div><p className="eyebrow">Multi-agent orchestration</p><h3>Task graph</h3><p>Give a lead agent one objective and Ollama can decompose it into specialists, dependencies, final review and an integration branch.</p></div><span>{graph.nodes.length} tasks</span></div>
    <form onSubmit={createLead} className="autonomous-lead-form"><div><p className="eyebrow">Autonomous lead</p><h4>Coordinate a larger implementation</h4><p>Ollama creates a dependency-aware specialist plan. The lead does not consume a worker slot while specialists execute.</p></div><label>Title<input value={leadDraft.title} onChange={(event) => setLeadDraft((current) => ({ ...current, title: event.target.value }))} placeholder="Optional orchestration title" /></label><label>Maximum specialists<select value={leadDraft.maxTasks} onChange={(event) => setLeadDraft((current) => ({ ...current, maxTasks: Number(event.target.value) }))}>{[2,3,4,5,6,7,8,9,10].map((value) => <option key={value} value={value}>{value}</option>)}</select></label><label className="orchestration-prompt">Objective<textarea value={leadDraft.objective} onChange={(event) => setLeadDraft((current) => ({ ...current, objective: event.target.value }))} placeholder="Build the feature end-to-end…" /></label><button className="primary" disabled={busy || !leadDraft.objective.trim()}>{busy ? "Planning…" : "Start autonomous lead"}</button></form>
    {lastPlan.length > 0 && <details className="activity-card lead-plan" open><summary><span>✦</span><div><strong>Generated specialist plan</strong><small>{lastPlan.length} tasks</small></div><b>⌄</b></summary>{lastPlan.map((item, index) => <article key={`${index}-${item.title}`}><strong>{index + 1}. {item.title}</strong><small>{item.role}{item.depends_on.length ? ` · after ${item.depends_on.map((dep) => dep + 1).join(", ")}` : " · can start immediately"}</small><p>{item.prompt}</p></article>)}</details>}
    <div className="orchestration-grid"><div className="orchestration-tree">{roots.length ? roots.map((node) => renderNode(node)) : <p>No orchestration graph yet.</p>}</div><form onSubmit={createTask} className="orchestration-form"><p className="eyebrow">Manual specialist</p><label>Title<input value={draft.title} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} /></label><label>Role<select value={draft.role} onChange={(event) => setDraft((current) => ({ ...current, role: event.target.value }))}><option value="worker">Worker</option><option value="frontend">Frontend</option><option value="backend">Backend</option><option value="researcher">Researcher</option><option value="reviewer">Reviewer</option><option value="tester">Tester</option></select></label><label>Parent<select value={draft.parent} onChange={(event) => setDraft((current) => ({ ...current, parent: event.target.value }))}><option value="">No parent</option>{graph.nodes.map((node) => <option key={node.id} value={node.id}>#{node.id} {node.title}</option>)}</select></label><label>Depends on<input value={draft.dependencies} onChange={(event) => setDraft((current) => ({ ...current, dependencies: event.target.value }))} placeholder="12, 13" /></label><label className="orchestration-prompt">Task prompt<textarea value={draft.prompt} onChange={(event) => setDraft((current) => ({ ...current, prompt: event.target.value }))} /></label><button className="primary" disabled={busy || !draft.prompt.trim()}>{busy ? "Working…" : "Queue specialist task"}</button></form></div>
    {selectedLead && <details className="activity-card orchestration-review" open><summary><span>⇄</span><div><strong>Integration · lead #{selectedLead}</strong><small>Select committed specialist branches, combine, validate and promote once.</small></div><b>⌄</b></summary><div className="task-promotion-form"><div>{integrationChildren.map((node) => <label key={node.id}><input type="checkbox" checked={selectedTasks.includes(node.id)} disabled={node.status !== "completed" || !node.worktree_branch} onChange={() => toggleIntegrationTask(node.id)} /> #{node.id} {node.title} · {node.status}</label>)}</div><div className="activity-actions"><button disabled={busy || !selectedTasks.length} onClick={preflightIntegration}>Preflight overlaps</button><button className="primary" disabled={busy || !selectedTasks.length} onClick={createIntegration}>Build integration branch</button></div>{preflight && <div><strong>{preflight.overlaps.length ? `${preflight.overlaps.length} overlapping file(s)` : "No overlapping files"}</strong>{preflight.overlaps.map((item) => <p key={item.path}>{item.path} · {item.branches.join(", ")}</p>)}</div>}{integration?.branch && <><p><strong>{integration.branch}</strong></p>{integration.diff && <pre>{integration.diff}</pre>}<label>Combined check command<input value={checkCommand} onChange={(event) => setCheckCommand(event.target.value)} /></label><div className="activity-actions"><button disabled={busy || !checkCommand.trim()} onClick={runChecks}>Run combined checks</button><span>{integration.check_status || "not tested"}</span></div>{integration.check_output && <pre>{integration.check_output}</pre>}<label>Final PR title<input value={prTitle} onChange={(event) => setPrTitle(event.target.value)} /></label><label>Final PR description<textarea value={prBody} onChange={(event) => setPrBody(event.target.value)} /></label><div className="activity-actions"><button disabled={busy || integration.check_status !== "passed"} onClick={pushIntegration}>Push integration</button><button className="primary" disabled={busy || integration.check_status !== "passed" || !prTitle.trim()} onClick={createIntegrationPr}>Create final PR</button>{integration.pull_request_url && <button onClick={() => window.open(integration.pull_request_url, "_blank", "noopener,noreferrer")}>Open PR #{integration.pull_request_number}</button>}</div></>}</div></details>}
    {review && <details className="activity-card orchestration-review" open><summary><span>◎</span><div><strong>Lead task #{review.task_id} review bundle</strong><small>{review.items.length} branches/tasks against {review.base}</small></div><b>⌄</b></summary>{review.items.map((item) => <article key={item.id}><header><strong>#{item.id} {item.title}</strong><small>{item.agent_role} · {item.status}</small></header>{item.result && <p>{item.result}</p>}{item.error && <p>{item.error}</p>}{item.branch ? <pre>{item.branch.working_diff || item.branch.branch_diff || "No diff"}</pre> : <p>No worktree available.</p>}</article>)}</details>}
    {notice && <div className="queue-notice">{notice}</div>}
  </section>;
}
