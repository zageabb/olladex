"use client";

import { FormEvent, useEffect, useState } from "react";
import { request } from "../lib/api";

type GitHubStatus = { available: boolean; authenticated: boolean; repository: string; error: string };
type Issue = { number: number; title: string; body: string; url: string; labels: { name: string }[]; updatedAt: string };
type Operation = { id: number; action: string; repository: string; title: string; head: string; base: string; command: string; status: string; output: string };
type PullRequest = { number: number; title: string; url: string; state: string; isDraft: boolean; headRefName: string; baseRefName: string; reviewDecision?: string; updatedAt?: string };
type PullRequestDetail = PullRequest & { body?: string; mergeable?: string; reviews?: unknown[]; comments?: unknown[]; files?: unknown[]; commits?: unknown[]; statusCheckRollup?: unknown[] };

export function GitHubPanel({ projectId, branch, onTaskQueued }: { projectId: number; branch: string; onTaskQueued: () => void }) {
  const [status, setStatus] = useState<GitHubStatus | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [pullRequests, setPullRequests] = useState<PullRequest[]>([]);
  const [selectedPr, setSelectedPr] = useState<PullRequestDetail | null>(null);
  const [prDiff, setPrDiff] = useState("");
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
      if (current.authenticated) {
        const [issueData, prData] = await Promise.all([
          request<Issue[]>(`/projects/${projectId}/github/issues`),
          request<PullRequest[]>(`/projects/${projectId}/github/pull-requests/review`),
        ]);
        setIssues(issueData); setPullRequests(prData);
      }
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function importIssue(issue: Issue) {
    setBusy(true);
    try { await request(`/projects/${projectId}/github/issues/${issue.number}/task`, { method: "POST" }); setNotice(`Issue #${issue.number} queued`); onTaskQueued(); }
    catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function openPullRequest(pr: PullRequest) {
    setBusy(true); setPrDiff("");
    try {
      const [detail, diff] = await Promise.all([
        request<PullRequestDetail>(`/projects/${projectId}/github/pull-requests/${pr.number}`),
        request<{ diff: string }>(`/projects/${projectId}/github/pull-requests/${pr.number}/diff`),
      ]);
      setSelectedPr(detail); setPrDiff(diff.diff);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function commentOnPullRequest(pr: PullRequestDetail) {
    const comment = window.prompt(`Comment on PR #${pr.number}`);
    if (!comment?.trim()) return;
    setBusy(true);
    try {
      await request(`/projects/${projectId}/github/pull-requests/${pr.number}/comments`, { method: "POST", body: JSON.stringify({ body: comment.trim() }) });
      setNotice(`Comment added to PR #${pr.number}`); await openPullRequest(pr);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); setBusy(false); }
  }

  async function reviewPullRequest(pr: PullRequestDetail, event: "approve" | "request-changes") {
    const reviewBody = event === "approve" ? (window.prompt("Approval note (optional)") ?? "") : window.prompt("What needs to change?");
    if (event === "request-changes" && !reviewBody?.trim()) return;
    setBusy(true);
    try {
      await request(`/projects/${projectId}/github/pull-requests/${pr.number}/reviews`, { method: "POST", body: JSON.stringify({ event, body: reviewBody || "" }) });
      setNotice(event === "approve" ? `Approved PR #${pr.number}` : `Changes requested on PR #${pr.number}`);
      await load(); await openPullRequest(pr);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); setBusy(false); }
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
      if (decision === "approve") await load();
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  return <section className="github-panel"><header><div><p className="eyebrow">GitHub workflow</p><h3>{status?.repository || "No GitHub remote"}</h3></div><span className={status?.authenticated ? "connected" : ""}>{status?.authenticated ? "gh connected" : "gh unavailable"}</span></header>
    {!status?.authenticated ? <p className="github-help">{status?.error || "Checking GitHub CLI…"}</p> : <>
      <details className="github-issues"><summary>Open issues <span>{issues.length}</span></summary>{issues.slice(0, 12).map((issue) => <article key={issue.number}><div><strong>#{issue.number} {issue.title}</strong><small>{issue.labels?.map((label) => label.name).join(" · ") || "No labels"}</small></div><button disabled={busy} onClick={() => importIssue(issue)}>Queue implementation</button></article>)}{!issues.length && <p>No open issues found.</p>}</details>
      <details className="github-issues" open><summary>Pull requests <span>{pullRequests.length}</span></summary>{pullRequests.slice(0, 20).map((pr) => <article key={pr.number}><div><strong>#{pr.number} {pr.title}</strong><small>{pr.headRefName} → {pr.baseRefName}{pr.reviewDecision ? ` · ${pr.reviewDecision}` : ""}</small></div><button disabled={busy} onClick={() => openPullRequest(pr)}>Review</button></article>)}{!pullRequests.length && <p>No open pull requests found.</p>}</details>
      {selectedPr && <details className="github-pr" open><summary>Review PR #{selectedPr.number} · {selectedPr.title}</summary><div className="git-remote-controls"><div><span>{selectedPr.headRefName} → {selectedPr.baseRefName} · {selectedPr.mergeable || "mergeability unknown"}</span></div><div><button disabled={busy} onClick={() => commentOnPullRequest(selectedPr)}>Comment</button><button disabled={busy} onClick={() => reviewPullRequest(selectedPr, "request-changes")}>Request changes</button><button className="primary" disabled={busy} onClick={() => reviewPullRequest(selectedPr, "approve")}>Approve</button></div></div>{selectedPr.body && <p>{selectedPr.body}</p>}<pre>{prDiff || "No diff returned."}</pre></details>}
      <details className="github-pr"><summary>Prepare pull request</summary><form onSubmit={propose}><div><label>Head<input value={branch} disabled /></label><label>Base<input value={base} onChange={(event) => setBase(event.target.value)} /></label></div><label>Title<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Describe this change" /></label><label>Description<textarea value={body} onChange={(event) => setBody(event.target.value)} placeholder="Summary, testing and review notes…" /></label><button disabled={busy || !title.trim()}>Prepare exact command</button></form></details>
    </>}
    {operations.filter((operation) => operation.status === "pending").map((operation) => <article className="github-approval" key={operation.id}><div><strong>{operation.title}</strong><code>{operation.command}</code></div><div><button disabled={busy} onClick={() => decide(operation, "reject")}>Reject</button><button className="primary" disabled={busy} onClick={() => decide(operation, "approve")}>Approve & create PR</button></div></article>)}
    {notice && <div className="git-notice">{notice}</div>}
  </section>;
}
