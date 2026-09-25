"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { request } from "../lib/api";
import styles from "./SwarmPanel.module.css";

type Skill = { project_id:number; skill:"swarm"; enabled:boolean };
type SwarmProfile = { id:number; name:string; max_agents:number; max_concurrency:number; max_depth:number; dynamic_size:number; require_reviewer:number; require_challenger:number };
type Agent = { id:number; title:string; status:string; agent_role:string; assigned_model:string; task_kind:string; priority:number; progress:number; current_activity:string; depends_on?:number[]|string; run_id?:number|null; worktree_branch?:string; result?:string; error?:string; created_at:string; started_at?:string };
type SwarmRun = { id:number; project_id:number; title:string; objective:string; status:string; profile_id:number; max_agents:number; max_concurrency:number; total_agents_created:number; created_at:string; started_at:string; completed_at:string; agents?:Agent[]; agent_counts?:Record<string,number> };
type BlackboardItem = { id:number; task_id?:number|null; category:string; key:string; content:string; confidence?:number|null; created_at:string };

export function SwarmPanel({ projectId }: { projectId:number }) {
  const [skill,setSkill]=useState<Skill|null>(null);
  const [profiles,setProfiles]=useState<SwarmProfile[]>([]);
  const [runs,setRuns]=useState<SwarmRun[]>([]);
  const [selectedId,setSelectedId]=useState<number|null>(null);
  const [selected,setSelected]=useState<SwarmRun|null>(null);
  const [blackboard,setBlackboard]=useState<BlackboardItem[]>([]);
  const [profileId,setProfileId]=useState("");
  const [title,setTitle]=useState("");
  const [objective,setObjective]=useState("");
  const [maxAgents,setMaxAgents]=useState(5);
  const [maxConcurrency,setMaxConcurrency]=useState(3);
  const [notice,setNotice]=useState("");
  const [busy,setBusy]=useState(false);

  useEffect(()=>{ loadBootstrap(); },[projectId]);

  useEffect(()=>{
    if(!selectedId){ setSelected(null); setBlackboard([]); return; }
    let disposed=false;
    async function refresh(){
      try{
        const results=await Promise.all([
          request<SwarmRun>("/swarms/"+selectedId),
          request<BlackboardItem[]>("/swarms/"+selectedId+"/blackboard")
        ]);
        if(disposed)return;
        const run=results[0]; const board=results[1];
        setSelected(run); setBlackboard(board);
        setRuns(items=>items.map(item=>item.id===run.id?{...item,...run}:item));
      }catch(error){ if(!disposed)setNotice(error instanceof Error?error.message:String(error)); }
    }
    refresh();
    const timer=window.setInterval(refresh,2000);
    return()=>{disposed=true;window.clearInterval(timer);};
  },[selectedId]);

  async function loadBootstrap(){
    try{
      const results=await Promise.all([
        request<Skill>("/projects/"+projectId+"/skills/swarm"),
        request<SwarmProfile[]>("/swarm-profiles"),
        request<SwarmRun[]>("/projects/"+projectId+"/swarms")
      ]);
      const skillState=results[0]; const profileData=results[1]; const runData=results[2];
      setSkill(skillState); setProfiles(profileData); setRuns(runData);
      if(profileData.length && !profileId){
        const preferred=profileData.find(item=>item.name==="Development")||profileData[0];
        applyProfile(preferred);
      }
      if(runData.length){ setSelectedId(current=>current||runData[0].id); }
    }catch(error){ setNotice(error instanceof Error?error.message:String(error)); }
  }

  function applyProfile(profile:SwarmProfile){
    setProfileId(String(profile.id));
    setMaxAgents(profile.max_agents);
    setMaxConcurrency(profile.max_concurrency);
  }

  async function toggleSkill(){
    if(!skill)return;
    setBusy(true);
    try{
      const updated=await request<Skill>("/projects/"+projectId+"/skills/swarm",{
        method:"PUT",body:JSON.stringify({enabled:!skill.enabled})
      });
      setSkill(updated);
      setNotice(updated.enabled?"Swarm enabled for this project":"Swarm disabled for this project");
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function createSwarm(event:FormEvent){
    event.preventDefault();
    if(!objective.trim()||!profileId)return;
    setBusy(true);setNotice("Planning swarm…");
    try{
      const result=await request<{swarm:SwarmRun}>("/projects/"+projectId+"/swarms",{
        method:"POST",
        body:JSON.stringify({ objective:objective.trim(),title:title.trim(),profile_id:Number(profileId),max_agents:maxAgents,max_concurrency:maxConcurrency })
      });
      setObjective("");setTitle("");setSelectedId(result.swarm.id);
      await loadBootstrap();
      setNotice("Swarm #"+result.swarm.id+" started");
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function action(kind:"pause"|"resume"|"stop"){
    if(!selected)return;
    setBusy(true);
    try{
      const updated=kind==="stop"
        ? await request<SwarmRun>("/swarms/"+selected.id,{method:"DELETE"})
        : await request<SwarmRun>("/swarms/"+selected.id+"/"+kind,{method:"POST"});
      setSelected(updated); setRuns(items=>items.map(item=>item.id===updated.id?{...item,...updated}:item));
      setNotice("Swarm "+(kind==="stop"?"stopped":kind+"d"));
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function stopAgent(agent:Agent){
    setBusy(true);
    try{
      await request("/swarm-agents/"+agent.id,{method:"DELETE"});
      setNotice("Stop requested for agent #"+agent.id);
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  const agents=selected?.agents||[];
  const byId=useMemo(()=>new Map(agents.map(agent=>[agent.id,agent])),[agents]);
  const complete=agents.filter(agent=>agent.status==="completed").length;
  const active=agents.filter(agent=>["running","waiting_for_input","waiting_for_approval"].includes(agent.status)).length;
  const progress=agents.length?Math.round(agents.reduce((sum,agent)=>sum+(agent.status==="completed"?100:agent.status==="running"?50:agent.status==="failed"||agent.status==="cancelled"?100:0),0)/agents.length):0;

  return <div className={styles.panel}>
    <section className={styles.hero}>
      <div><p className="eyebrow">Local multi-agent development</p><h2>Swarm</h2><p>Coordinate multiple Ollama agents in isolated worktrees while keeping their roles, models and progress visible.</p></div>
      <button className={skill?.enabled?"primary":""} onClick={toggleSkill} disabled={busy||!skill}>{skill?.enabled?"Swarm enabled":"Enable Swarm"}</button>
    </section>

    {skill?.enabled&&<section className={styles.launch}>
      <div className={styles.sectionHead}><div><p className="eyebrow">New swarm</p><h3>Delegate a larger objective</h3></div></div>
      <form onSubmit={createSwarm}>
        <label>Preset<select value={profileId} onChange={event=>{const p=profiles.find(item=>String(item.id)===event.target.value);if(p)applyProfile(p);}}>{profiles.map(profile=><option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
        <label>Maximum agents<input type="number" min="2" max="20" value={maxAgents} onChange={event=>setMaxAgents(Number(event.target.value))}/></label>
        <label>Concurrency<input type="number" min="1" max="8" value={maxConcurrency} onChange={event=>setMaxConcurrency(Number(event.target.value))}/></label>
        <label>Title<input value={title} onChange={event=>setTitle(event.target.value)} placeholder="Optional swarm title"/></label>
        <label className={styles.objective}>Objective<textarea value={objective} onChange={event=>setObjective(event.target.value)} placeholder="Describe the outcome you want the team to deliver…"/></label>
        <button className="primary" disabled={busy||!objective.trim()||!profileId}>{busy?"Working…":"Start swarm"}</button>
      </form>
    </section>}

    <section className={styles.board}>
      <aside className={styles.runList}>
        <div className={styles.sectionHead}><div><p className="eyebrow">Swarm runs</p><h3>{runs.length} runs</h3></div></div>
        {runs.length?runs.map(run=><button key={run.id} className={selectedId===run.id?styles.selected:""} onClick={()=>setSelectedId(run.id)}>
          <span><strong>#{run.id} {run.title}</strong><small>{run.status} · {run.total_agents_created}/{run.max_agents} agents</small></span>
          <b>{run.agent_counts?.active||0}</b>
        </button>):<div className={styles.empty}>No swarm runs yet.</div>}
      </aside>

      <div className={styles.boardMain}>
        {selected?<><header className={styles.statusHead}>
          <div><p className="eyebrow">Swarm #{selected.id}</p><h2>{selected.title}</h2><p>{selected.objective}</p></div>
          <div className={styles.controls}>
            <span className={styles.status}>{selected.status}</span>
            {selected.status==="paused"?<button onClick={()=>action("resume")} disabled={busy}>Resume</button>:!["completed","failed","cancelled"].includes(selected.status)&&<button onClick={()=>action("pause")} disabled={busy}>Pause</button>}
            {!["completed","failed","cancelled"].includes(selected.status)&&<button onClick={()=>action("stop")} disabled={busy}>Stop</button>}
          </div>
        </header>

        <div className={styles.metrics}>
          <span><strong>{agents.length}/{selected.max_agents}</strong>agents</span>
          <span><strong>{active}/{selected.max_concurrency}</strong>running</span>
          <span><strong>{complete}</strong>complete</span>
          <span><strong>{progress}%</strong>progress</span>
        </div>
        <div className={styles.progress}><i style={{width:String(progress)+"%"}}/></div>

        <section className={styles.graphSection}>
          <div className={styles.sectionHead}><div><p className="eyebrow">Task graph</p><h3>Dependencies</h3></div></div>
          <div className={styles.graph}>
            {agents.map(agent=>{
              const deps=Array.isArray(agent.depends_on)?agent.depends_on:[];
              return <article key={agent.id} className={styles.node+" "+(styles[agent.status]||"")}>
                <header><span>#{agent.id}</span><b>{agent.status}</b></header>
                <strong>{agent.title}</strong>
                <small>{agent.agent_role} · {agent.assigned_model||"project model"}</small>
                <em>{deps.length?"after "+deps.map(id=>byId.get(id)?.title||("#"+id)).join(", "):"can start immediately"}</em>
              </article>;
            })}
          </div>
        </section>

        <section>
          <div className={styles.sectionHead}><div><p className="eyebrow">Agent board</p><h3>Live workers</h3></div></div>
          <div className={styles.agents}>
            {agents.map(agent=><article key={agent.id} className={styles.agent}>
              <header><div><i className={styles.dot+" "+(styles[agent.status]||"")}/><strong>Agent #{agent.id} · {agent.agent_role}</strong></div><span>{agent.status}</span></header>
              <h4>{agent.title}</h4>
              <dl><div><dt>Model</dt><dd>{agent.assigned_model||"Project default"}</dd></div><div><dt>Branch</dt><dd>{agent.worktree_branch||"waiting"}</dd></div><div><dt>Run</dt><dd>{agent.run_id?"#"+agent.run_id:"not started"}</dd></div></dl>
              <p>{agent.current_activity||agent.result||agent.error||"Waiting for activity…"}</p>
              <footer>{["queued","running","waiting_for_input","waiting_for_approval"].includes(agent.status)&&<button onClick={()=>stopAgent(agent)} disabled={busy}>Stop agent</button>}</footer>
            </article>)}
          </div>
        </section>

        <section>
          <div className={styles.sectionHead}><div><p className="eyebrow">Shared knowledge</p><h3>Blackboard</h3></div><span>{blackboard.length} entries</span></div>
          <div className={styles.blackboard}>{blackboard.length?blackboard.slice().reverse().map(item=><article key={item.id}><header><strong>{item.category}</strong>{item.task_id&&<span>Agent #{item.task_id}</span>}{item.confidence!=null&&<span>{Math.round(item.confidence*100)}%</span>}</header><p>{item.content}</p>{item.key&&<small>{item.key}</small>}</article>):<div className={styles.empty}>No shared findings yet.</div>}</div>
        </section>
        </>:<div className={styles.emptyLarge}><span>✦</span><h3>Select or start a swarm</h3><p>The board will show every local agent, its assigned model, task dependencies, worktree and shared findings.</p></div>}
      </div>
    </section>
    {notice&&<div className={styles.notice}>{notice}</div>}
  </div>;
}
