"use client";

import { FormEvent, useEffect, useState } from "react";
import { GitSummary } from "./GitControls";
import { request } from "../lib/api";

type Issue = { number: number; title: string; body: string; url: string; labels: string[] };
type Pull = { number: number; title: string; url: string; head: string; base: string; draft: boolean };
type Overview = { repository: string; authenticated: boolean; issues: Issue[]; pull_requests: Pull[] };
type Operation = { id: number; title: string; repository: string; head: string; base: string; draft: number; status: "pending" | "completed" | "failed" | "rejected"; response: string };

export function GitHubPanel({ projectId, git, onJobCreated }: { projectId: number; git: GitSummary; onJobCreated: (sessionId: number) => void }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [operations, setOperations] = useState<Operation[]>([]);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [base, setBase] = useState("main");
  const [draft, setDraft] = useState(true);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { refresh(); }, [projectId]);

  async function refresh() {
    try {
      const [details, pending] = await Promise.all([request<Overview>(`/projects/${projectId}/github`), request<Operation[]>(`/projects/${projectId}/github/operations`)]);
      setOverview(details); setOperations(pending); setNotice("");
    } catch (error) { setOverview(null); setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function importIssue(issue: Issue) {
    setBusy(true);
    try {
      const result = await request<{ session_id: number }>(`/projects/${projectId}/github/issues/${issue.number}/jobs`, { method: "POST" });
      setNotice(`Issue #${issue.number} queued as a background job`); onJobCreated(result.session_id);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function propose(event: FormEvent) {
    event.preventDefault(); if (!title.trim()) return;
    setBusy(true);
    try {
      await request(`/projects/${projectId}/github/pull-requests`, { method: "POST", body: JSON.stringify({ title: title.trim(), body, head: git.branch, base, draft }) });
      setTitle(""); setBody(""); await refresh(); setNotice("Pull request prepared — review it below before creation");
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function decide(operation: Operation, decision: "approve" | "reject") {
    setBusy(true);
    try {
      await request(`/projects/${projectId}/github/operations/${operation.id}/${decision}`, { method: "POST" });
      await refresh(); setNotice(decision === "approve" ? "Pull request created" : "Pull request proposal rejected");
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); await refresh(); }
    finally { setBusy(false); }
  }

  return <section className="github-panel">
    <header><div><p className="eyebrow">Issue-to-agent workflow</p><h3>GitHub {overview?.repository && <span>{overview.repository} · {overview.authenticated ? "token ready" : "public read-only"}</span>}</h3></div><button onClick={refresh} disabled={busy}>Refresh</button></header>
    {notice && <div className="github-notice">{notice}</div>}
    {overview && <div className="github-grid">
      <div><h4>Open issues</h4>{overview.issues.length ? overview.issues.map((issue) => <article key={issue.number}><div><a href={issue.url} target="_blank" rel="noreferrer">#{issue.number} {issue.title}</a><small>{issue.labels.join(" · ") || "No labels"}</small></div><button disabled={busy} onClick={() => importIssue(issue)}>Queue agent</button></article>) : <p>No open issues</p>}</div>
      <div><h4>Open pull requests</h4>{overview.pull_requests.length ? overview.pull_requests.map((pull) => <article key={pull.number}><div><a href={pull.url} target="_blank" rel="noreferrer">#{pull.number} {pull.title}</a><small>{pull.head} → {pull.base}{pull.draft ? " · draft" : ""}</small></div></article>) : <p>No open pull requests</p>}</div>
    </div>}
    {overview && <form className="github-pr-form" onSubmit={propose}><h4>Prepare pull request</h4><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={`Title for ${git.branch}`} /><textarea value={body} onChange={(event) => setBody(event.target.value)} placeholder="Summary, checks and related issue…" /><div><label>Base<select value={base} onChange={(event) => setBase(event.target.value)}>{git.branches.map((branch) => <option key={branch}>{branch}</option>)}</select></label><label className="draft-check"><input type="checkbox" checked={draft} onChange={(event) => setDraft(event.target.checked)} />Draft</label><button disabled={busy || !title.trim() || base === git.branch}>Prepare for review</button></div>{base === git.branch && <small>Switch to a feature branch or choose a different base branch.</small>}</form>}
    {operations.some((item) => item.status === "pending") && <div className="github-approvals"><p className="eyebrow">Awaiting explicit approval</p>{operations.filter((item) => item.status === "pending").map((operation) => <article key={operation.id}><div><strong>{operation.title}</strong><span>{operation.repository} · {operation.head} → {operation.base}{operation.draft ? " · draft" : ""}</span></div><div><button onClick={() => decide(operation, "reject")} disabled={busy}>Reject</button><button className="primary" onClick={() => decide(operation, "approve")} disabled={busy}>Approve & create</button></div></article>)}</div>}
  </section>;
}
