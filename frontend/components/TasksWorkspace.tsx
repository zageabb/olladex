"use client";

import { useState } from "react";
import { BackgroundTasksPanel } from "./BackgroundTasksPanel";
import { TaskOrchestrationPanel } from "./TaskOrchestrationPanel";

type View = "orchestrate" | "queue";

export function TasksWorkspace({ projectId, onOpenSession, onCreated }: { projectId: number; onOpenSession: (sessionId: number) => void; onCreated: () => void }) {
  const [view, setView] = useState<View>("orchestrate");

  return <div className="tasks-dashboard">
    <section className="tasks-dashboard-head">
      <div>
        <p className="eyebrow">Development tasks</p>
        <h2>Plan, run and promote work</h2>
        <p>Use orchestration for larger objectives. Use the queue for individual background jobs, branch review and pull requests.</p>
      </div>
      <div className="tasks-workflow-strip" aria-label="Task workflow">
        <span><b>1</b> Plan</span><i>→</i><span><b>2</b> Run</span><i>→</i><span><b>3</b> Review</span><i>→</i><span><b>4</b> Integrate</span>
      </div>
    </section>

    <nav className="tasks-mode-tabs" aria-label="Task workspace view">
      <button type="button" className={view === "orchestrate" ? "active" : ""} onClick={() => setView("orchestrate")}>
        <span>✦</span><div><strong>Orchestrate</strong><small>One objective → specialist agents → integration</small></div>
      </button>
      <button type="button" className={view === "queue" ? "active" : ""} onClick={() => setView("queue")}>
        <span>◷</span><div><strong>Queue & branches</strong><small>Individual jobs → worktree → PR lifecycle</small></div>
      </button>
    </nav>

    <section className="tasks-mode-content">
      {view === "orchestrate" ? <>
        <div className="tasks-context-note"><strong>Best for:</strong> features that need several coordinated changes. Start with the objective at the top; open Review or Integrate only when the lead has produced work.</div>
        <TaskOrchestrationPanel projectId={projectId} onCreated={onCreated} />
      </> : <>
        <div className="tasks-context-note"><strong>Best for:</strong> a single coding job, imported issue, or reviewing/publishing an agent branch. Expand a task only when you need its branch or PR controls.</div>
        <BackgroundTasksPanel projectId={projectId} onOpenSession={onOpenSession} />
      </>}
    </section>
  </div>;
}
