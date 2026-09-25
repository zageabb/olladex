"use client";

import { FormEvent, useEffect, useState } from "react";
import { request } from "../lib/api";

type Project = { id: number; name: string; path: string };
type Workspace = { id: number; name: string; description: string; projects?: Project[] };

export function WorkspacePanel({ projectId, projectName, projects, onProjectChange }: { projectId: number; projectName: string; projects: Project[]; onProjectChange?: () => void }) {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [current, setCurrent] = useState<Workspace | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    try {
      const [items, active] = await Promise.all([
        request<Workspace[]>("/workspaces"),
        request<Workspace | null>(`/projects/${projectId}/workspace`),
      ]);
      setWorkspaces(items);
      setCurrent(active);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error));
    }
  }

  useEffect(() => { void load(); }, [projectId]);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      const created = await request<Workspace>("/workspaces", { method: "POST", body: JSON.stringify({ name: name.trim(), description: description.trim() }) });
      await request(`/workspaces/${created.id}/projects`, { method: "POST", body: JSON.stringify({ project_id: projectId }) });
      setName(""); setDescription(""); setNotice(`Created ${created.name} and added ${projectName}`);
      await load(); onProjectChange?.();
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function assign(workspaceId: number) {
    try {
      if (current && current.id !== workspaceId) {
        await request(`/workspaces/${current.id}/projects/${projectId}`, { method: "DELETE" });
      }
      await request(`/workspaces/${workspaceId}/projects`, { method: "POST", body: JSON.stringify({ project_id: projectId }) });
      setNotice("Workspace membership updated"); await load(); onProjectChange?.();
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  async function remove() {
    if (!current) return;
    try {
      await request(`/workspaces/${current.id}/projects/${projectId}`, { method: "DELETE" });
      setNotice("Project removed from workspace"); await load(); onProjectChange?.();
    } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
  }

  return <div className="workspace-panel">
    <section className="workspace-hero">
      <div><p className="eyebrow">Workspaces</p><h2>Group related projects</h2><p>Projects in the same workspace can share workspace memory safely and become candidates for future cross-project retrieval.</p></div>
      <div className="workspace-current"><span>Current</span><strong>{current?.name || "No workspace"}</strong><small>{current ? `${current.projects?.length || 0} project(s)` : "Project memory stays isolated"}</small></div>
    </section>

    <section className="workspace-list">
      <header><div><p className="eyebrow">Available workspaces</p><h3>{workspaces.length} workspace{workspaces.length === 1 ? "" : "s"}</h3></div></header>
      {workspaces.length ? workspaces.map(item => <article key={item.id} className={current?.id === item.id ? "selected" : ""}>
        <div><strong>{item.name}</strong><small>{item.description || "No description"}</small><span>{item.projects?.map(project => project.name).join(", ") || "No projects"}</span></div>
        <div>{current?.id === item.id ? <button onClick={remove}>Remove project</button> : <button className="primary" onClick={() => assign(item.id)}>Use workspace</button>}</div>
      </article>) : <p className="workspace-empty">No workspaces yet.</p>}
    </section>

    <section className="workspace-create">
      <div><p className="eyebrow">New workspace</p><h3>Create a project group</h3><p>For example: “Local AI Development” could group olladex, Context Studio and localLLM.</p></div>
      <form onSubmit={create}><label>Name<input value={name} onChange={event => setName(event.target.value)} placeholder="Local AI Development" /></label><label>Description<textarea value={description} onChange={event => setDescription(event.target.value)} placeholder="Shared local AI tooling and services" /></label><button className="primary" disabled={!name.trim()}>Create & add {projectName}</button></form>
    </section>
    {notice && <div className="queue-notice">{notice}</div>}
  </div>;
}
