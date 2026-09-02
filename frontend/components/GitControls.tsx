"use client";

import { FormEvent, useEffect, useState } from "react";
import { request } from "../lib/api";
import { GitHubPanel } from "./GitHubPanel";

export type GitSummary = { repository: boolean; branch: string; branches: string[]; changes: { status: string; path: string; staged: boolean; unstaged: boolean }[]; recent: { sha: string; subject: string; age: string }[]; remotes: { name: string; url: string }[]; upstream: string; ahead: number; behind: number };
type GitOperation = { id: number; action: "fetch" | "pull" | "push"; remote: string; remote_url: string; branch: string; command: string; status: "pending" | "completed" | "failed" | "rejected"; output: string; created_at: string };

export function GitControls({ projectId, git, onRefresh, onTaskQueued }: { projectId: number; git: GitSummary | null; onRefresh: () => Promise<void>; onTaskQueued: () => void }) {
  const [branchName, setBranchName] = useState("");
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [remote, setRemote] = useState("origin");
  const [operations, setOperations] = useState<GitOperation[]>([]);

  useEffect(() => { refreshOperations(); }, [projectId]);
  useEffect(() => { if (git?.remotes.length && !git.remotes.some((item) => item.name === remote)) setRemote(git.remotes[0].name); }, [git?.remotes, remote]);

  async function refreshOperations() {
    try { setOperations(await request<GitOperation[]>(`/projects/${projectId}/git/operations`)); }
    catch { setOperations([]); }
  }

  async function action(path: string, body?: object) {
    setBusy(true); setNotice("");
    try { await request(`/projects/${projectId}/git/${path}`, { method: "POST", body: JSON.stringify(body || {}) }); await onRefresh(); }
    catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function createBranch(event: FormEvent) {
    event.preventDefault(); if (!branchName.trim()) return;
    await action("branches", { name: branchName.trim(), checkout: true }); setBranchName("");
  }

  async function commit(event: FormEvent) {
    event.preventDefault(); if (!message.trim()) return;
    await action("commit", { message: message.trim() }); setMessage("");
  }

  async function proposeRemote(actionName: GitOperation["action"]) {
    setBusy(true); setNotice("");
    try {
      await request(`/projects/${projectId}/git/operations`, { method: "POST", body: JSON.stringify({ action: actionName, remote, branch: git?.branch }) });
      await refreshOperations(); setNotice(`${actionName} prepared — review the exact command below`);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }

  async function decide(operation: GitOperation, decision: "approve" | "reject") {
    setBusy(true); setNotice("");
    try {
      await request(`/projects/${projectId}/git/operations/${operation.id}/${decision}`, { method: "POST" });
      await Promise.all([refreshOperations(), onRefresh()]);
      setNotice(decision === "approve" ? `${operation.action} completed` : `${operation.action} rejected`);
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); await refreshOperations(); }
    finally { setBusy(false); }
  }

  if (!git?.repository) return <div className="git-controls empty-git"><strong>Git is not initialised</strong><span>Use the terminal to run `git init` if this project should be version controlled.</span></div>;

  return <><section className="git-controls">
    <div className="git-control-head"><div><p className="eyebrow">Controlled Git workflow</p><h3>{git.branch}</h3></div><label>Switch branch<select value={git.branch} onChange={(e) => action("checkout", { name: e.target.value })} disabled={busy}>{git.branches.map((branch) => <option key={branch}>{branch}</option>)}</select></label></div>
    <form className="branch-form" onSubmit={createBranch}><input value={branchName} onChange={(e) => setBranchName(e.target.value)} placeholder="feature/new-branch" /><button disabled={busy || !branchName.trim()}>Create & switch</button></form>
    <div className="git-file-list">{git.changes.length ? git.changes.map((file) => <article key={file.path}><span className="git-code">{file.status}</span><strong>{file.path}</strong><div>{file.staged && <button disabled={busy} onClick={() => action("unstage", { paths: [file.path] })}>Unstage</button>}{(!file.staged || file.unstaged) && <button disabled={busy} onClick={() => action("stage", { paths: [file.path] })}>Stage</button>}</div></article>) : <p>Working tree clean</p>}</div>
    <form className="commit-form" onSubmit={commit}><input value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Commit message" /><button className="primary" disabled={busy || !message.trim() || !git.changes.some((item) => item.staged)}>Commit staged</button></form>
    {git.remotes.length > 0 && <div className="git-remote-controls"><div><label>Remote<select value={remote} onChange={(event) => setRemote(event.target.value)}>{git.remotes.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select></label><span>{git.upstream || "No upstream"} · ↑ {git.ahead} ↓ {git.behind}</span></div><div><button disabled={busy} onClick={() => proposeRemote("fetch")}>Prepare fetch</button><button disabled={busy} onClick={() => proposeRemote("pull")}>Prepare pull</button><button disabled={busy} onClick={() => proposeRemote("push")}>Prepare push</button></div></div>}
    {operations.some((item) => item.status === "pending") && <div className="git-approvals"><p className="eyebrow">Awaiting explicit approval</p>{operations.filter((item) => item.status === "pending").map((operation) => <article key={operation.id}><div><strong>{operation.action} to {operation.remote}</strong><code>{operation.command}</code><small>{operation.remote_url}</small></div><div><button disabled={busy} onClick={() => decide(operation, "reject")}>Reject</button><button className="primary" disabled={busy} onClick={() => decide(operation, "approve")}>Approve & run</button></div></article>)}</div>}
    {notice && <div className="git-notice">{notice}</div>}
  </section><GitHubPanel projectId={projectId} branch={git.branch} onTaskQueued={onTaskQueued} /></>;
}
