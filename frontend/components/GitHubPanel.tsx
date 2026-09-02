"use client";

import { FormEvent, useEffect, useState } from "react";
import { request } from "../lib/api";

type GitHubStatus = { available: boolean; authenticated: boolean; repository: string; error: string };
type Issue = { number: number; title: string; body: string; url: string; labels: { name: string }[]; updatedAt: string };
type Operation = { id: number; action: string; repository: string; title: string; head: string; base: string; command: string; status: string; output: string };

export function GitHubPanel({ projectId, branch, onTaskQueued }: { projectId: number; branch: string; onTaskQueued: () => void }) {
  const [status, setStatus] = useState<GitHubStatus | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [operations, setOperations] = useState<Operation[]>([]);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [base, setBase] = useState("main");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { load(); }, [projectId]);

  async function load() {
    try {
      const current = await request<GitHubStatus>(`/projects/${projectId}/github`); setStatus(current);
      const ops = await request<Operation[]>(`/projects/${projectId}/github/operations`); setOperations(ops);
      if (current.authenticated) setIssues(await request<Issue[]>(`/projects/${projectId}/github/issues`));
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function importIssue(issue: Issue) {
    setBusy(true);
    try { await request(`/projects/${projectId}/github/issues/${issue.number}/task`, { method: "POST" }); setNotice(`Issue #${issue.number} queued`); onTaskQueued(); }
    catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function propose(event: FormEvent) {
    event.preventDefault(); if (!title.trim()) return;
    setBusy(true);
    try {
      await request(`/projects/${projectId}/github/pull-requests`, { method: "POST", body: JSON.stringify({ title: title.trim(), body, base }) });
      setOperations(await request<Operation[]>(`/projects/${projectId}/github/operations`)); setNotice("Pull request prepared — approve the exact command below");
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function decide(operation: Operation, decision: "approve" | "reject") {
    setBusy(true);
    try {
      await request(`/projects/${projectId}/github/operations/${operation.id}/${decision}`, { method: "POST" });
      setOperations(await request<Operation[]>(`/projects/${projectId}/github/operations`)); setNotice(decision === "approve" ? "Pull request created" : "Pull request proposal rejected");
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  return <section className="github-panel"><header><div><p className="eyebrow">GitHub workflow</p><h3>{status?.repository || "No GitHub remote"}</h3></div><span className={status?.authenticated ? "connected" : ""}>{status?.authenticated ? "gh connected" : "gh unavailable"}</span></header>
    {!status?.authenticated ? <p className="github-help">{status?.error || "Checking GitHub CLI…"}</p> : <>
      <details className="github-issues" open><summary>Open issues <span>{issues.length}</span></summary>{issues.slice(0, 12).map((issue) => <article key={issue.number}><div><strong>#{issue.number} {issue.title}</strong><small>{issue.labels?.map((label) => label.name).join(" · ") || "No labels"}</small></div><button disabled={busy} onClick={() => importIssue(issue)}>Queue implementation</button></article>)}{!issues.length && <p>No open issues found.</p>}</details>
      <details className="github-pr"><summary>Prepare pull request</summary><form onSubmit={propose}><div><label>Head<input value={branch} disabled /></label><label>Base<input value={base} onChange={(event) => setBase(event.target.value)} /></label></div><label>Title<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Describe this change" /></label><label>Description<textarea value={body} onChange={(event) => setBody(event.target.value)} placeholder="Summary, testing and review notes…" /></label><button disabled={busy || !title.trim()}>Prepare exact command</button></form></details>
    </>}
    {operations.filter((operation) => operation.status === "pending").map((operation) => <article className="github-approval" key={operation.id}><div><strong>{operation.title}</strong><code>{operation.command}</code></div><div><button disabled={busy} onClick={() => decide(operation, "reject")}>Reject</button><button className="primary" disabled={busy} onClick={() => decide(operation, "approve")}>Approve & create PR</button></div></article>)}
    {notice && <div className="git-notice">{notice}</div>}
  </section>;
}
