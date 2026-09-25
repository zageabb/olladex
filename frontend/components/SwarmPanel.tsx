"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { request } from "../lib/api";
import styles from "./SwarmPanel.module.css";

type Skill = { project_id:number; skill:"swarm"; enabled:boolean };
type SwarmProfile = { id:number; name:string; max_agents:number; max_concurrency:number; max_depth:number; dynamic_size:number; require_reviewer:number; require_challenger:number; coordinator_profile_id?:number|null; default_worker_profile_id?:number|null; role_profiles:Record<string,number>; agent_tool_budget:number; coordinator_tool_budget:number; is_builtin:number };
type ModelProfile = { id:number; name:string; chat_model:string };
type Agent = { id:number; title:string; status:string; agent_role:string; assigned_model:string; task_kind:string; priority:number; progress:number; current_activity:string; depends_on?:number[]|string; run_id?:number|null; worktree_branch?:string; result?:string; error?:string; created_at:string; started_at?:string };
type SwarmRun = { id:number; project_id:number; title:string; objective:string; status:string; profile_id:number; max_agents:number; max_concurrency:number; total_agents_created:number; created_at:string; started_at:string; completed_at:string; agents?:Agent[]; agent_counts?:Record<string,number>; integration_path?:string; integration_branch?:string; integration_check_command?:string; integration_check_status?:string; integration_check_output?:string; integration_pr_number?:number; integration_pr_url?:string; integration_pr_state?:string };
type BlackboardItem = { id:number; task_id?:number|null; category:string; key:string; content:string; confidence?:number|null; created_at:string };
type SwarmEvent = { id:number; run_id:number; task_id:number; task_title:string; agent_role:string; assigned_model:string; kind:string; payload:Record<string,unknown>; created_at:string };
type IntegrationPlan = { branches:string[]; overlaps:{path:string;branches:string[]}[]; files_by_branch:Record<string,string[]>; path?:string; branch?:string; check_status?:string; check_output?:string };

export function SwarmPanel({ projectId }: { projectId:number }) {
  const [skill,setSkill]=useState<Skill|null>(null);
  const [profiles,setProfiles]=useState<SwarmProfile[]>([]);
  const [modelProfiles,setModelProfiles]=useState<ModelProfile[]>([]);
  const [runs,setRuns]=useState<SwarmRun[]>([]);
  const [selectedId,setSelectedId]=useState<number|null>(null);
  const [selected,setSelected]=useState<SwarmRun|null>(null);
  const [blackboard,setBlackboard]=useState<BlackboardItem[]>([]);
  const [events,setEvents]=useState<SwarmEvent[]>([]);
  const [profileId,setProfileId]=useState("");
  const [title,setTitle]=useState("");
  const [objective,setObjective]=useState("");
  const [maxAgents,setMaxAgents]=useState(5);
  const [maxConcurrency,setMaxConcurrency]=useState(3);
  const [notice,setNotice]=useState("");
  const [busy,setBusy]=useState(false);
  const [selectedAgentId,setSelectedAgentId]=useState<number|null>(null);
  const [guidance,setGuidance]=useState("");
  const [coordinatorGuidance,setCoordinatorGuidance]=useState("");
  const [integrationIds,setIntegrationIds]=useState<number[]>([]);
  const [integrationPlan,setIntegrationPlan]=useState<IntegrationPlan|null>(null);
  const [checkCommand,setCheckCommand]=useState("python -m pytest backend/tests -q");
  const [integrationPushed,setIntegrationPushed]=useState(false);

  useEffect(()=>{ loadBootstrap(); },[projectId]);

  useEffect(()=>{
    setIntegrationIds([]);
    setIntegrationPlan(null);
    setIntegrationPushed(false);
    if(!selectedId){ setSelected(null); setBlackboard([]); setEvents([]); return; }
    let disposed=false;
    async function refresh(){
      try{
        const results=await Promise.all([
          request<SwarmRun>("/swarms/"+selectedId),
          request<BlackboardItem[]>("/swarms/"+selectedId+"/blackboard"),
          request<SwarmEvent[]>("/swarms/"+selectedId+"/events?after=0&limit=200")
        ]);
        if(disposed)return;
        const run=results[0]; const board=results[1]; const activity=results[2];
        setSelected(run); setBlackboard(board); setEvents(activity);
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
        request<SwarmRun[]>("/projects/"+projectId+"/swarms"),
        request<ModelProfile[]>("/model-profiles")
      ]);
      const skillState=results[0]; const profileData=results[1]; const runData=results[2]; const modelData=results[3];
      setSkill(skillState); setProfiles(profileData); setRuns(runData); setModelProfiles(modelData);
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

  async function saveSelectedProfile(profile:SwarmProfile, patch:Partial<SwarmProfile>){
    const updated={...profile,...patch};
    setBusy(true);
    try{
      const saved=await request<SwarmProfile>("/swarm-profiles/"+profile.id,{
        method:"PUT",
        body:JSON.stringify({
          name:updated.name,
          enabled:true,
          coordinator_profile_id:updated.coordinator_profile_id||null,
          default_worker_profile_id:updated.default_worker_profile_id||null,
          role_profiles:updated.role_profiles||{},
          max_agents:updated.max_agents,
          max_concurrency:updated.max_concurrency,
          max_depth:updated.max_depth,
          dynamic_size:Boolean(updated.dynamic_size),
          agent_tool_budget:updated.agent_tool_budget,
          coordinator_tool_budget:updated.coordinator_tool_budget,
          require_reviewer:Boolean(updated.require_reviewer),
          require_challenger:Boolean(updated.require_challenger)
        })
      });
      setProfiles(items=>items.map(item=>item.id===saved.id?saved:item));
      setNotice("Swarm model assignments saved");
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  function modelSelect(profile:SwarmProfile, role:string, value:number|null){
    const roleProfiles={...(profile.role_profiles||{})};
    if(value)roleProfiles[role]=value; else delete roleProfiles[role];
    setProfiles(items=>items.map(item=>item.id===profile.id?{...item,role_profiles:roleProfiles}:item));
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

  async function steerCoordinator(){
    if(!selected||!coordinatorGuidance.trim())return;
    setBusy(true);
    try{
      await request("/swarms/"+selected.id+"/coordinator/input",{
        method:"POST",body:JSON.stringify({content:coordinatorGuidance.trim()})
      });
      setCoordinatorGuidance(""); setNotice("Guidance sent to Coordinator");
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function steerAgent(agent:Agent){
    if(!guidance.trim())return;
    setBusy(true);
    try{
      await request("/swarm-agents/"+agent.id+"/input",{method:"POST",body:JSON.stringify({content:guidance.trim()})});
      setGuidance(""); setNotice("Guidance sent to agent #"+agent.id);
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  function toggleIntegrationTask(taskId:number){
    setIntegrationIds(items=>items.includes(taskId)?items.filter(id=>id!==taskId):[...items,taskId]);
  }

  async function preflightIntegration(){
    if(!selected||!integrationIds.length)return;
    setBusy(true);
    try{
      const plan=await request<IntegrationPlan>("/swarms/"+selected.id+"/integration/preflight",{
        method:"POST",body:JSON.stringify({task_ids:integrationIds,base:"main"})
      });
      setIntegrationPlan(plan); setNotice(plan.overlaps.length?"Integration preflight found overlapping files":"Integration preflight passed with no overlapping files");
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function createIntegration(){
    if(!selected||!integrationIds.length)return;
    setBusy(true);
    try{
      const result=await request<IntegrationPlan>("/swarms/"+selected.id+"/integration",{
        method:"POST",body:JSON.stringify({task_ids:integrationIds,base:"main"})
      });
      setIntegrationPlan(result);
      const refreshed=await request<SwarmRun>("/swarms/"+selected.id);
      setSelected(refreshed);
      setNotice("Integration worktree created");
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function pushIntegration(){
    if(!selected)return;
    setBusy(true);
    try{
      await request("/swarms/"+selected.id+"/integration/push",{method:"POST",body:JSON.stringify({remote:"origin"})});
      setIntegrationPushed(true); setNotice("Integration branch pushed");
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function createIntegrationPullRequest(){
    if(!selected)return;
    setBusy(true);
    try{
      const result=await request<{pull_request_number:number;url:string}>("/swarms/"+selected.id+"/integration/pull-request",{
        method:"POST",
        body:JSON.stringify({
          title:"Olladex Swarm #"+selected.id+": "+selected.title,
          body:"Integrated and verified by Olladex Swarm #"+selected.id+".\n\nObjective:\n"+selected.objective,
          base:"main"
        })
      });
      const refreshed=await request<SwarmRun>("/swarms/"+selected.id);
      setSelected(refreshed); setNotice("Pull request #"+result.pull_request_number+" created");
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function runIntegrationChecks(){
    if(!selected||!checkCommand.trim())return;
    setBusy(true);
    try{
      const result=await request<{passed:boolean;output:string;command:string}>("/swarms/"+selected.id+"/integration/checks",{
        method:"POST",body:JSON.stringify({command:checkCommand.trim()})
      });
      setIntegrationPlan(current=>current?{...current,check_status:result.passed?"passed":"failed",check_output:result.output}:current);
      const refreshed=await request<SwarmRun>("/swarms/"+selected.id);
      setSelected(refreshed);
      setNotice(result.passed?"Combined integration checks passed":"Combined integration checks failed");
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
  const selectedAgent=selectedAgentId?agents.find(agent=>agent.id===selectedAgentId)||null:null;
  const selectedAgentEvents=selectedAgent?events.filter(item=>item.task_id===selectedAgent.id):[];
  const integrationCandidates=agents.filter(agent=>agent.status==="completed"&&agent.task_kind!=="reviewer"&&agent.task_kind!=="challenger"&&Boolean(agent.worktree_branch));
  const activeSwarmProfile=selected?profiles.find(item=>item.id===selected.profile_id):undefined;
  const coordinatorProfile=activeSwarmProfile?.coordinator_profile_id?modelProfiles.find(item=>item.id===activeSwarmProfile.coordinator_profile_id):undefined;

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
      {profiles.find(item=>String(item.id)===profileId)&&<details className={styles.roleSettings}>
        <summary>Role model settings</summary>
        {(()=>{
          const profile=profiles.find(item=>String(item.id)===profileId)!;
          const roles=["backend","frontend","coder","tester","researcher","reviewer","challenger"];
          return <div className={styles.roleGrid}>
            <label>Coordinator<select value={profile.coordinator_profile_id||""} onChange={event=>setProfiles(items=>items.map(item=>item.id===profile.id?{...item,coordinator_profile_id:event.target.value?Number(event.target.value):null}:item))}><option value="">Project default</option>{modelProfiles.map(model=><option key={model.id} value={model.id}>{model.name} · {model.chat_model}</option>)}</select></label>
            <label>Default worker<select value={profile.default_worker_profile_id||""} onChange={event=>setProfiles(items=>items.map(item=>item.id===profile.id?{...item,default_worker_profile_id:event.target.value?Number(event.target.value):null}:item))}><option value="">Project default</option>{modelProfiles.map(model=><option key={model.id} value={model.id}>{model.name} · {model.chat_model}</option>)}</select></label>
            {roles.map(role=><label key={role}>{role}<select value={(profile.role_profiles||{})[role]||""} onChange={event=>modelSelect(profile,role,event.target.value?Number(event.target.value):null)}><option value="">Use default worker</option>{modelProfiles.map(model=><option key={model.id} value={model.id}>{model.name} · {model.chat_model}</option>)}</select></label>)}
            <label><span>Final reviewer</span><input type="checkbox" checked={Boolean(profile.require_reviewer)} onChange={event=>setProfiles(items=>items.map(item=>item.id===profile.id?{...item,require_reviewer:event.target.checked?1:0}:item))}/></label>
            <label><span>Challenger</span><input type="checkbox" checked={Boolean(profile.require_challenger)} onChange={event=>setProfiles(items=>items.map(item=>item.id===profile.id?{...item,require_challenger:event.target.checked?1:0}:item))}/></label>
            <div className={styles.roleActions}><button type="button" onClick={()=>saveSelectedProfile(profile,{})} disabled={busy}>Save role assignments</button></div>
          </div>;
        })()}
      </details>}
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

        <article className={styles.coordinator}>
          <div><i className={styles.dot+" "+(selected.status==="failed"?"failed":selected.status==="completed"?"completed":"running")}/><span><strong>Coordinator</strong><small>{coordinatorProfile?.chat_model||"Project default"} · {selected.status==="reviewing"?"Evaluating verification and review flow":selected.status==="running"?"Monitoring specialists, Blackboard and recovery conditions":selected.status==="paused"?"Paused with swarm":"Coordinator "+selected.status}</small></span></div>
          <b>{selected.status}</b>
        </article>
        {!["completed","failed","cancelled"].includes(selected.status)&&<form className={styles.coordinatorGuidance} onSubmit={event=>{event.preventDefault();steerCoordinator();}}>
          <input value={coordinatorGuidance} onChange={event=>setCoordinatorGuidance(event.target.value)} placeholder="Guide Coordinator — e.g. prioritise tests; do not change public API"/>
          <button disabled={busy||!coordinatorGuidance.trim()}>Send to Coordinator</button>
        </form>}

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
              <footer><button onClick={()=>setSelectedAgentId(agent.id)}>Open agent</button>{["queued","running","waiting_for_input","waiting_for_approval"].includes(agent.status)&&<button onClick={()=>stopAgent(agent)} disabled={busy}>Stop agent</button>}</footer>
            </article>)}
          </div>
        </section>

        <section>
          <div className={styles.sectionHead}><div><p className="eyebrow">Live activity</p><h3>Agent timeline</h3></div><span>{events.length} events</span></div>
          <div className={styles.timeline}>{events.length?events.slice().reverse().map(item=><article key={item.id}>
            <time>{new Date(item.created_at).toLocaleTimeString()}</time>
            <strong>Agent #{item.task_id} · {item.agent_role}</strong>
            <b>{item.kind}</b>
            <p>{eventText(item)}</p>
          </article>):<div className={styles.empty}>No activity yet.</div>}</div>
        </section>

        {(selected.status==="completed"||selected.status==="integrating")&&<section className={styles.integration}>
          <div className={styles.sectionHead}><div><p className="eyebrow">Integration</p><h3>Combine verified specialist branches</h3></div><span>{selected.integration_check_status||"not checked"}</span></div>
          <div className={styles.integrationTasks}>{integrationCandidates.length?integrationCandidates.map(agent=><label key={agent.id}><input type="checkbox" checked={integrationIds.includes(agent.id)} onChange={()=>toggleIntegrationTask(agent.id)}/><span><strong>Agent #{agent.id} · {agent.title}</strong><small>{agent.worktree_branch}</small></span></label>):<div className={styles.empty}>No completed implementation branches are available.</div>}</div>
          <div className={styles.integrationActions}><button onClick={preflightIntegration} disabled={busy||!integrationIds.length}>Preflight</button>{selected.status==="completed"&&<button className="primary" onClick={createIntegration} disabled={busy||!integrationIds.length}>Create integration</button>}</div>
          {integrationPlan&&<div className={styles.integrationSummary}><span><strong>{integrationPlan.branches?.length||0}</strong> branches</span><span><strong>{integrationPlan.overlaps?.length||0}</strong> overlaps</span>{integrationPlan.branch&&<span><strong>{integrationPlan.branch}</strong> integration branch</span>}</div>}
          {selected.integration_path&&<div className={styles.integrationChecks}><input value={checkCommand} onChange={event=>setCheckCommand(event.target.value)} placeholder="Combined verification command"/><button onClick={runIntegrationChecks} disabled={busy||!checkCommand.trim()}>Run combined checks</button></div>}
          {(selected.integration_check_output||integrationPlan?.check_output)&&<pre className={styles.checkOutput}>{selected.integration_check_output||integrationPlan?.check_output}</pre>}
          {selected.integration_check_status==="passed"&&<div className={styles.integrationPublish}>
            <button onClick={pushIntegration} disabled={busy}>{integrationPushed?"Pushed":"Push integration branch"}</button>
            <button className="primary" onClick={createIntegrationPullRequest} disabled={busy||(!integrationPushed&&!selected.integration_pr_url)}>{selected.integration_pr_number?"PR #"+selected.integration_pr_number:"Create pull request"}</button>
            {selected.integration_pr_url&&<small>{selected.integration_pr_url}</small>}
          </div>}
        </section>}

        <section>
          <div className={styles.sectionHead}><div><p className="eyebrow">Shared knowledge</p><h3>Blackboard</h3></div><span>{blackboard.length} entries</span></div>
          <div className={styles.blackboard}>{blackboard.length?blackboard.slice().reverse().map(item=><article key={item.id}><header><strong>{item.category}</strong>{item.task_id&&<span>Agent #{item.task_id}</span>}{item.confidence!=null&&<span>{Math.round(item.confidence*100)}%</span>}</header><p>{item.content}</p>{item.key&&<small>{item.key}</small>}</article>):<div className={styles.empty}>No shared findings yet.</div>}</div>
        </section>
        </>:<div className={styles.emptyLarge}><span>✦</span><h3>Select or start a swarm</h3><p>The board will show every local agent, its assigned model, task dependencies, worktree and shared findings.</p></div>}
      </div>
    </section>
    {selectedAgent&&<div className={styles.agentDrawer}>
      <div className={styles.drawerHead}><div><p className="eyebrow">Agent #{selectedAgent.id}</p><h3>{selectedAgent.title}</h3><small>{selectedAgent.agent_role} · {selectedAgent.assigned_model||"Project default"}</small></div><button onClick={()=>setSelectedAgentId(null)}>×</button></div>
      <div className={styles.drawerMeta}><span><b>Status</b>{selectedAgent.status}</span><span><b>Branch</b>{selectedAgent.worktree_branch||"waiting"}</span><span><b>Run</b>{selectedAgent.run_id?"#"+selectedAgent.run_id:"not started"}</span></div>
      <div className={styles.drawerEvents}>{selectedAgentEvents.length?selectedAgentEvents.slice().reverse().map(item=><article key={item.id}><time>{new Date(item.created_at).toLocaleTimeString()}</time><b>{item.kind}</b><p>{eventText(item)}</p></article>):<div className={styles.empty}>No events for this agent yet.</div>}</div>
      {selectedAgent.run_id&&["running","waiting_for_input","waiting_for_approval"].includes(selectedAgent.status)&&<form className={styles.guidance} onSubmit={event=>{event.preventDefault();steerAgent(selectedAgent);}}><textarea value={guidance} onChange={event=>setGuidance(event.target.value)} placeholder="Give this agent guidance without stopping its run…"/><button className="primary" disabled={busy||!guidance.trim()}>Send guidance</button></form>}
    </div>}
    {notice&&<div className={styles.notice}>{notice}</div>}
  </div>;
}


function eventText(item:SwarmEvent){
  const payload=item.payload||{};
  const direct=payload["content"]||payload["message"]||payload["summary"]||payload["status"]||payload["question"];
  if(typeof direct==="string"&&direct.trim())return direct;
  const steps=payload["steps"];
  if(Array.isArray(steps))return steps.map(String).join(" · ");
  const tool=payload["tool"];
  if(typeof tool==="string")return "Using "+tool;
  return item.task_title||item.kind.replaceAll("_"," ");
}
