"use client";

import { FormEvent, useState } from "react";
import { request } from "../lib/api";

export type GitSummary = { repository: boolean; branch: string; branches: string[]; changes: { status: string; path: string; staged: boolean; unstaged: boolean }[]; recent: { sha: string; subject: string; age: string }[] };

export function GitControls({ projectId, git, onRefresh }: { projectId: number; git: GitSummary | null; onRefresh: () => Promise<void> }) {
  const [branchName, setBranchName] = useState("");
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

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

  if (!git?.repository) return <div className="git-controls empty-git"><strong>Git is not initialised</strong><span>Use the terminal to run `git init` if this project should be version controlled.</span></div>;

  return <section className="git-controls">
    <div className="git-control-head"><div><p className="eyebrow">Controlled Git workflow</p><h3>{git.branch}</h3></div><label>Switch branch<select value={git.branch} onChange={(e) => action("checkout", { name: e.target.value })} disabled={busy}>{git.branches.map((branch) => <option key={branch}>{branch}</option>)}</select></label></div>
    <form className="branch-form" onSubmit={createBranch}><input value={branchName} onChange={(e) => setBranchName(e.target.value)} placeholder="feature/new-branch" /><button disabled={busy || !branchName.trim()}>Create & switch</button></form>
    <div className="git-file-list">{git.changes.length ? git.changes.map((file) => <article key={file.path}><span className="git-code">{file.status}</span><strong>{file.path}</strong><div>{file.staged && <button disabled={busy} onClick={() => action("unstage", { paths: [file.path] })}>Unstage</button>}{(!file.staged || file.unstaged) && <button disabled={busy} onClick={() => action("stage", { paths: [file.path] })}>Stage</button>}</div></article>) : <p>Working tree clean</p>}</div>
    <form className="commit-form" onSubmit={commit}><input value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Commit message" /><button className="primary" disabled={busy || !message.trim() || !git.changes.some((item) => item.staged)}>Commit staged</button></form>
    {notice && <div className="git-notice">{notice}</div>}
  </section>;
}

