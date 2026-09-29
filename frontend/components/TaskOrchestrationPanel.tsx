"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { request } from "../lib/api";
import { MarkdownBody } from "./MarkdownBody";
import styles from "./TaskOrchestrationPanel.module.css";

type Node = { id:number; title:string; status:string; agent_role:string; parent_task_id?:number|null; depends_on:number[]; children:number[]; worktree_branch:string; pr_number:number; pr_state:string; result?:string; error?:string };
type Graph = { project_id:number; nodes:Node[] };
type ReviewItem = { id:number; title:string; agent_role:string; status:string; depends_on:number[]; worktree_branch:string; pull_request_number:number; pull_request_state:string; result?:string; error?:string; branch?:{branch_diff:string;working_diff:string;changes:string[]}|null; branch_error?:string };
type ReviewBundle = { task_id:number; base:string; items:ReviewItem[] };
type Draft = { title:string; prompt:string; role:string; parent:string; dependencies:string };
type LeadDraft = { title:string; objective:string; maxTasks:number };
type LeadResponse = { lead:Node; specialists:unknown[]; reviewer:unknown; plan:{title:string;role:string;prompt:string;depends_on:number[]}[] };
type IntegrationState = { lead_task_id:number; path:string; branch:string; base:string; diff?:string; changes?:string[]; check_command?:string; check_status?:string; check_output?:string; pull_request_number?:number; pull_request_url?:string; pull_request_state?:string };
type IntegrationPreflight = { lead_task_id:number; task_ids:number[]; base:string; branches:string[]; files_by_branch:Record<string,string[]>; overlaps:{path:string;branches:string[]}[] };
type SwarmListItem = { id:number; title:string; status:string; max_agents:number; max_concurrency:number; total_agents_created:number };
type PendingCommand = { id:number; run_id?:number; command:string; cwd:string; status:string; output?:string; exit_code?:number; created_at?:string; updated_at?:string };
type BudgetRequest = { id:number; swarm_id:number; task_id?:number|null; run_id?:number|null; scope:"agent"|"coordinator"; status:string; requested_amount:number; granted_amount:number; reason:string; decided_by:string };
type RecoveryInfo = { task_id:number; status:string; session_id:number; active_run_id:number; prior_run_id:number; prior_run_status:string; checkpoint_available:boolean; checkpoint_bytes:number; worktree_path:string; worktree_branch:string; worktree_available:boolean; branch_available:boolean; previous_budget:number; resumed_budget:number; max_recovery_attempts:number; recovery_attempt:number; blocking_dependency_ids:number[]; can_resume:boolean };
type SwarmAgent = { id:number; title:string; status:string; agent_role:string; progress?:number; assigned_model?:string; current_activity?:string; tool_usage?:number; tool_budget?:number; latest_insight?:{category:string;content:string}|null; task_kind?:string; worktree_branch?:string; result?:string; session_id?:number; run_id?:number; run_status?:string; pending_approval?:PendingCommand|null; blocking_dependency_ids?:number[]; recovery_attempt?:number; recovery?:RecoveryInfo|null };
type SwarmAgentDetail = { task:SwarmAgent; run?:{id:number;session_id:number;task_id:number;status:string;cancel_requested:number}|null; commands:PendingCommand[]; active_pending_commands:PendingCommand[]; blackboard:{id:number;category:string;content:string}[]; changed_files:string[]; worktree?:{branch_diff?:string;working_diff?:string}|null };
type GitCapabilities = { repository:boolean; has_head:boolean; remotes:{name:string;url:string}[]; has_remote:boolean; github_remote:string; can_push:boolean; can_create_pull_request:boolean };
type SwarmBoard = {
  swarm:{ id:number; title:string; status:string; agents?:SwarmAgent[]; coordinator_activity?:{category:string;content:string}|null; coordinator_budget?:{used:number;budget:number;remaining:number}; integration_path?:string; integration_branch?:string; integration_check_status?:string; integration_check_output?:string; integration_pushed?:number; integration_pr_number?:number; integration_pr_url?:string; integration_pr_state?:string; promotion_status?:string; promoted_commit?:string; promotion_output?:string };
  summary:{ total_agents:number; active_agents:number; completed_agents:number; failed_agents:number; progress:number; max_agents:number; max_concurrency:number; integration_ready:boolean; recovery_available?:boolean; recovery_blockers?:{task_id:number;title:string;status:string;blocking_dependency_ids:number[];recovery?:RecoveryInfo|null}[]; integration_blockers?:string[] };
  events?:{id:number;task_id:number;kind:string;payload:Record<string,unknown>;created_at:string}[];
  coordinator_events?:{id:number;kind:string;payload:Record<string,unknown>;created_at:string}[];
  blackboard?:{id:number;task_id?:number|null;category:string;content:string;key?:string;created_at:string}[];
  cursors?:{event:number;coordinator_event:number;blackboard:number};
  repository?:GitCapabilities;
  budget_requests?:BudgetRequest[];
  locations?:{main:string;integration:string;specialists:{task_id:number;title:string;role:string;path:string;branch:string;status:string}[]};
};
type SwarmSkill = { project_id:number; skill:"swarm"; enabled:boolean };
type SwarmProfile = { id:number; name:string; max_agents:number; max_concurrency:number; max_depth:number; dynamic_size:number; agent_tool_budget:number; coordinator_tool_budget:number; resumed_task_tool_budget:number; max_recovery_attempts:number; require_reviewer:number; require_challenger:number; coordinator_profile_id?:number|null; default_worker_profile_id?:number|null; role_profiles?:Record<string,number> };
type ModelProfile = { id:number; name:string; chat_model:string };
type SwarmPreflight = { ready:boolean; checks:{name:string;ok:boolean;detail:string}[]; max_agents:number; max_concurrency:number; git:GitCapabilities };
type SwarmModelSelfTest = { ready:boolean; models:{model:string;roles:string[];ok:boolean;latency_ms:number;response:string;error?:string}[] };
type SwarmIntegrationPlan = { task_ids?:number[]; branches:string[]; overlaps:{path:string;branches:string[]}[]; files_by_branch?:Record<string,string[]>; path?:string; branch?:string; check_status?:string; check_output?:string };

export function TaskOrchestrationPanel({ projectId, onCreated, onOpenConversation }: { projectId:number; onCreated:()=>void; onOpenConversation?:(sessionId:number)=>void }) {
  const [graph,setGraph]=useState<Graph>({project_id:projectId,nodes:[]});
  const [review,setReview]=useState<ReviewBundle|null>(null);
  const [draft,setDraft]=useState<Draft>({title:"",prompt:"",role:"worker",parent:"",dependencies:""});
  const [leadDraft,setLeadDraft]=useState<LeadDraft>({title:"",objective:"",maxTasks:6});
  const [lastPlan,setLastPlan]=useState<LeadResponse["plan"]>([]);
  const [selectedLead,setSelectedLead]=useState<number|null>(null);
  const [selectedTasks,setSelectedTasks]=useState<number[]>([]);
  const [integration,setIntegration]=useState<IntegrationState|null>(null);
  const [preflight,setPreflight]=useState<IntegrationPreflight|null>(null);
  const [checkCommand,setCheckCommand]=useState("python -m pytest backend/tests -q && cd frontend && npx tsc --noEmit && npm run build");
  const [prTitle,setPrTitle]=useState("");
  const [prBody,setPrBody]=useState("Integrated and validated by Olladex multi-agent orchestration.");
  const [notice,setNotice]=useState("");
  const [busy,setBusy]=useState(false);
  const [swarmBoard,setSwarmBoard]=useState<SwarmBoard|null>(null);
  const [swarmRuns,setSwarmRuns]=useState<SwarmListItem[]>([]);
  const [selectedSwarmId,setSelectedSwarmId]=useState<number|null>(null);
  const [swarmSkill,setSwarmSkill]=useState<SwarmSkill|null>(null);
  const [swarmProfiles,setSwarmProfiles]=useState<SwarmProfile[]>([]);
  const [modelProfiles,setModelProfiles]=useState<ModelProfile[]>([]);
  const [swarmProfileId,setSwarmProfileId]=useState("");
  const [swarmObjective,setSwarmObjective]=useState("");
  const [swarmTitle,setSwarmTitle]=useState("");
  const [swarmMaxAgents,setSwarmMaxAgents]=useState(5);
  const [swarmConcurrency,setSwarmConcurrency]=useState(3);
  const [swarmPreflight,setSwarmPreflight]=useState<SwarmPreflight|null>(null);
  const [swarmSelfTest,setSwarmSelfTest]=useState<SwarmModelSelfTest|null>(null);
  const [selectedSwarmAgentId,setSelectedSwarmAgentId]=useState<number|null>(null);
  const [selectedSwarmAgent,setSelectedSwarmAgent]=useState<SwarmAgentDetail|null>(null);
  const [agentGuidance,setAgentGuidance]=useState("");
  const [swarmGuidance,setSwarmGuidance]=useState("");
  const [swarmIntegration,setSwarmIntegration]=useState<SwarmIntegrationPlan|null>(null);
  const [swarmCheckCommand,setSwarmCheckCommand]=useState("python -m pytest backend/tests -q && cd frontend && npx tsc --noEmit && npm run build");
  const [swarmIntegrationPushed,setSwarmIntegrationPushed]=useState(false);
  const [budgetGrantAmounts,setBudgetGrantAmounts]=useState<Record<number,string>>({});
  const swarmCursors=useRef({event:0,coordinator_event:0,blackboard:0});

  useEffect(()=>{
    swarmCursors.current={event:0,coordinator_event:0,blackboard:0};
    setSwarmBoard(null);
    load(); loadSwarmSettings();
    const timer=window.setInterval(load,1000);
    return()=>window.clearInterval(timer);
  },[projectId,selectedSwarmId]);
  async function load(){
    try{
      const [nextGraph,swarmRuns]=await Promise.all([
        request<Graph>(`/projects/${projectId}/orchestration`),
        request<SwarmListItem[]>(`/projects/${projectId}/swarms`)
      ]);
      setGraph(nextGraph);
      setSwarmRuns(swarmRuns);
      const selectedSwarm=(selectedSwarmId?swarmRuns.find(item=>item.id===selectedSwarmId):null)
        ||swarmRuns.find(item=>!["completed","failed","cancelled"].includes(item.status))
        ||swarmRuns[0];
      if(selectedSwarm){
        if(selectedSwarmId!==selectedSwarm.id)setSelectedSwarmId(selectedSwarm.id);
        const cursor=swarmCursors.current;
        const board=await request<SwarmBoard>(`/swarms/${selectedSwarm.id}/board?after_event=${cursor.event}&after_coordinator_event=${cursor.coordinator_event}&after_blackboard=${cursor.blackboard}&limit=80`);
        setSwarmBoard(current=>{
          if(!current||current.swarm.id!==board.swarm.id)return board;
          return {
            ...board,
            events:mergeById(current.events||[],board.events||[],200),
            coordinator_events:mergeById(current.coordinator_events||[],board.coordinator_events||[],200),
            blackboard:mergeById(current.blackboard||[],board.blackboard||[],300)
          };
        });
        if(board.cursors)swarmCursors.current=board.cursors;
        if(board.swarm.integration_branch){
          setSwarmIntegration(current=>current||{
            branches:[],
            overlaps:[],
            path:board.swarm.integration_path,
            branch:board.swarm.integration_branch,
            check_status:board.swarm.integration_check_status,
            check_output:board.swarm.integration_check_output
          });
          setSwarmIntegrationPushed(Boolean(board.swarm.integration_pushed||board.swarm.integration_pr_number));
        }else if(!["integrating","completed"].includes(board.swarm.status)){
          setSwarmIntegration(null);
          setSwarmIntegrationPushed(false);
        }
      }else{
        setSelectedSwarmId(null);
        swarmCursors.current={event:0,coordinator_event:0,blackboard:0};
        setSwarmBoard(null);
        setSwarmIntegration(null);
        setSwarmIntegrationPushed(false);
      }
    }catch(error){ setNotice(error instanceof Error?error.message:String(error)); }
  }

  async function loadSwarmSettings(){
    try{
      const [skill,profiles,models]=await Promise.all([
        request<SwarmSkill>(`/projects/${projectId}/skills/swarm`),
        request<SwarmProfile[]>("/swarm-profiles"),
        request<ModelProfile[]>("/model-profiles")
      ]);
      setSwarmSkill(skill);
      setSwarmProfiles(profiles);
      setModelProfiles(models);
      if(profiles.length&&!swarmProfileId){
        const preferred=profiles.find(item=>item.name==="Development")||profiles[0];
        setSwarmProfileId(String(preferred.id));
        setSwarmMaxAgents(preferred.max_agents);
        setSwarmConcurrency(preferred.max_concurrency);
      }
    }catch(error){ setNotice(error instanceof Error?error.message:String(error)); }
  }

  async function toggleSwarmSkill(){
    if(!swarmSkill)return;
    setBusy(true);
    try{
      const updated=await request<SwarmSkill>(`/projects/${projectId}/skills/swarm`,{
        method:"PUT",body:JSON.stringify({enabled:!swarmSkill.enabled})
      });
      setSwarmSkill(updated);
      setNotice(updated.enabled?"Advanced orchestration enabled for this project":"Advanced orchestration disabled for this project");
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function swarmAction(kind:"pause"|"resume"|"stop"){
    if(!swarmBoard)return;
    setBusy(true);
    try{
      if(kind==="stop") await request(`/swarms/${swarmBoard.swarm.id}`,{method:"DELETE"});
      else await request(`/swarms/${swarmBoard.swarm.id}/${kind}`,{method:"POST"});
      setNotice(kind==="stop"?"Advanced orchestration stopped":`Advanced orchestration ${kind}d`);
      await load();
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function sendSwarmGuidance(all:boolean){
    if(!swarmBoard||!swarmGuidance.trim())return;
    setBusy(true);
    try{
      const endpoint=all
        ? `/swarms/${swarmBoard.swarm.id}/broadcast`
        : `/swarms/${swarmBoard.swarm.id}/coordinator/input`;
      await request(endpoint,{method:"POST",body:JSON.stringify({content:swarmGuidance.trim()})});
      setNotice(all?"Guidance applied across Advanced orchestration":"Guidance sent to Coordinator");
      setSwarmGuidance("");
      await load();
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function sendAgentGuidance(){
    if(!selectedSwarmAgent||!agentGuidance.trim())return;
    setBusy(true);
    try{
      await request(`/swarm-agents/${selectedSwarmAgent.task.id}/input`,{
        method:"POST",body:JSON.stringify({content:agentGuidance.trim()})
      });
      setNotice(`Guidance sent to agent #${selectedSwarmAgent.task.id}`);
      setAgentGuidance("");
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function stopSwarmAgent(){
    if(!selectedSwarmAgent)return;
    setBusy(true);
    try{
      await request(`/swarm-agents/${selectedSwarmAgent.task.id}`,{method:"DELETE"});
      setNotice(`Stop requested for agent #${selectedSwarmAgent.task.id}`);
      setSelectedSwarmAgentId(null);
      await load();
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function initializeSwarmGit(){
    if(!swarmProfileId)return;
    setBusy(true);
    try{
      await request(`/projects/${projectId}/swarms/git/init`,{method:"POST"});
      const query=new URLSearchParams({
        profile_id:swarmProfileId,
        max_agents:String(swarmMaxAgents),
        max_concurrency:String(swarmConcurrency)
      });
      const readiness=await request<SwarmPreflight>(`/projects/${projectId}/swarms/preflight?${query.toString()}`);
      setSwarmPreflight(readiness);
      setNotice(readiness.ready?"Local Git baseline created; Advanced orchestration is ready":"Local Git baseline created; review the remaining preflight checks");
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function testSwarmModels(){
    if(!swarmProfileId)return;
    setBusy(true);setSwarmSelfTest(null);
    try{
      const result=await request<SwarmModelSelfTest>(`/projects/${projectId}/swarms/self-test?profile_id=${swarmProfileId}`,{method:"POST"});
      setSwarmSelfTest(result);
      setNotice(result.ready?"All configured Advanced orchestration models responded":"One or more configured Advanced orchestration models failed the self-test");
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  function updateSwarmProfile(profileId:number, patch:Partial<SwarmProfile>){
    setSwarmProfiles(items=>items.map(item=>item.id===profileId?{...item,...patch}:item));
  }

  function updateRoleProfile(profile:SwarmProfile, role:string, modelId:number|null){
    const roles={...(profile.role_profiles||{})};
    if(modelId)roles[role]=modelId;else delete roles[role];
    updateSwarmProfile(profile.id,{role_profiles:roles});
  }

  async function saveSwarmProfile(profile:SwarmProfile){
    setBusy(true);
    try{
      const saved=await request<SwarmProfile>(`/swarm-profiles/${profile.id}`,{
        method:"PUT",
        body:JSON.stringify({
          name:profile.name,
          enabled:true,
          coordinator_profile_id:profile.coordinator_profile_id||null,
          default_worker_profile_id:profile.default_worker_profile_id||null,
          role_profiles:profile.role_profiles||{},
          max_agents:profile.max_agents,
          max_concurrency:profile.max_concurrency,
          max_depth:profile.max_depth,
          dynamic_size:Boolean(profile.dynamic_size),
          agent_tool_budget:profile.agent_tool_budget,
          coordinator_tool_budget:profile.coordinator_tool_budget,
          resumed_task_tool_budget:profile.resumed_task_tool_budget,
          max_recovery_attempts:profile.max_recovery_attempts,
          require_reviewer:Boolean(profile.require_reviewer),
          require_challenger:Boolean(profile.require_challenger)
        })
      });
      setSwarmProfiles(items=>items.map(item=>item.id===saved.id?saved:item));
      setNotice("Advanced orchestration model and policy settings saved");
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  function swarmIntegrationTaskIds(){
    return (swarmBoard?.swarm.agents||[])
      .filter(agent=>agent.status==="completed"&&agent.worktree_branch&&!["reviewer","challenger"].includes(agent.task_kind||agent.agent_role))
      .map(agent=>agent.id);
  }

  async function checkSwarmIntegration(){
    if(!swarmBoard)return;
    const taskIds=swarmIntegrationTaskIds();
    if(!taskIds.length){setNotice("No completed specialist branches are ready to integrate");return;}
    setBusy(true);
    try{
      const plan=await request<SwarmIntegrationPlan>(`/swarms/${swarmBoard.swarm.id}/integration/preflight`,{
        method:"POST",body:JSON.stringify({task_ids:taskIds,base:"main"})
      });
      setSwarmIntegration({...plan,task_ids:taskIds});
      setNotice(plan.overlaps.length?`Integration preflight found ${plan.overlaps.length} overlapping file(s)`:"Integration preflight passed");
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function buildSwarmIntegration(){
    if(!swarmBoard)return;
    const taskIds=swarmIntegration?.task_ids||swarmIntegrationTaskIds();
    if(!taskIds.length)return;
    setBusy(true);
    try{
      const result=await request<SwarmIntegrationPlan>(`/swarms/${swarmBoard.swarm.id}/integration`,{
        method:"POST",body:JSON.stringify({task_ids:taskIds,base:"main"})
      });
      setSwarmIntegration({...result,task_ids:taskIds});
      setSwarmIntegrationPushed(false);
      setNotice("Advanced orchestration integration worktree created");
      await load();
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function runSwarmChecks(){
    if(!swarmBoard||!swarmCheckCommand.trim())return;
    setBusy(true);
    try{
      const result=await request<{passed:boolean;output:string;command:string}>(`/swarms/${swarmBoard.swarm.id}/integration/checks`,{
        method:"POST",body:JSON.stringify({command:swarmCheckCommand.trim()})
      });
      setSwarmIntegration(current=>current?{...current,check_status:result.passed?"passed":"failed",check_output:result.output}:current);
      setNotice(result.passed?"Combined Advanced orchestration checks passed":"Combined Advanced orchestration checks failed");
      await load();
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function resumeRecoveryAgent(agent:SwarmAgent){
    const recovery=agent.recovery;
    if(!recovery?.can_resume)return;
    setBusy(true);
    try{
      const result=await request<{run_id:number;prior_run_id:number;fresh_budget:number;worktree_path:string;worktree_branch:string;checkpoint_bytes:number}>(`/tasks/${agent.id}/resume`,{
        method:"POST",
        body:JSON.stringify({fresh_budget:recovery.resumed_budget})
      });
      setNotice(`Agent #${agent.id} resumed from run #${result.prior_run_id} with ${result.fresh_budget} fresh tool steps`);
      await Promise.all([load(), selectedSwarmAgentId===agent.id?refreshSelectedAgent(agent.id):Promise.resolve()]);
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function retryRecoveredDependants(taskId:number,fullChain:boolean){
    setBusy(true);
    try{
      const result=await request<{retried_task_ids:number[]}>(`/tasks/${taskId}/retry-dependants`,{
        method:"POST",body:JSON.stringify({full_chain:fullChain})
      });
      setNotice(result.retried_task_ids.length?`Retry queued for ${result.retried_task_ids.map(id=>"#"+id).join(", ")}`:"No dependency-blocked tasks needed retrying");
      await load();
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function decideBudgetRequest(requestItem:BudgetRequest,accepted:boolean,amount?:number){
    if(!swarmBoard)return;
    setBusy(true);
    try{
      await request(`/swarms/${swarmBoard.swarm.id}/budget-requests/${requestItem.id}/decision`,{
        method:"POST",
        body:JSON.stringify({accepted,amount:accepted?(amount||requestItem.requested_amount):null})
      });
      setNotice(
        accepted
          ? `${requestItem.scope==="coordinator"?"Coordinator":"Agent #"+requestItem.task_id} budget extended by ${amount||requestItem.requested_amount}`
          : `${requestItem.scope==="coordinator"?"Coordinator":"Agent #"+requestItem.task_id} budget extension declined`
      );
      await load();
      if(requestItem.task_id&&selectedSwarmAgentId===requestItem.task_id){
        await refreshSelectedAgent(requestItem.task_id);
      }
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function promoteSwarmIntegration(){
    if(!swarmBoard)return;
    setBusy(true);
    try{
      const result=await request<{status:string;promotion:{main_commit:string;main_path:string;integration_commit:string}}>(`/swarms/${swarmBoard.swarm.id}/integration/promote`,{
        method:"POST",body:JSON.stringify({target_branch:"main"})
      });
      setNotice(`Promoted to main at ${result.promotion.main_commit.slice(0,12)}`);
      await load();
      onCreated();
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function pushSwarmIntegration(){
    if(!swarmBoard)return;
    setBusy(true);
    try{
      const remote=swarmBoard.repository?.github_remote||swarmBoard.repository?.remotes?.[0]?.name;
      if(!remote){setNotice("No Git remote is configured; the verified integration branch remains local");return;}
      await request(`/swarms/${swarmBoard.swarm.id}/integration/push`,{method:"POST",body:JSON.stringify({remote})});
      setSwarmIntegrationPushed(true);
      setNotice(`Advanced orchestration integration branch pushed to ${remote}`);
      await load();
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function createSwarmPullRequest(){
    if(!swarmBoard)return;
    setBusy(true);
    try{
      const result=await request<{pull_request_number:number;url:string}>(`/swarms/${swarmBoard.swarm.id}/integration/pull-request`,{
        method:"POST",
        body:JSON.stringify({
          title:`Olladex Advanced orchestration #${swarmBoard.swarm.id}: ${swarmBoard.swarm.title}`,
          body:`Integrated and verified by Olladex Advanced orchestration #${swarmBoard.swarm.id}.`,
          base:"main"
        })
      });
      setNotice(`Final Advanced orchestration PR #${result.pull_request_number} created`);
      await load();
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function startSwarm(event:FormEvent){
    event.preventDefault();
    if(!swarmSkill?.enabled||!swarmProfileId||!swarmObjective.trim())return;
    setBusy(true); setNotice(""); setSwarmPreflight(null);
    try{
      const query=new URLSearchParams({
        profile_id:swarmProfileId,
        max_agents:String(swarmMaxAgents),
        max_concurrency:String(swarmConcurrency)
      });
      const readiness=await request<SwarmPreflight>(`/projects/${projectId}/swarms/preflight?${query.toString()}`);
      setSwarmPreflight(readiness);
      if(!readiness.ready){
        const failed=readiness.checks.filter(item=>!item.ok).map(item=>item.detail).join(" · ");
        setNotice("Advanced orchestration is not ready: "+failed);
        return;
      }
      const created=await request<{swarm:{id:number}}>(`/projects/${projectId}/swarms`,{
        method:"POST",
        body:JSON.stringify({
          objective:swarmObjective.trim(),
          title:swarmTitle.trim(),
          profile_id:Number(swarmProfileId),
          max_agents:swarmMaxAgents,
          max_concurrency:swarmConcurrency
        })
      });
      setSwarmObjective(""); setSwarmTitle("");
      setNotice("Advanced orchestration #"+created.swarm.id+" started");
      await load();
      onCreated();
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  async function refreshSelectedAgent(taskId=selectedSwarmAgentId){
    if(!taskId)return;
    const detail=await request<SwarmAgentDetail>(`/swarm-agents/${taskId}`);
    setSelectedSwarmAgent(detail);
  }

  async function decideAgentCommand(commandId:number,accepted:boolean){
    if(!selectedSwarmAgentId)return;
    setBusy(true);
    try{
      await request(`/commands/${commandId}/decision`,{
        method:"POST",body:JSON.stringify({accepted})
      });
      setNotice(accepted?"Command approved once":"Command declined");
      await Promise.all([refreshSelectedAgent(selectedSwarmAgentId),load()]);
      window.setTimeout(()=>{refreshSelectedAgent(selectedSwarmAgentId).catch(()=>{});load().catch(()=>{});},250);
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }

  useEffect(()=>{
    if(!selectedSwarmAgentId){setSelectedSwarmAgent(null);setAgentGuidance("");return;}
    let disposed=false;
    async function refresh(){
      try{
        const detail=await request<SwarmAgentDetail>(`/swarm-agents/${selectedSwarmAgentId}`);
        if(!disposed)setSelectedSwarmAgent(detail);
      }catch(error){if(!disposed)setNotice(error instanceof Error?error.message:String(error));}
    }
    refresh();
    const timer=window.setInterval(refresh,1000);
    return()=>{disposed=true;window.clearInterval(timer);};
  },[selectedSwarmAgentId]);

  const roots=useMemo(()=>graph.nodes.filter(node=>!node.parent_task_id),[graph.nodes]);
  const byId=useMemo(()=>new Map(graph.nodes.map(node=>[node.id,node])),[graph.nodes]);
  const integrationChildren=useMemo(()=>selectedLead?graph.nodes.filter(node=>node.parent_task_id===selectedLead&&node.agent_role!=="reviewer"):[],[graph.nodes,selectedLead]);

  async function createLead(event:FormEvent){ event.preventDefault(); if(!leadDraft.objective.trim())return; setBusy(true);setNotice("");setLastPlan([]); try{ const created=await request<LeadResponse>(`/projects/${projectId}/orchestration/lead`,{method:"POST",body:JSON.stringify({objective:leadDraft.objective.trim(),title:leadDraft.title.trim(),max_tasks:leadDraft.maxTasks})}); setLastPlan(created.plan||[]);setLeadDraft({title:"",objective:"",maxTasks:6});setNotice(`Lead task created with ${created.plan.length} specialist tasks and a final reviewer`);await load();onCreated(); }catch(error){setNotice(error instanceof Error?error.message:String(error));}finally{setBusy(false);} }
  async function createTask(event:FormEvent){ event.preventDefault();if(!draft.prompt.trim())return;const dependencies=draft.dependencies.split(",").map(item=>Number(item.trim())).filter(item=>Number.isInteger(item)&&item>0);setBusy(true);setNotice("");try{await request(`/projects/${projectId}/orchestration/tasks`,{method:"POST",body:JSON.stringify({title:draft.title.trim(),prompt:draft.prompt.trim(),agent_role:draft.role.trim()||"worker",parent_task_id:draft.parent?Number(draft.parent):null,depends_on:dependencies})});setDraft({title:"",prompt:"",role:"worker",parent:"",dependencies:""});setNotice("Orchestrated task queued");await load();onCreated();}catch(error){setNotice(error instanceof Error?error.message:String(error));}finally{setBusy(false);} }
  async function loadReview(taskId:number){setBusy(true);setNotice("");try{setReview(await request<ReviewBundle>(`/tasks/${taskId}/review-bundle`));}catch(error){setNotice(error instanceof Error?error.message:String(error));}finally{setBusy(false);} }
  async function openIntegration(lead:Node){setSelectedLead(lead.id);setPreflight(null);setSelectedTasks([]);setPrTitle(`Integrate: ${lead.title}`);try{setIntegration(await request<IntegrationState>(`/tasks/${lead.id}/integration`));}catch{setIntegration(null);} }
  function toggleIntegrationTask(id:number){setSelectedTasks(current=>current.includes(id)?current.filter(item=>item!==id):[...current,id]);}
  async function preflightIntegration(){if(!selectedLead||!selectedTasks.length)return;setBusy(true);setNotice("");try{const result=await request<IntegrationPreflight>(`/tasks/${selectedLead}/integration/preflight`,{method:"POST",body:JSON.stringify({task_ids:selectedTasks,base:"main"})});setPreflight(result);setNotice(result.overlaps.length?`${result.overlaps.length} overlapping file(s) need review`:"No file overlaps detected");}catch(error){setNotice(error instanceof Error?error.message:String(error));}finally{setBusy(false);} }
  async function createIntegration(){if(!selectedLead||!selectedTasks.length)return;setBusy(true);setNotice("");try{const result=await request<IntegrationState>(`/tasks/${selectedLead}/integration`,{method:"POST",body:JSON.stringify({task_ids:selectedTasks,base:"main"})});setIntegration(result);setNotice(`Created ${result.branch}`);}catch(error){setNotice(error instanceof Error?error.message:String(error));}finally{setBusy(false);} }
  async function runChecks(){if(!selectedLead||!checkCommand.trim())return;setBusy(true);setNotice("");try{const result=await request<{passed:boolean;output:string;command:string}>(`/tasks/${selectedLead}/integration/checks`,{method:"POST",body:JSON.stringify({command:checkCommand.trim()})});setIntegration(current=>current?{...current,check_command:result.command,check_status:result.passed?"passed":"failed",check_output:result.output}:current);setNotice(result.passed?"Combined checks passed":"Combined checks failed");}catch(error){setNotice(error instanceof Error?error.message:String(error));}finally{setBusy(false);} }
  async function pushIntegration(){if(!selectedLead)return;setBusy(true);setNotice("");try{const result=await request<{branch:string}>(`/tasks/${selectedLead}/integration/push`,{method:"POST",body:JSON.stringify({remote:"origin"})});setNotice(`Pushed ${result.branch}`);}catch(error){setNotice(error instanceof Error?error.message:String(error));}finally{setBusy(false);} }
  async function createIntegrationPr(){if(!selectedLead||!prTitle.trim())return;setBusy(true);setNotice("");try{const result=await request<{url:string;pull_request_number:number}>(`/tasks/${selectedLead}/integration/pull-request`,{method:"POST",body:JSON.stringify({title:prTitle.trim(),body:prBody,base:"main"})});setIntegration(current=>current?{...current,pull_request_number:result.pull_request_number,pull_request_url:result.url,pull_request_state:"OPEN"}:current);setNotice(`Final integration PR #${result.pull_request_number} created`);}catch(error){setNotice(error instanceof Error?error.message:String(error));}finally{setBusy(false);} }

  function statusClass(status:string){return status==="completed"?styles.statusCompleted:status==="running"||status==="coordinating"?styles.statusRunning:status==="failed"?styles.statusFailed:"";}
  function renderRoot(node:Node){const children=node.children.map(id=>byId.get(id)).filter(Boolean) as Node[];return <article key={node.id} className={styles.root}><div className={styles.rootHead}><div className={styles.rootTitle}><strong>#{node.id} {node.title}</strong><div className={styles.meta}><span className={`${styles.chip} ${statusClass(node.status)}`}>{node.status}</span><span className={styles.chip}>{node.agent_role}</span>{node.worktree_branch&&<span className={styles.chip}>{node.worktree_branch}</span>}{node.pr_number>0&&<span className={styles.chip}>PR #{node.pr_number} {node.pr_state||""}</span>}</div></div><div className={styles.rootActions}><button type="button" disabled={busy} onClick={()=>loadReview(node.id)}>Review</button>{node.agent_role==="lead"&&<button type="button" className="primary" disabled={busy} onClick={()=>openIntegration(node)}>Integrate</button>}</div></div>{children.length>0&&<div className={styles.children}>{children.map(child=><div key={child.id} className={styles.child}><div><strong>#{child.id} {child.title}</strong><small>{child.agent_role}{child.depends_on.length?` · after ${child.depends_on.map(id=>`#${id}`).join(", ")}`:""}{child.worktree_branch?` · ${child.worktree_branch}`:""}</small>{child.error&&<small>{child.error}</small>}</div><span className={`${styles.childStatus} ${statusClass(child.status)}`}>{child.status}</span></div>)}</div>}{node.agent_role==="lead"&&node.result&&<details className={styles.result}><summary>Lead consolidation result</summary><MarkdownBody value={node.result} /></details>}</article>;}

  const activeAgents=graph.nodes.filter(node=>["running","coordinating","queued"].includes(node.status));
  const completedAgents=graph.nodes.filter(node=>node.status==="completed");
  const boardAgents=swarmBoard?.swarm.agents||[];
  const boardTotal=swarmBoard?swarmBoard.summary.total_agents:graph.nodes.length;
  const boardActive=swarmBoard?swarmBoard.summary.active_agents:activeAgents.length;
  const boardCompleted=swarmBoard?swarmBoard.summary.completed_agents:completedAgents.length;
  const approvalAgents=boardAgents.filter(agent=>agent.run_status==="waiting_for_approval"&&agent.pending_approval);
  const recoveryBlockers=swarmBoard?.summary.recovery_blockers||[];
  const dependencyBlocked=recoveryBlockers.filter(item=>item.status==="dependency_failed");
  const resumableAgents=boardAgents.filter(agent=>agent.recovery?.can_resume);
  const recoveredRoots=Array.from(new Set(dependencyBlocked.flatMap(item=>item.blocking_dependency_ids||[]))).filter(id=>boardAgents.some(agent=>agent.id===id&&agent.status==="completed"));

  return <section className={styles.panel}>
    <section className="agent-board-shell">
      <div><p className="eyebrow">Advanced orchestration</p><h3>{swarmBoard?swarmBoard.swarm.title:"Agent board"}</h3><p>{swarmBoard?`Advanced orchestration #${swarmBoard.swarm.id} · ${swarmBoard.swarm.status.replaceAll("_"," ")} · ${swarmBoard.summary.progress}% ${swarmBoard.swarm.status==="completed"?"complete":"agent work"}`:"Normal tasks stay simple. Expand this view when you want to inspect specialist agents, roles and execution state."}</p>{swarmRuns.length>1&&<label className="agent-board-run-select">Run<select value={selectedSwarmId||""} onChange={event=>{swarmCursors.current={event:0,coordinator_event:0,blackboard:0};setSelectedSwarmAgentId(null);setSwarmIntegration(null);setSelectedSwarmId(Number(event.target.value));}}>{swarmRuns.map(run=><option key={run.id} value={run.id}>#{run.id} {run.title} · {run.status}</option>)}</select></label>}</div>
      <div className="agent-board-metrics"><span><strong>{boardTotal}</strong> agents</span><span><strong>{boardActive}</strong> active</span><span><strong>{boardCompleted}</strong> complete</span>{swarmBoard?.summary.integration_ready&&<span><strong>✓</strong> integrate</span>}</div>
      {approvalAgents.length>0&&<section className="advanced-approval-banner" aria-live="assertive"><strong>Command approval required</strong><div>{approvalAgents.map(agent=><button type="button" key={agent.id} onClick={()=>setSelectedSwarmAgentId(agent.id)}>Agent #{agent.id} needs command approval</button>)}</div></section>}
      {(swarmBoard?.budget_requests||[]).length>0&&<section className="advanced-budget-banner" aria-live="assertive"><strong>More budget requested</strong>{(swarmBoard?.budget_requests||[]).map(item=><article key={item.id}><div><b>{item.scope==="coordinator"?"Coordinator":`Agent #${item.task_id}`} needs more budget</b><small>{item.reason||"Additional budget is needed to continue."}</small></div><div className="advanced-budget-actions"><button type="button" onClick={()=>decideBudgetRequest(item,true,10)} disabled={busy}>+10</button><button type="button" onClick={()=>decideBudgetRequest(item,true,25)} disabled={busy}>+25</button><input aria-label={`Custom budget for request ${item.id}`} type="number" min="1" max="200" value={budgetGrantAmounts[item.id]??String(item.requested_amount||10)} onChange={event=>setBudgetGrantAmounts(current=>({...current,[item.id]:event.target.value}))}/><button type="button" onClick={()=>decideBudgetRequest(item,true,Number(budgetGrantAmounts[item.id]||item.requested_amount||10))} disabled={busy}>Grant custom</button><button type="button" onClick={()=>decideBudgetRequest(item,false)} disabled={busy}>Decline</button>{item.task_id&&<button type="button" onClick={()=>setSelectedSwarmAgentId(Number(item.task_id))}>Open agent</button>}</div></article>)}</section>}
      {swarmBoard?.summary.recovery_available&&<section className="advanced-recovery-banner" aria-live="polite"><header><div><strong>Recovery available</strong><small>Completed sibling work is preserved. Integration stays unavailable until recovery blockers are resolved.</small></div></header>{resumableAgents.map(agent=><article key={agent.id}><div><b>Agent #{agent.id} · {agent.status.replaceAll("_"," ")}</b><small>Checkpoint {agent.recovery?.checkpoint_bytes||0} bytes · prior budget {agent.recovery?.previous_budget||0} · new budget {agent.recovery?.resumed_budget||0}</small><small>{agent.recovery?.worktree_branch} · {agent.recovery?.worktree_path}</small></div><div><button type="button" className="primary" onClick={()=>resumeRecoveryAgent(agent)} disabled={busy}>Resume from checkpoint</button><button type="button" onClick={()=>setSelectedSwarmAgentId(agent.id)}>Review saved work</button>{agent.session_id&&onOpenConversation&&<button type="button" onClick={()=>onOpenConversation(agent.session_id!)}>Open conversation</button>}</div></article>)}{dependencyBlocked.map(item=><article key={item.task_id}><div><b>Agent #{item.task_id} blocked by dependency</b><small>Waiting for {(item.blocking_dependency_ids||[]).map(id=>"#"+id).join(", ")}</small></div></article>)}{recoveredRoots.length>0&&<div className="advanced-recovery-actions">{recoveredRoots.map(id=><span key={id}><button type="button" onClick={()=>retryRecoveredDependants(id,false)} disabled={busy}>Retry blocked dependants after #{id}</button><button type="button" onClick={()=>retryRecoveredDependants(id,true)} disabled={busy}>Retry full dependency chain</button></span>)}</div>}{(swarmBoard.summary.integration_blockers||[]).length>0&&<small className="recovery-integration-blocker">Integration unavailable: {(swarmBoard.summary.integration_blockers||[]).join("; ")}</small>}</section>}
      {swarmBoard&&<>
        <article className="agent-board-coordinator"><span className={`agent-dot ${swarmBoard.swarm.status}`}>●</span><div><strong>Coordinator</strong><small>budget {swarmBoard.swarm.coordinator_budget?.used||0}/{swarmBoard.swarm.coordinator_budget?.budget||0} · {swarmBoard.swarm.coordinator_activity?.content||"Monitoring specialist progress and dependencies"}</small></div><div className="agent-board-control-actions">{swarmBoard.swarm.status==="paused"?<button type="button" onClick={()=>swarmAction("resume")} disabled={busy}>Resume</button>:["running","reviewing","waiting"].includes(swarmBoard.swarm.status)&&<button type="button" onClick={()=>swarmAction("pause")} disabled={busy}>Pause</button>}{!["completed","failed","cancelled"].includes(swarmBoard.swarm.status)&&<button type="button" onClick={()=>swarmAction("stop")} disabled={busy}>Stop</button>}</div></article>
        {!["completed","failed","cancelled"].includes(swarmBoard.swarm.status)&&<form className="agent-board-guidance" onSubmit={event=>{event.preventDefault();sendSwarmGuidance(false);}}><input value={swarmGuidance} onChange={event=>setSwarmGuidance(event.target.value)} placeholder="Guide Advanced orchestration…"/><button disabled={busy||!swarmGuidance.trim()}>Coordinator</button><button type="button" onClick={()=>sendSwarmGuidance(true)} disabled={busy||!swarmGuidance.trim()}>Apply to all</button></form>}
      </>}
      <div className="agent-board-preview">{swarmBoard&&boardAgents.length?boardAgents.slice(0,8).map(agent=><article key={agent.id} role="button" tabIndex={0} onClick={()=>setSelectedSwarmAgentId(agent.id)} onKeyDown={event=>{if(event.key==="Enter")setSelectedSwarmAgentId(agent.id);}}><span className={`agent-dot ${agent.status}`}>●</span><div><strong>{agent.title}</strong><small>{agent.agent_role} · {agent.status.replaceAll("_"," ")}{typeof agent.progress==="number"?` · ${agent.progress}%`:""}{agent.tool_budget?` · tools ${agent.tool_usage||0}/${agent.tool_budget}`:""}</small>{agent.pending_approval&&<button type="button" className="agent-approval-link" onClick={event=>{event.stopPropagation();setSelectedSwarmAgentId(agent.id);}}>Agent #{agent.id} needs command approval</button>}{agent.recovery?.can_resume&&<button type="button" className="agent-recovery-link" onClick={event=>{event.stopPropagation();resumeRecoveryAgent(agent);}} disabled={busy}>Resume from checkpoint</button>}{agent.status==="dependency_failed"&&<small>Waiting for {(agent.blocking_dependency_ids||[]).map(id=>"#"+id).join(", ")}</small>}{agent.current_activity&&<small>{agent.current_activity}</small>}{agent.latest_insight&&<div className="agent-card-markdown"><b>{agent.latest_insight.category}</b><MarkdownBody value={agent.latest_insight.content} compact /></div>}</div></article>):graph.nodes.length?graph.nodes.slice(0,8).map(node=><article key={node.id}><span className={`agent-dot ${node.status}`}>●</span><div><strong>{node.title}</strong><small>{node.agent_role} · {node.status.replaceAll("_"," ")}</small></div></article>):<p>No specialist agents yet. Advanced orchestration tasks will appear here through the same board.</p>}</div>
      {selectedSwarmAgent&&<section className="agent-board-detail">
        <header><div><p className="eyebrow">Advanced orchestration agent #{selectedSwarmAgent.task.id}</p><h4>{selectedSwarmAgent.task.title}</h4><small>{selectedSwarmAgent.task.agent_role} · {(selectedSwarmAgent.run?.status||selectedSwarmAgent.task.status).replaceAll("_"," ")}</small></div><div className="agent-board-control-actions">{selectedSwarmAgent.run?.session_id&&onOpenConversation&&<button type="button" onClick={()=>onOpenConversation(selectedSwarmAgent.run!.session_id)}>Open conversation</button>}{["queued","running","waiting_for_input","waiting_for_approval"].includes(selectedSwarmAgent.task.status)&&<button type="button" onClick={stopSwarmAgent} disabled={busy}>Stop agent</button>}<button type="button" onClick={()=>setSelectedSwarmAgentId(null)}>Close</button></div></header>
        {(selectedSwarmAgent.active_pending_commands||[]).length>0&&selectedSwarmAgent.run?.status==="waiting_for_approval"&&<section className="agent-pending-approvals"><strong>Command approval required</strong>{(selectedSwarmAgent.active_pending_commands||[]).map(command=><article key={command.id}><code>{command.command}</code><small>Working directory: {command.cwd}</small><div><button type="button" className="primary" onClick={()=>decideAgentCommand(command.id,true)} disabled={busy}>Approve once</button><button type="button" onClick={()=>decideAgentCommand(command.id,false)} disabled={busy}>Decline</button></div></article>)}</section>}
        {selectedSwarmAgent.task.recovery?.can_resume&&<section className="agent-recovery-detail"><strong>Recovery checkpoint available</strong><small>Stopped: {selectedSwarmAgent.task.recovery.prior_run_status.replaceAll("_"," ")} · source run #{selectedSwarmAgent.task.recovery.prior_run_id}</small><small>Checkpoint: {selectedSwarmAgent.task.recovery.checkpoint_bytes} bytes · recovery attempt {selectedSwarmAgent.task.recovery.recovery_attempt}/{selectedSwarmAgent.task.recovery.max_recovery_attempts}</small><small>Budget: previous {selectedSwarmAgent.task.recovery.previous_budget} · fresh {selectedSwarmAgent.task.recovery.resumed_budget}</small><code>{selectedSwarmAgent.task.recovery.worktree_branch}</code><code>{selectedSwarmAgent.task.recovery.worktree_path}</code><div><button type="button" className="primary" onClick={()=>resumeRecoveryAgent(selectedSwarmAgent.task)} disabled={busy}>Resume from checkpoint</button></div></section>}
        <div className="agent-board-detail-grid">
          <article><strong>Activity</strong><p>{selectedSwarmAgent.task.current_activity||"No current activity"}</p><small>{selectedSwarmAgent.task.progress||0}% · tools {selectedSwarmAgent.task.tool_usage||0}/{selectedSwarmAgent.task.tool_budget||0}</small></article>
          <article><strong>Changed files</strong>{selectedSwarmAgent.changed_files.length?<ul>{selectedSwarmAgent.changed_files.map(path=><li key={path}>{path}</li>)}</ul>:<p>No committed branch changes yet.</p>}</article>
          <article><strong>Commands</strong>{selectedSwarmAgent.commands.length?<ul>{selectedSwarmAgent.commands.slice(0,8).map(command=><li key={command.id}><code>{command.command}</code> · {command.status} · exit {command.exit_code}</li>)}</ul>:<p>No commands recorded.</p>}</article>
          {selectedSwarmAgent.task.task_kind==="reviewer"&&<article><strong>Final reviewer report</strong>{selectedSwarmAgent.task.result?.trim()?<MarkdownBody value={selectedSwarmAgent.task.result}/>:<p>No substantive reviewer report was produced.</p>}</article>}
          <article><strong>Findings</strong>{selectedSwarmAgent.blackboard.length?<div className="agent-markdown-list">{selectedSwarmAgent.blackboard.slice().reverse().slice(0,8).map(item=><section key={item.id}><b>{item.category}</b><MarkdownBody value={item.content} compact /></section>)}</div>:<p>No task-specific Blackboard entries yet.</p>}</article>
        </div>
        {["running","waiting_for_input","waiting_for_approval"].includes(selectedSwarmAgent.task.status)&&<form className="agent-board-agent-guidance" onSubmit={event=>{event.preventDefault();sendAgentGuidance();}}><input value={agentGuidance} onChange={event=>setAgentGuidance(event.target.value)} placeholder="Guide this agent…"/><button disabled={busy||!agentGuidance.trim()}>Send guidance</button></form>}
      </section>}
      {swarmBoard&&<div className="agent-board-observability">
        <details><summary>Coordinator timeline · {swarmBoard.coordinator_events?.length||0}</summary><div>{swarmBoard.coordinator_events?.length?swarmBoard.coordinator_events.slice().reverse().slice(0,12).map(item=><article key={item.id}><b>{item.kind.replaceAll("_"," ")}</b><MarkdownBody value={coordinatorPayloadText(item.payload)} compact /></article>):<p>No Coordinator events yet.</p>}</div></details>
        <details><summary>Blackboard · {swarmBoard.blackboard?.length||0}</summary><div>{swarmBoard.blackboard?.length?swarmBoard.blackboard.slice().reverse().slice(0,12).map(item=><article key={item.id}><b>{item.category}</b><MarkdownBody value={item.content} compact />{item.task_id?<small>Agent #{item.task_id}</small>:<small>Coordinator</small>}</article>):<p>No shared knowledge yet.</p>}</div></details>
      </div>}
      {swarmBoard&&(swarmBoard.summary.integration_ready||swarmIntegration)&&<section className="agent-board-integration">
        <header><div><p className="eyebrow">Advanced orchestration integration</p><h4>{swarmIntegration?.branch||"Completed specialist branches are ready"}</h4></div><div className="agent-board-control-actions"><button type="button" onClick={checkSwarmIntegration} disabled={busy}>Check overlaps</button>{!swarmBoard.swarm.integration_branch&&<button type="button" className="primary" onClick={buildSwarmIntegration} disabled={busy}>Build integration</button>}</div></header>
        {swarmBoard.locations&&<div className="swarm-workspace-locations">
          <article><strong>Main project directory</strong><code>{swarmBoard.locations.main}</code><small>{swarmBoard.swarm.status==="completed"&&swarmBoard.swarm.promoted_commit?`Promoted · ${swarmBoard.swarm.promoted_commit.slice(0,12)}`:"Target worktree"}</small></article>
          <article><strong>Integration worktree</strong><code>{swarmBoard.locations.integration||"Not prepared yet"}</code><small>{swarmBoard.swarm.integration_branch||"No integration branch"}</small></article>
          <article><strong>Specialist worktrees</strong><div>{swarmBoard.locations.specialists.length?swarmBoard.locations.specialists.map(item=><small key={item.task_id}>#{item.task_id} {item.branch} · {item.path}</small>):<small>No specialist worktrees</small>}</div></article>
        </div>}
        {swarmBoard.swarm.integration_branch&&swarmBoard.swarm.status!=="completed"&&<div className="integration-warning"><strong>Not yet in main</strong><span>Work is committed on {swarmBoard.swarm.integration_branch} but has not yet been promoted to main.</span></div>}
        {swarmIntegration?.overlaps?.length?<div className="integration-warning"><strong>{swarmIntegration.overlaps.length} overlap(s)</strong><span>{swarmIntegration.overlaps.map(item=>item.path).join(", ")}</span></div>:swarmIntegration&&<div className="integration-ok">No overlapping files detected.</div>}
        {swarmIntegration?.branch&&<div className="agent-board-integration-actions"><label>Combined checks<input value={swarmCheckCommand} onChange={event=>setSwarmCheckCommand(event.target.value)}/></label><button type="button" onClick={runSwarmChecks} disabled={busy||!swarmCheckCommand.trim()}>Run checks</button><span>{swarmIntegration.check_status||"not tested"}</span>
          {swarmBoard.swarm.status==="ready_to_promote"&&<button type="button" className="primary" onClick={promoteSwarmIntegration} disabled={busy}>Promote to main</button>}
          {swarmBoard.swarm.status==="ready_to_promote"&&!swarmBoard.repository?.has_remote&&<span>Verified local integration branch ready</span>}
          {swarmBoard.swarm.status==="ready_to_promote"&&swarmBoard.repository?.has_remote&&!swarmIntegrationPushed&&<button type="button" onClick={pushSwarmIntegration} disabled={busy}>Push branch</button>}
          {swarmBoard.swarm.status==="ready_to_promote"&&swarmIntegrationPushed&&swarmBoard.repository?.can_create_pull_request&&!swarmBoard.swarm.integration_pr_number&&<button type="button" onClick={createSwarmPullRequest} disabled={busy}>Create final PR</button>}
          {swarmIntegration.check_status==="passed"&&swarmIntegrationPushed&&!swarmBoard.repository?.can_create_pull_request&&<span>Remote branch pushed · GitHub PR not available</span>}
          {swarmBoard.swarm.integration_pr_number?<span>PR #{swarmBoard.swarm.integration_pr_number} {swarmBoard.swarm.integration_pr_state||""}</span>:null}
        </div>}
        {swarmIntegration?.check_output&&<details><summary>Combined check output</summary><pre>{swarmIntegration.check_output}</pre></details>}
      </section>}
    </section>
    <details className={styles.advanced}>
      <summary>Advanced orchestration controls · {swarmSkill?.enabled?"enabled":"disabled"}</summary>
      <div className={styles.advancedForm}>
        <div className={styles.actions}><button type="button" onClick={toggleSwarmSkill} disabled={busy||!swarmSkill}>{swarmSkill?.enabled?"Disable Advanced orchestration":"Enable Advanced orchestration"}</button></div>
        {swarmSkill?.enabled&&<>
          <form onSubmit={startSwarm} className={styles.advancedForm}>
            <label>Preset<select value={swarmProfileId} onChange={event=>{const id=event.target.value;setSwarmProfileId(id);const profile=swarmProfiles.find(item=>String(item.id)===id);if(profile){setSwarmMaxAgents(profile.max_agents);setSwarmConcurrency(profile.max_concurrency);}}}>{swarmProfiles.map(profile=><option key={profile.id} value={profile.id}>{profile.name}</option>)}</select></label>
            <label>Maximum agents<input type="number" min="2" max="20" value={swarmMaxAgents} onChange={event=>setSwarmMaxAgents(Number(event.target.value))}/></label>
            <label>Concurrency<input type="number" min="1" max="8" value={swarmConcurrency} onChange={event=>setSwarmConcurrency(Number(event.target.value))}/></label>
            <label>Title<input value={swarmTitle} onChange={event=>setSwarmTitle(event.target.value)} placeholder="Optional orchestration title"/></label>
            <label className={styles.advancedPrompt}>Objective<textarea value={swarmObjective} onChange={event=>setSwarmObjective(event.target.value)} placeholder="Describe the larger outcome for Advanced orchestration…"/></label>
            <button className="primary" disabled={busy||!swarmProfileId||!swarmObjective.trim()}>{busy?"Checking…":"Preflight & start Advanced orchestration"}</button>
            {swarmPreflight&&<>
              <small>{swarmPreflight.ready?"Readiness checks passed":swarmPreflight.checks.filter(item=>!item.ok).map(item=>item.detail).join(" · ")}</small>
              {(!swarmPreflight.git.repository||!swarmPreflight.git.has_head)&&<div className="swarm-local-git"><strong>Local Git required for Advanced orchestration worktrees</strong><span>Olladex can initialise Git locally and create a baseline commit of non-ignored files. No GitHub account or remote is required.</span><button type="button" onClick={initializeSwarmGit} disabled={busy}>Initialize local Git</button></div>}
              {swarmPreflight.git.repository&&swarmPreflight.git.has_head&&!swarmPreflight.git.has_remote&&<small>Local-only Git repository · Advanced orchestration can run normally; final results will remain on a verified local integration branch.</small>}
            </>}
          </form>
          {swarmProfiles.find(item=>String(item.id)===swarmProfileId)&&(()=>{const profile=swarmProfiles.find(item=>String(item.id)===swarmProfileId)!;const roles=["backend","frontend","coder","tester","researcher","reviewer","challenger"];return <details className="swarm-profile-settings"><summary>Model & policy settings</summary><div className="swarm-profile-grid">
            <label>Coordinator<select value={profile.coordinator_profile_id||""} onChange={event=>updateSwarmProfile(profile.id,{coordinator_profile_id:event.target.value?Number(event.target.value):null})}><option value="">Project default</option>{modelProfiles.map(model=><option key={model.id} value={model.id}>{model.name} · {model.chat_model}</option>)}</select></label>
            <label>Default worker<select value={profile.default_worker_profile_id||""} onChange={event=>updateSwarmProfile(profile.id,{default_worker_profile_id:event.target.value?Number(event.target.value):null})}><option value="">Project default</option>{modelProfiles.map(model=><option key={model.id} value={model.id}>{model.name} · {model.chat_model}</option>)}</select></label>
            {roles.map(role=><label key={role}>{role}<select value={(profile.role_profiles||{})[role]||""} onChange={event=>updateRoleProfile(profile,role,event.target.value?Number(event.target.value):null)}><option value="">Default worker</option>{modelProfiles.map(model=><option key={model.id} value={model.id}>{model.name} · {model.chat_model}</option>)}</select></label>)}
            <label>Worker tool budget<input type="number" min="1" max="200" value={profile.agent_tool_budget} onChange={event=>updateSwarmProfile(profile.id,{agent_tool_budget:Number(event.target.value)})}/></label>
            <label>Coordinator budget<input type="number" min="1" max="200" value={profile.coordinator_tool_budget} onChange={event=>updateSwarmProfile(profile.id,{coordinator_tool_budget:Number(event.target.value)})}/></label>
            <label>Resumed task budget<input type="number" min="1" max="200" value={profile.resumed_task_tool_budget||20} onChange={event=>updateSwarmProfile(profile.id,{resumed_task_tool_budget:Number(event.target.value)})}/></label>
            <label>Maximum recovery attempts<input type="number" min="1" max="10" value={profile.max_recovery_attempts||2} onChange={event=>updateSwarmProfile(profile.id,{max_recovery_attempts:Number(event.target.value)})}/></label>
            <label className="swarm-check"><input type="checkbox" checked={Boolean(profile.dynamic_size)} onChange={event=>updateSwarmProfile(profile.id,{dynamic_size:event.target.checked?1:0})}/> Dynamic size</label>
            <label className="swarm-check"><input type="checkbox" checked={Boolean(profile.require_reviewer)} onChange={event=>updateSwarmProfile(profile.id,{require_reviewer:event.target.checked?1:0})}/> Final reviewer</label>
            <label className="swarm-check"><input type="checkbox" checked={Boolean(profile.require_challenger)} onChange={event=>updateSwarmProfile(profile.id,{require_challenger:event.target.checked?1:0})}/> Challenger</label>
            <div className={styles.actions}><button type="button" onClick={()=>saveSwarmProfile(profile)} disabled={busy}>Save Advanced orchestration settings</button><button type="button" onClick={testSwarmModels} disabled={busy}>Test local models</button></div>
            {swarmSelfTest&&<div className="swarm-model-test-results">{swarmSelfTest.models.map(item=><article key={item.model} className={item.ok?"ok":"failed"}><strong>{item.model}</strong><span>{item.ok?"ready":"failed"} · {item.latency_ms} ms</span><small>{item.roles.join(", ")}</small>{!item.ok&&<small>{item.error||item.response||"Unexpected model response"}</small>}</article>)}</div>}
          </div></details>})()}
        </>}
      </div>
    </details>
    <div className={styles.hero}><div><p className="eyebrow">Advanced orchestration</p><h3>Coordinate larger work</h3><p>Start with one objective. Olladex breaks it into specialist tasks, waits for dependencies, then gives you a review and integration path.</p></div><span className={styles.count}>{graph.nodes.length} tasks</span></div>

    <section className={styles.stage}>
      <div className={styles.stageHead}><span className={styles.stageNo}>1</span><div><strong>Start work</strong><small>Describe the outcome you want. Olladex plans the specialists.</small></div></div>
      <form onSubmit={createLead} className={styles.leadForm}>
        <label>Title<input value={leadDraft.title} onChange={event=>setLeadDraft(current=>({...current,title:event.target.value}))} placeholder="Optional plan title" /></label>
        <label>Specialists<select value={leadDraft.maxTasks} onChange={event=>setLeadDraft(current=>({...current,maxTasks:Number(event.target.value)}))}>{[2,3,4,5,6,7,8,9,10].map(value=><option key={value} value={value}>{value}</option>)}</select></label>
        <label className={styles.objective}>Objective<textarea value={leadDraft.objective} onChange={event=>setLeadDraft(current=>({...current,objective:event.target.value}))} placeholder="Example: Add persistent application settings, update the UI, and cover it with tests." /></label>
        <div className={styles.leadActions}><button className="primary" disabled={busy||!leadDraft.objective.trim()}>{busy?"Planning…":"Start autonomous lead"}</button></div>
      </form>
      {lastPlan.length>0&&<details className={styles.plan} open><summary>Generated plan · {lastPlan.length} specialist tasks</summary><div className={styles.planList}>{lastPlan.map((item,index)=><div className={styles.planItem} key={`${index}-${item.title}`}><strong>{index+1}. {item.title}</strong><small>{item.role}{item.depends_on.length?` · after ${item.depends_on.map(dep=>dep+1).join(", ")}`:" · can start immediately"}</small><MarkdownBody value={item.prompt} compact /></div>)}</div></details>}
      <details className={styles.advanced}><summary>Advanced · add a specialist manually</summary><form onSubmit={createTask} className={styles.advancedForm}><label>Title<input value={draft.title} onChange={event=>setDraft(current=>({...current,title:event.target.value}))}/></label><label>Role<select value={draft.role} onChange={event=>setDraft(current=>({...current,role:event.target.value}))}><option value="worker">Worker</option><option value="frontend">Frontend</option><option value="backend">Backend</option><option value="researcher">Researcher</option><option value="reviewer">Reviewer</option><option value="tester">Tester</option></select></label><label>Parent<select value={draft.parent} onChange={event=>setDraft(current=>({...current,parent:event.target.value}))}><option value="">No parent</option>{graph.nodes.map(node=><option key={node.id} value={node.id}>#{node.id} {node.title}</option>)}</select></label><label>Depends on<input value={draft.dependencies} onChange={event=>setDraft(current=>({...current,dependencies:event.target.value}))} placeholder="12, 13"/></label><label className={styles.advancedPrompt}>Task prompt<textarea value={draft.prompt} onChange={event=>setDraft(current=>({...current,prompt:event.target.value}))}/></label><button className="primary" disabled={busy||!draft.prompt.trim()}>{busy?"Working…":"Queue specialist"}</button></form></details>
    </section>

    <section className={styles.stage}>
      <div className={styles.stageHead}><span className={styles.stageNo}>2</span><div><strong>Active plans</strong><small>Follow progress here. Open Review or Integrate only when you need the next action.</small></div></div>
      <div className={styles.roots}>{roots.length?roots.map(renderRoot):<div className={styles.empty}>No orchestration plans yet. Start with an objective above.</div>}</div>
    </section>

    {(selectedLead||review)&&<section className={styles.stage}><div className={styles.stageHead}><span className={styles.stageNo}>3</span><div><strong>Review & integrate</strong><small>Combine completed specialist branches, validate once, then create the final PR.</small></div></div>
      {selectedLead&&<div className={styles.integrationBody}><div className={styles.taskSelect}>{integrationChildren.map(node=><label key={node.id}><input type="checkbox" checked={selectedTasks.includes(node.id)} disabled={node.status!=="completed"||!node.worktree_branch} onChange={()=>toggleIntegrationTask(node.id)}/><span>#{node.id} {node.title} · {node.status}</span></label>)}</div><div className={styles.actions}><button type="button" disabled={busy||!selectedTasks.length} onClick={preflightIntegration}>Check overlaps</button><button type="button" className="primary" disabled={busy||!selectedTasks.length} onClick={createIntegration}>Build integration branch</button></div>{preflight&&<div className={styles.overlap}>{preflight.overlaps.length?`${preflight.overlaps.length} overlapping file(s): ${preflight.overlaps.map(item=>item.path).join(", ")}`:"No overlapping files detected."}</div>}{integration?.branch&&<><div><strong>{integration.branch}</strong></div>{integration.diff&&<pre>{integration.diff}</pre>}<label>Combined check command<input value={checkCommand} onChange={event=>setCheckCommand(event.target.value)}/></label><div className={styles.actions}><button type="button" disabled={busy||!checkCommand.trim()} onClick={runChecks}>Run checks</button><span className={`${styles.chip} ${integration.check_status==="passed"?styles.statusCompleted:integration.check_status==="failed"?styles.statusFailed:""}`}>{integration.check_status||"not tested"}</span></div>{integration.check_output&&<pre>{integration.check_output}</pre>}<label>Final PR title<input value={prTitle} onChange={event=>setPrTitle(event.target.value)}/></label><label>Final PR description<textarea value={prBody} onChange={event=>setPrBody(event.target.value)}/></label><div className={styles.actions}><button type="button" disabled={busy||integration.check_status!=="passed"} onClick={pushIntegration}>Push integration</button><button type="button" className="primary" disabled={busy||integration.check_status!=="passed"||!prTitle.trim()} onClick={createIntegrationPr}>Create final PR</button>{integration.pull_request_url&&<button type="button" onClick={()=>window.open(integration.pull_request_url,"_blank","noopener,noreferrer")}>Open PR #{integration.pull_request_number}</button>}</div></>}</div>}
      {review&&<details className={styles.review} open><summary>Review bundle · lead #{review.task_id} · {review.items.length} items</summary>{review.items.map(item=><article key={item.id}><header><strong>#{item.id} {item.title}</strong><small>{item.agent_role} · {item.status}</small></header>{item.result&&<MarkdownBody value={item.result} />}{item.error&&<p>{item.error}</p>}{item.branch?<pre>{item.branch.working_diff||item.branch.branch_diff||"No diff"}</pre>:<p>No worktree available.</p>}</article>)}</details>}
    </section>}

    {notice&&<div className={styles.notice}>{notice}</div>}
  </section>;
}


function coordinatorPayloadText(payload:Record<string,unknown>){
  for(const key of ["content","reason","status","title","purpose"]){
    const value=payload[key];
    if(typeof value==="string"&&value.trim())return value;
  }
  return "Coordinator event";
}


function mergeById<T extends {id:number}>(current:T[], incoming:T[], limit:number):T[]{
  const byId=new Map<number,T>();
  for(const item of current)byId.set(item.id,item);
  for(const item of incoming)byId.set(item.id,item);
  return Array.from(byId.values()).sort((a,b)=>a.id-b.id).slice(-limit);
}
