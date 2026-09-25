import { test, expect } from '@playwright/test';

test('swarm board can be opened and enabled for a project', async ({ page }) => {
  let swarmEnabled = false;
  const project = { id:1,name:'Demo',path:'/demo',model:'test',approval_mode:'assisted' };
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    const json = (data: unknown) => route.fulfill({ json: data });

    if (p === '/api/projects') return json([project]);
    if (p === '/api/status') return json({ version:'test',ollama:{connected:true,models:['test']} });
    if (p === '/api/projects/1/sessions') return json([{id:1,project_id:1,title:'Chat',updated_at:new Date().toISOString()}]);
    if (p === '/api/projects/1/skills/swarm') {
      if (route.request().method() === 'PUT') {
        swarmEnabled = Boolean(route.request().postDataJSON().enabled);
      }
      return json({project_id:1,skill:'swarm',enabled:swarmEnabled});
    }
    if (p === '/api/swarm-profiles') return json([{
      id:1,name:'Development',max_agents:5,max_concurrency:3,max_depth:1,dynamic_size:1,
      require_reviewer:1,require_challenger:0,role_profiles:{},agent_tool_budget:30,
      coordinator_tool_budget:20,is_builtin:1
    }]);
    if (p === '/api/model-profiles') return json([{id:1,name:'Local coder',chat_model:'test'}]);
    if (p === '/api/projects/1/swarms') return json([]);
    if (p.endsWith('/tree')) return json([]);
    if (p.endsWith('/changes')) return json([]);
    if (p.endsWith('/memory')) return json({content:''});
    if (p.endsWith('/git/diff')) return json({diff:''});
    if (p.endsWith('/git')) return json({changes:[],branches:[],remotes:[]});
    if (p.endsWith('/messages')) return json([]);
    return json([]);
  });

  await page.goto('/');
  await page.locator('.rail').getByRole('button', {name:/Swarm/}).click();
  await expect(page.getByRole('heading', {name:'Swarm', exact:true})).toBeVisible();
  await expect(page.getByRole('button', {name:'Enable Swarm'})).toBeVisible();

  await page.getByRole('button', {name:'Enable Swarm'}).click();
  await expect.poll(() => swarmEnabled).toBe(true);
  await expect(page.getByRole('button', {name:'Swarm enabled'})).toBeVisible();
  await expect(page.getByRole('button', {name:'Start swarm'})).toBeVisible();
  await expect(page.getByText('Role model settings')).toBeVisible();
});


test('swarm board shows coordinator timeline and advances incremental polling cursor', async ({ page }) => {
  const project = { id:1,name:'Demo',path:'/demo',model:'test',approval_mode:'assisted' };
  const coordinatorAfter: string[] = [];
  const agentAfter: string[] = [];
  const run = {
    id:7,project_id:1,title:'Auth hardening',objective:'Harden authentication',status:'reviewing',
    profile_id:1,max_agents:5,max_concurrency:3,total_agents_created:2,
    created_at:new Date().toISOString(),started_at:new Date().toISOString(),completed_at:'',
    coordinator_activity:{category:'decision',key:'pre-review-gate',content:'Coordinator opened final verification.',created_at:new Date().toISOString()},
    agents:[
      {id:11,title:'Inspect auth',status:'completed',agent_role:'backend',assigned_model:'test',task_kind:'backend',priority:100,progress:100,current_activity:'Done',depends_on:[],run_id:101,worktree_branch:'olladex/task-11',created_at:new Date().toISOString()},
      {id:12,title:'Final review',status:'queued',agent_role:'reviewer',assigned_model:'test',task_kind:'reviewer',priority:300,progress:0,current_activity:'',depends_on:[11],run_id:null,worktree_branch:'',created_at:new Date().toISOString()}
    ]
  };

  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    const json = (data: unknown) => route.fulfill({ json: data });

    if (p === '/api/projects') return json([project]);
    if (p === '/api/status') return json({ version:'test',ollama:{connected:true,models:['test']} });
    if (p === '/api/projects/1/sessions') return json([{id:1,project_id:1,title:'Chat',updated_at:new Date().toISOString()}]);
    if (p === '/api/projects/1/skills/swarm') return json({project_id:1,skill:'swarm',enabled:true});
    if (p === '/api/swarm-profiles') return json([{
      id:1,name:'Development',max_agents:5,max_concurrency:3,max_depth:1,dynamic_size:1,
      require_reviewer:1,require_challenger:0,role_profiles:{},agent_tool_budget:30,
      coordinator_tool_budget:20,is_builtin:1,coordinator_profile_id:1,default_worker_profile_id:1
    }]);
    if (p === '/api/model-profiles') return json([{id:1,name:'Local coder',chat_model:'test'}]);
    if (p === '/api/projects/1/swarms') return json([{...run,agents:undefined,agent_counts:{active:1,total:2}}]);
    if (p === '/api/swarms/7') return json(run);
    if (p === '/api/swarms/7/blackboard') return json([
      {id:1,task_id:null,category:'decision',key:'pre-review-gate',content:'Coordinator opened final verification.',confidence:null,created_at:new Date().toISOString()}
    ]);
    if (p === '/api/swarms/7/events') {
      const after=url.searchParams.get('after')||'0'; agentAfter.push(after);
      return json(after==='0'?[{id:9,run_id:101,task_id:11,task_title:'Inspect auth',agent_role:'backend',assigned_model:'test',kind:'status',payload:{status:'completed'},created_at:new Date().toISOString()}]:[]);
    }
    if (p === '/api/swarms/7/coordinator/events') {
      const after=url.searchParams.get('after')||'0'; coordinatorAfter.push(after);
      return json(after==='0'?[
        {id:20,swarm_id:7,kind:'status',payload:{status:'reviewing',previous:'running'},created_at:new Date().toISOString()},
        {id:21,swarm_id:7,kind:'decision',payload:{content:'Coordinator opened final verification.'},created_at:new Date().toISOString()}
      ]:[]);
    }
    if (p === '/api/swarm-agents/11') return json({
      task:run.agents[0],
      run:{id:101,status:'completed',created_at:new Date().toISOString(),updated_at:new Date().toISOString()},
      commands:[{id:1,command:'pytest backend/tests/test_auth.py',output:'12 passed',exit_code:0,status:'completed',cwd:'/demo',created_at:new Date().toISOString(),updated_at:new Date().toISOString()}],
      blackboard:[{id:2,task_id:11,category:'finding',key:'auth',content:'Auth dependency is centralized.',confidence:null,created_at:new Date().toISOString()}],
      changed_files:['backend/app/auth.py'],
      worktree:{path:'/tmp/task-11',branch:'olladex/task-11',branch_diff:'diff --git a/backend/app/auth.py b/backend/app/auth.py',working_diff:'',changes:[]}
    });
    if (p.endsWith('/tree')) return json([]);
    if (p.endsWith('/changes')) return json([]);
    if (p.endsWith('/memory')) return json({content:''});
    if (p.endsWith('/git/diff')) return json({diff:''});
    if (p.endsWith('/git')) return json({changes:[],branches:[],remotes:[]});
    if (p.endsWith('/messages')) return json([]);
    return json([]);
  });

  await page.goto('/');
  await page.locator('.rail').getByRole('button', {name:/Swarm/}).click();

  await expect(page.getByRole('heading', {name:'Auth hardening'})).toBeVisible();
  await expect(page.getByText('Coordinator opened final verification.').first()).toBeVisible();
  await page.getByText(/Coordinator timeline · 2 events/).click();
  await expect(page.getByText('reviewing', {exact:true}).first()).toBeVisible();

  await expect.poll(() => coordinatorAfter.includes('21'), {timeout:5000}).toBe(true);
  await expect.poll(() => agentAfter.includes('9'), {timeout:5000}).toBe(true);

  await page.getByRole('button', {name:'Open agent'}).first().click();
  await expect(page.getByRole('heading', {name:'Changed files'})).toBeVisible();
  await expect(page.getByText('backend/app/auth.py')).toBeVisible();
  await expect(page.getByRole('heading', {name:'Commands'})).toBeVisible();
  await expect(page.getByText('pytest backend/tests/test_auth.py')).toBeVisible();
  await expect(page.getByRole('heading', {name:'Findings & hand-offs'})).toBeVisible();
  await expect(page.getByText('Auth dependency is centralized.')).toBeVisible();
});
