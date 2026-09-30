import { test, expect } from '@playwright/test';

const project = { id:1,name:'Demo',path:'/demo',model:'test',approval_mode:'assisted' };

function baseRoutes(page:any, extra:(route:any,url:URL)=>Promise<boolean>|boolean=()=>false) {
  return page.route('**/api/**', async (route:any) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    const json = (data: unknown) => route.fulfill({ json: data });
    if (await extra(route,url)) return;
    if (p === '/api/projects') return json([project]);
    if (p === '/api/status') return json({ version:'test',ollama:{connected:true,models:['test']} });
    if (p === '/api/projects/1/sessions') return json([{id:1,project_id:1,title:'Chat',updated_at:new Date().toISOString()}]);
    if (p === '/api/projects/1/orchestration') return json({project_id:1,nodes:[]});
    if (p === '/api/projects/1/swarms') return json([]);
    if (p === '/api/swarm-profiles') return json([{
      id:1,name:'Development',max_agents:5,max_concurrency:3,max_depth:1,dynamic_size:1,
      require_reviewer:1,require_challenger:0,role_profiles:{},agent_tool_budget:30,
      coordinator_tool_budget:20,is_builtin:1,coordinator_profile_id:null,default_worker_profile_id:null
    }]);
    if (p === '/api/model-profiles') return json([
      {id:1,name:'Fast coder',chat_model:'qwen2.5-coder:7b'},
      {id:2,name:'Reasoner',chat_model:'phi4:14b'}
    ]);
    if (p.endsWith('/tree')) return json([]);
    if (p.endsWith('/changes')) return json([]);
    if (p.endsWith('/memory')) return json({content:''});
    if (p.endsWith('/git/diff')) return json({diff:''});
    if (p.endsWith('/git')) return json({changes:[],branches:[],remotes:[]});
    if (p.endsWith('/messages')) return json([]);
    if (p.endsWith('/workspace')) return json(null);
    return json([]);
  });
}

test('interaction layer can enable, preflight and start a swarm', async ({ page }) => {
  let swarmEnabled = false;
  let createdObjective = '';
  let savedCoordinatorProfile: number | null = null;

  await baseRoutes(page, async (route,url) => {
    const p=url.pathname;
    const json=(data:unknown)=>route.fulfill({json:data});
    if (p === '/api/projects/1/skills/swarm') {
      if (route.request().method() === 'PUT') swarmEnabled = Boolean(route.request().postDataJSON().enabled);
      await json({project_id:1,skill:'swarm',enabled:swarmEnabled});
      return true;
    }
    if (p === '/api/swarm-profiles/1' && route.request().method() === 'PUT') {
      const body=route.request().postDataJSON();
      savedCoordinatorProfile=body.coordinator_profile_id;
      await json({...body,id:1,dynamic_size:body.dynamic_size?1:0,require_reviewer:body.require_reviewer?1:0,require_challenger:body.require_challenger?1:0});
      return true;
    }
    if (p === '/api/projects/1/swarms/self-test') {
      await json({
        ready:true,
        models:[
          {model:'phi4:14b',roles:['coordinator','reviewer'],ok:true,latency_ms:420,response:'OLLADEX_SWARM_OK'},
          {model:'qwen2.5-coder:7b',roles:['backend','tester'],ok:true,latency_ms:280,response:'OLLADEX_SWARM_OK'}
        ]
      });
      return true;
    }
    if (p === '/api/projects/1/swarms/preflight') {
      await json({ready:true,project_id:1,profile_id:1,max_agents:5,max_concurrency:3,checks:[
        {name:'sqlite_wal',ok:true,detail:'journal_mode=wal'},
        {name:'git_repository',ok:true,detail:'Git repository ready'},
        {name:'git_head',ok:true,detail:'Baseline commit available'},
        {name:'ollama_models',ok:true,detail:'test'}
      ],git:{repository:true,has_head:true,remotes:[],has_remote:false,github_remote:'',can_push:false,can_create_pull_request:false}});
      return true;
    }
    if (p === '/api/projects/1/swarms' && route.request().method() === 'POST') {
      createdObjective=String(route.request().postDataJSON().objective||'');
      await json({swarm:{id:7}});
      return true;
    }
    return false;
  });

  await page.goto('/');
  await page.locator('.rail').getByRole('button', {name:'Tasks'}).click();

  await expect(page.getByText('Agent board', {exact:true})).toBeVisible();
  await page.getByText(/Advanced orchestration controls/).click();
  await expect(page.getByRole('button', {name:'Enable Advanced orchestration'})).toBeVisible();

  await page.getByRole('button', {name:'Enable Advanced orchestration'}).click();
  await expect.poll(() => swarmEnabled).toBe(true);

  await page.getByText('Model & policy settings').click();
  await page.getByRole('combobox', {name:'Coordinator', exact:true}).selectOption('2');
  await page.getByRole('button', {name:'Save Advanced orchestration settings'}).click();
  await expect.poll(() => savedCoordinatorProfile).toBe(2);

  await page.getByRole('button', {name:'Test local models'}).click();
  const modelResults=page.locator('.swarm-model-test-results');
  await expect(modelResults.getByText('phi4:14b', {exact:true})).toBeVisible();
  await expect(modelResults.getByText(/420 ms/)).toBeVisible();
  await expect(modelResults.getByText('qwen2.5-coder:7b', {exact:true})).toBeVisible();
  await expect(modelResults.getByText(/280 ms/)).toBeVisible();

  await page.getByPlaceholder('Describe the larger outcome for Advanced orchestration…').fill('Harden authentication');
  await page.getByRole('button', {name:'Preflight & start Advanced orchestration'}).click();

  await expect.poll(() => createdObjective).toBe('Harden authentication');
  await expect(page.getByText(/Advanced orchestration #7 started/)).toBeVisible();
});

test('interaction agent board renders and controls a live swarm', async ({ page }) => {
  let pauseCalled = false;
  let coordinatorGuidance = '';
  let integrationBuilt = false;
  let integrationPushed = false;
  let finalPrCreated = false;
  let boardStatus = 'reviewing';
  let integrationBranch = '';
  let integrationPath = '';
  let integrationCheckStatus = '';
  const coordinatorAfter:string[] = [];
  const blackboardAfter:string[] = [];
  const run = {
    id:7,title:'Auth hardening',status:'reviewing',max_agents:5,max_concurrency:3,total_agents_created:2
  };

  await baseRoutes(page, async (route,url) => {
    const p=url.pathname;
    const json=(data:unknown)=>route.fulfill({json:data});
    if (p === '/api/projects/1/skills/swarm') {
      await json({project_id:1,skill:'swarm',enabled:true});
      return true;
    }
    if (p === '/api/projects/1/swarms') {
      await json([{...run,status:boardStatus}]);
      return true;
    }
    if (p === '/api/swarms/7/board') {
      const coordinatorCursor=url.searchParams.get('after_coordinator_event')||'0';
      const blackboardCursor=url.searchParams.get('after_blackboard')||'0';
      coordinatorAfter.push(coordinatorCursor);
      blackboardAfter.push(blackboardCursor);
      const initial=coordinatorCursor==='0'&&blackboardCursor==='0';
      await json({
        swarm:{
          id:7,title:'Auth hardening',status:boardStatus,
          integration_path:integrationPath,
          integration_branch:integrationBranch,
          integration_check_status:integrationCheckStatus,
          integration_pushed:integrationPushed?1:0,
          integration_pr_number:finalPrCreated?42:0,
          integration_pr_state:finalPrCreated?'OPEN':'',
          coordinator_activity:{category:'decision',content:'Coordinator opened final verification.'},
          coordinator_budget:{used:3,budget:20,remaining:17},
          agents:[
            {id:11,title:'Inspect auth',status:'completed',agent_role:'backend',task_kind:'backend',worktree_branch:'olladex/task-11',progress:100,assigned_model:'test',tool_usage:6,tool_budget:30,current_activity:'Done',latest_insight:{category:'finding',content:'Auth dependency is centralized.'}},
            {id:12,title:'Final review',status:'completed',agent_role:'reviewer',task_kind:'reviewer',progress:100,assigned_model:'test',tool_usage:2,tool_budget:30,current_activity:'Done'}
          ]
        },
        summary:{
          total_agents:2,active_agents:0,completed_agents:1,failed_agents:0,
          progress:100,max_agents:5,max_concurrency:3,integration_ready:true
        },
        events:[],
        coordinator_events:initial?[
          {id:20,kind:'status',payload:{status:'reviewing'},created_at:new Date().toISOString()},
          {id:21,kind:'decision',payload:{content:'Coordinator opened final verification.'},created_at:new Date().toISOString()}
        ]:[],
        blackboard:initial?[
          {id:1,task_id:null,category:'decision',content:'Review gate opened.',created_at:new Date().toISOString()},
          {id:2,task_id:11,category:'finding',content:'Auth dependency is centralized.',created_at:new Date().toISOString()},
          {id:3,task_id:11,category:'finding',content:'| Check | Status |\n| --- | --- |\n| Auth | Ready |',created_at:new Date().toISOString()}
        ]:[],
        cursors:{event:0,coordinator_event:21,blackboard:3},
        repository:{repository:true,has_head:true,remotes:[{name:'origin',url:'git@github.com:zageabb/olladex.git'}],has_remote:true,github_remote:'origin',can_push:true,can_create_pull_request:true},
        locations:{main:'/demo',integration:integrationPath,specialists:[{task_id:11,title:'Inspect auth',role:'backend',path:'/tmp/task-11',branch:'olladex/task-11',status:'completed'}]}
      });
      return true;
    }
    if (p === '/api/swarms/7/pause') {
      pauseCalled = true;
      await json({...run,status:'paused'});
      return true;
    }
    if (p === '/api/swarms/7/coordinator/input') {
      coordinatorGuidance = String(route.request().postDataJSON().content || '');
      await json({swarm_id:7,status:'received',coordinator_instructions:coordinatorGuidance});
      return true;
    }
    if (p === '/api/swarms/7/integration/preflight') {
      await json({task_ids:[11],branches:['olladex/task-11'],overlaps:[],files_by_branch:{'olladex/task-11':['backend/app/auth.py']}});
      return true;
    }
    if (p === '/api/swarms/7/integration' && route.request().method() === 'POST') {
      integrationBuilt = true;
      boardStatus = 'integrating';
      integrationPath = '/tmp/integration';
      integrationBranch = 'olladex/integration-swarm-7';
      await json({task_ids:[11],branches:['olladex/task-11'],overlaps:[],path:integrationPath,branch:integrationBranch});
      return true;
    }
    if (p === '/api/swarms/7/integration/checks') {
      boardStatus = 'ready_to_promote';
      integrationCheckStatus = 'passed';
      await json({passed:true,output:'100 passed',command:'pytest',status:'ready_to_promote'});
      return true;
    }
    if (p === '/api/swarms/7/integration/push') {
      integrationPushed = true;
      await json({branch:'olladex/integration-swarm-7'});
      return true;
    }
    if (p === '/api/swarms/7/integration/pull-request') {
      finalPrCreated = true;
      await json({pull_request_number:42,url:'https://github.com/zageabb/olladex/pull/42'});
      return true;
    }
    if (p === '/api/swarm-agents/11') {
      await json({
        task:{id:11,title:'Inspect auth',status:'completed',agent_role:'backend',progress:100,tool_usage:6,tool_budget:30,current_activity:'Done'},
        commands:[{id:1,command:'pytest backend/tests/test_auth.py',output:'12 passed',exit_code:0,status:'completed'}],
        blackboard:[
          {id:2,category:'finding',content:'Auth dependency is centralized.'},
          {id:3,category:'finding',content:'| Check | Status |\n| --- | --- |\n| Auth | Ready |'}
        ],
        changed_files:['backend/app/auth.py'],
        worktree:{branch_diff:'diff --git a/backend/app/auth.py b/backend/app/auth.py',working_diff:''}
      });
      return true;
    }
    return false;
  });

  await page.goto('/');
  await page.locator('.rail').getByRole('button', {name:'Tasks'}).click();

  await expect(page.getByRole('heading', {name:'Auth hardening'})).toBeVisible();
  await expect(page.getByText(/Advanced orchestration #7 · reviewing · 100% agent work/)).toBeVisible();
  await expect(page.getByText('Inspect auth')).toBeVisible();
  await expect(page.getByText(/backend · completed · 100%/)).toBeVisible();
  await expect(page.getByText('Final review', {exact:true})).toBeVisible();
  await expect(page.getByText(/reviewer · completed · 100%/)).toBeVisible();
  await expect(page.getByText(/budget 3\/20/)).toBeVisible();
  await expect(page.getByText(/budget 3\/20 · Coordinator opened final verification\./)).toBeVisible();
  await expect.poll(()=>coordinatorAfter.includes('21'),{timeout:5000}).toBe(true);
  await expect.poll(()=>blackboardAfter.includes('3'),{timeout:5000}).toBe(true);

  await page.getByPlaceholder('Guide Advanced orchestration…').fill('Prioritise regression tests.');
  await page.getByRole('button', {name:'Coordinator'}).click();
  await expect.poll(() => coordinatorGuidance).toBe('Prioritise regression tests.');

  await page.getByRole('button', {name:'Pause'}).click();
  await expect.poll(() => pauseCalled).toBe(true);

  await page.getByText('Inspect auth').click();
  await expect(page.getByText('backend/app/auth.py')).toBeVisible();
  await expect(page.getByText('pytest backend/tests/test_auth.py')).toBeVisible();
  await expect(page.locator('.agent-board-detail').getByText(/Auth dependency is centralized\./)).toBeVisible();
  const findingTable=page.locator('.agent-board-detail table');
  await expect(findingTable).toBeVisible();
  await expect(findingTable.getByRole('cell', {name:'Ready'})).toBeVisible();

  await page.getByText(/Coordinator timeline · 2/).click();
  await expect(page.getByText('Coordinator opened final verification.').last()).toBeVisible();
  await page.getByText(/Blackboard · 3/).click();
  await expect(page.getByText('Review gate opened.')).toBeVisible();

  await page.getByRole('button', {name:'Check overlaps'}).click();
  await expect(page.getByText('No overlapping files detected.')).toBeVisible();
  await page.getByRole('button', {name:'Build integration'}).click();
  await expect.poll(() => integrationBuilt).toBe(true);
  await page.getByRole('button', {name:'Run checks'}).click();
  await expect(page.getByText('passed', {exact:true})).toBeVisible();
  await page.getByRole('button', {name:'Push branch'}).click();
  await expect.poll(() => integrationPushed).toBe(true);
  await page.getByRole('button', {name:'Create final PR'}).click();
  await expect.poll(() => finalPrCreated).toBe(true);
});


test('interaction agent board can steer an active agent and switch between swarm runs', async ({ page }) => {
  let activeAgentGuidance = '';
  await baseRoutes(page, async (route,url) => {
    const p=url.pathname;
    const json=(data:unknown)=>route.fulfill({json:data});
    if (p === '/api/projects/1/skills/swarm') {
      await json({project_id:1,skill:'swarm',enabled:true});
      return true;
    }
    if (p === '/api/projects/1/swarms') {
      await json([
        {id:7,title:'Current swarm',status:'running',max_agents:5,max_concurrency:3,total_agents_created:1},
        {id:8,title:'Previous swarm',status:'completed',max_agents:4,max_concurrency:2,total_agents_created:1}
      ]);
      return true;
    }
    if (p === '/api/swarms/7/board') {
      await json({
        swarm:{id:7,title:'Current swarm',status:'running',agents:[{id:71,title:'Current task',status:'running',agent_role:'backend',progress:50}]},
        summary:{total_agents:1,active_agents:1,completed_agents:0,failed_agents:0,progress:50,max_agents:5,max_concurrency:3,integration_ready:false},
        events:[],coordinator_events:[],blackboard:[],cursors:{event:0,coordinator_event:0,blackboard:0}
      });
      return true;
    }
    if (p === '/api/swarms/8/board') {
      await json({
        swarm:{id:8,title:'Previous swarm',status:'completed',agents:[{id:81,title:'Historical task',status:'completed',agent_role:'tester',progress:100}]},
        summary:{total_agents:1,active_agents:0,completed_agents:1,failed_agents:0,progress:100,max_agents:4,max_concurrency:2,integration_ready:false},
        events:[],coordinator_events:[],blackboard:[],cursors:{event:0,coordinator_event:0,blackboard:0}
      });
      return true;
    }
    if (p === '/api/swarm-agents/71' && route.request().method() === 'GET') {
      await json({
        task:{id:71,title:'Current task',status:'running',agent_role:'backend',progress:50,tool_usage:3,tool_budget:30,current_activity:'Running tests'},
        commands:[],blackboard:[],changed_files:[],worktree:null
      });
      return true;
    }
    if (p === '/api/swarm-agents/71/input') {
      activeAgentGuidance = String(route.request().postDataJSON().content || '');
      await json({task_id:71,status:'received'});
      return true;
    }
    return false;
  });

  await page.goto('/');
  await page.locator('.rail').getByRole('button', {name:'Tasks'}).click();

  await expect(page.getByRole('heading', {name:'Current swarm'})).toBeVisible();
  await page.getByText('Current task').click();
  await page.getByPlaceholder('Guide this agent…').fill('Focus on the failing regression.');
  await page.getByRole('button', {name:'Send guidance'}).click();
  await expect.poll(()=>activeAgentGuidance).toBe('Focus on the failing regression.');
  await page.getByRole('button', {name:'Close'}).click();

  await page.getByLabel('Run').selectOption('8');
  await expect(page.getByRole('heading', {name:'Previous swarm'})).toBeVisible();
  await expect(page.getByText('Historical task')).toBeVisible();
  await expect(page.getByText(/Advanced orchestration #8 · completed · 100% complete/)).toBeVisible();
});


test('swarm preflight can initialize local git and continue without a remote', async ({ page }) => {
  let initialized = false;
  let createdObjective = '';

  await baseRoutes(page, async (route,url) => {
    const p=url.pathname;
    const json=(data:unknown)=>route.fulfill({json:data});
    if (p === '/api/projects/1/skills/swarm') {
      await json({project_id:1,skill:'swarm',enabled:true});
      return true;
    }
    if (p === '/api/projects/1/swarms/git/init') {
      initialized = true;
      await json({
        summary:{repository:true,branch:'main',remotes:[]},
        capabilities:{repository:true,has_head:true,remotes:[],has_remote:false,github_remote:'',can_push:false,can_create_pull_request:false}
      });
      return true;
    }
    if (p === '/api/projects/1/swarms/preflight') {
      if (!initialized) {
        await json({
          ready:false,project_id:1,profile_id:1,max_agents:5,max_concurrency:3,
          checks:[
            {name:'sqlite_wal',ok:true,detail:'journal_mode=wal'},
            {name:'git_repository',ok:false,detail:'Project is not a Git repository'},
            {name:'git_head',ok:false,detail:'Create a local baseline commit before starting Swarm'},
            {name:'ollama_models',ok:true,detail:'test'}
          ],
          git:{repository:false,has_head:false,remotes:[],has_remote:false,github_remote:'',can_push:false,can_create_pull_request:false}
        });
      } else {
        await json({
          ready:true,project_id:1,profile_id:1,max_agents:5,max_concurrency:3,
          checks:[
            {name:'sqlite_wal',ok:true,detail:'journal_mode=wal'},
            {name:'git_repository',ok:true,detail:'Git repository ready'},
            {name:'git_head',ok:true,detail:'Baseline commit available'},
            {name:'ollama_models',ok:true,detail:'test'}
          ],
          git:{repository:true,has_head:true,remotes:[],has_remote:false,github_remote:'',can_push:false,can_create_pull_request:false}
        });
      }
      return true;
    }
    if (p === '/api/projects/1/swarms' && route.request().method() === 'POST') {
      createdObjective=String(route.request().postDataJSON().objective||'');
      await json({swarm:{id:9}});
      return true;
    }
    return false;
  });

  await page.goto('/');
  await page.locator('.rail').getByRole('button', {name:'Tasks'}).click();
  await page.getByText(/Advanced orchestration controls/).click();

  await page.getByPlaceholder('Describe the larger outcome for Advanced orchestration…').fill('Improve local app');
  await page.getByRole('button', {name:'Preflight & start Advanced orchestration'}).click();

  await expect(page.getByRole('button', {name:'Initialize local Git'})).toBeVisible();
  await page.getByRole('button', {name:'Initialize local Git'}).click();
  await expect.poll(()=>initialized).toBe(true);
  await expect(page.getByText(/Local-only Git repository/)).toBeVisible();

  await page.getByRole('button', {name:'Preflight & start Advanced orchestration'}).click();
  await expect.poll(()=>createdObjective).toBe('Improve local app');
});

test('local swarm must be promoted to main before completion', async ({ page }) => {
  let promoted = false;
  await baseRoutes(page, async (route,url) => {
    const p=url.pathname;
    const json=(data:unknown)=>route.fulfill({json:data});
    if (p === '/api/projects/1/skills/swarm') {
      await json({project_id:1,skill:'swarm',enabled:true});
      return true;
    }
    if (p === '/api/projects/1/swarms') {
      await json([{id:10,title:'Local only',status:promoted?'completed':'ready_to_promote',max_agents:4,max_concurrency:2,total_agents_created:1}]);
      return true;
    }
    if (p === '/api/swarms/10/board') {
      await json({
        swarm:{
          id:10,title:'Local only',status:promoted?'completed':'ready_to_promote',
          integration_path:'/tmp/local-integration',
          integration_branch:'olladex/integration-swarm-10',
          integration_check_status:'passed',
          integration_check_output:'all good',
          promotion_status:promoted?'promoted':'',
          promoted_commit:promoted?'abc123def456':'',
          agents:[{id:101,title:'Local change',status:'completed',agent_role:'backend',task_kind:'backend',worktree_branch:'olladex/task-101',progress:100}]
        },
        summary:{total_agents:1,active_agents:0,completed_agents:1,failed_agents:0,progress:100,max_agents:4,max_concurrency:2,integration_ready:true},
        events:[],coordinator_events:[],blackboard:[],cursors:{event:0,coordinator_event:0,blackboard:0},
        repository:{repository:true,has_head:true,remotes:[],has_remote:false,github_remote:'',can_push:false,can_create_pull_request:false},
        locations:{
          main:'/Users/test/project',
          integration:'/tmp/local-integration',
          specialists:[{task_id:101,title:'Local change',role:'backend',path:'/tmp/task-101',branch:'olladex/task-101',status:'completed'}]
        }
      });
      return true;
    }
    if (p === '/api/swarms/10/integration/promote') {
      promoted = true;
      await json({status:'completed',promotion:{main_commit:'abc123def456',main_path:'/Users/test/project',integration_commit:'abc123def456'}});
      return true;
    }
    return false;
  });

  await page.goto('/');
  await page.locator('.rail').getByRole('button', {name:'Tasks'}).click();

  await expect(page.getByRole('heading', {name:'Local only'})).toBeVisible();
  await expect(page.getByText('Verified local integration branch ready')).toBeVisible();
  await expect(page.getByText(/has not yet been promoted to main/)).toBeVisible();
  await expect(page.getByText('/Users/test/project')).toBeVisible();
  await expect(page.getByText('/tmp/local-integration')).toBeVisible();
  await expect(page.getByText(/olladex\/task-101/)).toBeVisible();
  await expect(page.getByRole('button', {name:'Promote to main'})).toBeVisible();
  await expect(page.getByRole('button', {name:'Push branch'})).toHaveCount(0);
  await expect(page.getByRole('button', {name:'Create final PR'})).toHaveCount(0);

  await page.getByRole('button', {name:'Promote to main'}).click();
  await expect.poll(()=>promoted).toBe(true);
  await expect(page.getByText(/Advanced orchestration #10 · completed · 100% complete/)).toBeVisible();
});


test('advanced orchestration surfaces and resolves the correct agent command approval', async ({ page }) => {
  let boardCalls = 0;
  let decision: {id:number;accepted:boolean}|null = null;
  let currentCommandId = 901;
  let waiting = true;
  const sessions = [
    {id:1,project_id:1,title:'Chat',updated_at:new Date().toISOString()},
    {id:42,project_id:1,title:'Approval agent conversation',updated_at:new Date().toISOString()},
    {id:43,project_id:1,title:'Other agent conversation',updated_at:new Date().toISOString()}
  ];

  await baseRoutes(page, async (route,url) => {
    const p=url.pathname;
    const json=(data:unknown)=>route.fulfill({json:data});

    if (p === '/api/projects/1/sessions') {
      await json(sessions);
      return true;
    }
    if (p === '/api/projects/1/skills/swarm') {
      await json({project_id:1,skill:'swarm',enabled:true});
      return true;
    }
    if (p === '/api/projects/1/swarms') {
      await json([{id:20,title:'Approval test',status:'running',max_agents:4,max_concurrency:2,total_agents_created:2}]);
      return true;
    }
    if (p === '/api/swarms/20/board') {
      boardCalls += 1;
      const approvalVisible = boardCalls >= 2 && waiting;
      await json({
        swarm:{
          id:20,title:'Approval test',status:'running',
          coordinator_budget:{used:1,budget:20,remaining:19},
          agents:[
            {
              id:201,title:'Command agent',status:approvalVisible?'waiting_for_approval':'running',
              agent_role:'backend',task_kind:'backend',progress:55,session_id:42,
              run_id:701,run_status:approvalVisible?'waiting_for_approval':'running',
              pending_approval:approvalVisible?{
                id:currentCommandId,command:'pytest backend/tests/test_auth.py -q',
                cwd:'/demo/.olladex/task-201',status:'pending'
              }:null
            },
            {
              id:202,title:'Other agent',status:'running',agent_role:'tester',task_kind:'tester',
              progress:40,session_id:43,run_id:702,run_status:'running',pending_approval:null
            }
          ]
        },
        summary:{total_agents:2,active_agents:2,completed_agents:0,failed_agents:0,progress:48,max_agents:4,max_concurrency:2,integration_ready:false},
        events:[],coordinator_events:[],blackboard:[],cursors:{event:0,coordinator_event:0,blackboard:0},
        repository:{repository:true,has_head:true,remotes:[],has_remote:false,github_remote:'',can_push:false,can_create_pull_request:false}
      });
      return true;
    }
    if (p === '/api/swarm-agents/201') {
      const active = waiting;
      await json({
        task:{
          id:201,title:'Command agent',status:active?'waiting_for_approval':'running',
          agent_role:'backend',task_kind:'backend',progress:55,session_id:42
        },
        run:{id:701,session_id:42,task_id:201,status:active?'waiting_for_approval':'running',cancel_requested:0},
        commands:[
          {id:currentCommandId,run_id:701,command:'pytest backend/tests/test_auth.py -q',cwd:'/demo/.olladex/task-201',output:'',exit_code:-1,status:active?'pending':(decision?.accepted?'running':'rejected')},
          {id:900,run_id:699,command:'printf stale',cwd:'/old/worktree',output:'',exit_code:-1,status:'pending'}
        ],
        active_pending_commands:active?[
          {id:currentCommandId,run_id:701,command:'pytest backend/tests/test_auth.py -q',cwd:'/demo/.olladex/task-201',output:'',exit_code:-1,status:'pending'}
        ]:[],
        blackboard:[],changed_files:[],worktree:null
      });
      return true;
    }
    if (p === '/api/swarm-agents/202') {
      await json({
        task:{id:202,title:'Other agent',status:'running',agent_role:'tester',task_kind:'tester',progress:40,session_id:43},
        run:{id:702,session_id:43,task_id:202,status:'running',cancel_requested:0},
        commands:[],active_pending_commands:[],blackboard:[],changed_files:[],worktree:null
      });
      return true;
    }
    if (p === '/api/commands/' + currentCommandId + '/decision') {
      decision={id:currentCommandId,accepted:Boolean(route.request().postDataJSON().accepted)};
      waiting=false;
      await json({status:decision.accepted?'approved':'rejected'});
      return true;
    }
    return false;
  });

  await page.goto('/');
  await page.locator('.rail').getByRole('button', {name:'Tasks'}).click();

  await expect.poll(()=>boardCalls,{timeout:4000}).toBeGreaterThanOrEqual(2);
  const banner=page.locator('.advanced-approval-banner');
  await expect(banner.getByText('Command approval required')).toBeVisible();
  await expect(banner.getByRole('button',{name:'Agent #201 needs command approval'})).toBeVisible();
  await expect(page.getByRole('button',{name:'Agent #202 needs command approval'})).toHaveCount(0);

  await banner.getByRole('button',{name:'Agent #201 needs command approval'}).click();
  const detail=page.locator('.agent-board-detail');
  await expect(detail.getByText('Advanced orchestration agent #201')).toBeVisible();
  const approval=detail.locator('.agent-pending-approvals');
  await expect(approval.getByText('pytest backend/tests/test_auth.py -q',{exact:true})).toBeVisible();
  await expect(approval.getByText('Working directory: /demo/.olladex/task-201')).toBeVisible();
  await expect(approval.getByRole('button',{name:'Approve once'})).toBeVisible();
  await expect(approval.getByRole('button',{name:'Decline'})).toBeVisible();
  await expect(detail.getByText('printf stale',{exact:true})).toBeVisible();
  await expect(detail.locator('.agent-pending-approvals').getByText('printf stale',{exact:true})).toHaveCount(0);

  await approval.getByRole('button',{name:'Approve once'}).click();
  await expect.poll(()=>decision).toEqual({id:901,accepted:true});
  await expect(detail.locator('.agent-pending-approvals')).toHaveCount(0);
  await expect(page.locator('.advanced-approval-banner')).toHaveCount(0);

  currentCommandId=902;
  decision=null;
  waiting=true;
  await expect(page.locator('.advanced-approval-banner').getByRole('button',{name:'Agent #201 needs command approval'})).toBeVisible({timeout:4000});
  await page.locator('.advanced-approval-banner').getByRole('button',{name:'Agent #201 needs command approval'}).click();
  await expect(detail.locator('.agent-pending-approvals').getByRole('button',{name:'Decline'})).toBeVisible();
  await detail.locator('.agent-pending-approvals').getByRole('button',{name:'Decline'}).click();
  await expect.poll(()=>decision).toEqual({id:902,accepted:false});
  await expect(detail.locator('.agent-pending-approvals')).toHaveCount(0);

  await detail.getByRole('button',{name:'Open conversation'}).click();
  await expect(page.locator('.conversation-panel').getByRole('heading',{name:'Approval agent conversation'})).toBeVisible();
});

test('autonomous advanced orchestration shows no approval controls without an explicit pending command', async ({ page }) => {
  await baseRoutes(page, async (route,url) => {
    const p=url.pathname;
    const json=(data:unknown)=>route.fulfill({json:data});
    if (p === '/api/projects') {
      await json([{...project,approval_mode:'autonomous'}]);
      return true;
    }
    if (p === '/api/projects/1/skills/swarm') {
      await json({project_id:1,skill:'swarm',enabled:true});
      return true;
    }
    if (p === '/api/projects/1/swarms') {
      await json([{id:21,title:'Autonomous orchestration',status:'running',max_agents:3,max_concurrency:2,total_agents_created:1}]);
      return true;
    }
    if (p === '/api/swarms/21/board') {
      await json({
        swarm:{id:21,title:'Autonomous orchestration',status:'running',agents:[
          {id:211,title:'Autonomous agent',status:'running',agent_role:'backend',task_kind:'backend',session_id:42,run_id:801,run_status:'running',pending_approval:null}
        ]},
        summary:{total_agents:1,active_agents:1,completed_agents:0,failed_agents:0,progress:20,max_agents:3,max_concurrency:2,integration_ready:false},
        events:[],coordinator_events:[],blackboard:[],cursors:{event:0,coordinator_event:0,blackboard:0}
      });
      return true;
    }
    if (p === '/api/swarm-agents/211') {
      await json({
        task:{id:211,title:'Autonomous agent',status:'running',agent_role:'backend',task_kind:'backend',session_id:42},
        run:{id:801,session_id:42,task_id:211,status:'running',cancel_requested:0},
        commands:[{id:950,run_id:801,command:'pytest -q',cwd:'/demo',output:'ok',exit_code:0,status:'completed'}],
        active_pending_commands:[],blackboard:[],changed_files:[],worktree:null
      });
      return true;
    }
    return false;
  });

  await page.goto('/');
  await page.locator('.rail').getByRole('button',{name:'Tasks'}).click();

  await expect(page.locator('.advanced-approval-banner')).toHaveCount(0);
  await page.getByText('Autonomous agent',{exact:true}).click();
  const detail=page.locator('.agent-board-detail');
  await expect(detail.getByRole('button',{name:'Approve once'})).toHaveCount(0);
  await expect(detail.getByRole('button',{name:'Decline'})).toHaveCount(0);
});


test('advanced orchestration recovers budget-exhausted agents and blocked dependants without reload', async ({ page }) => {
  let resumed = false;
  let rootCompleted = false;
  let retryRequested = false;
  let resumeBody: Record<string,unknown>|null = null;

  await baseRoutes(page, async (route,url) => {
    const p=url.pathname;
    const json=(data:unknown)=>route.fulfill({json:data});
    if (p === '/api/projects/1/skills/swarm') {
      await json({project_id:1,skill:'swarm',enabled:true});
      return true;
    }
    if (p === '/api/projects/1/swarms') {
      await json([{id:30,title:'Recovery test',status:retryRequested?'recovering':'recovery_available',max_agents:5,max_concurrency:3,total_agents_created:2}]);
      return true;
    }
    if (p === '/api/swarms/30/board') {
      const rootStatus = rootCompleted ? 'completed' : resumed ? 'running' : 'budget_exhausted';
      const childStatus = retryRequested ? 'queued' : 'dependency_failed';
      const recoveryAvailable = !retryRequested && (!rootCompleted || childStatus === 'dependency_failed');
      await json({
        swarm:{
          id:30,title:'Recovery test',status:retryRequested?'recovering':'recovery_available',
          agents:[
            {
              id:301,title:'Implement callbacks',status:rootStatus,agent_role:'frontend',task_kind:'frontend',
              progress:rootCompleted?100:65,session_id:81,run_id:53,run_status:rootStatus,
              worktree_branch:'olladex/task-301',
              recovery:(!resumed&&!rootCompleted)?{
                task_id:301,status:'budget_exhausted',session_id:81,active_run_id:0,prior_run_id:53,
                prior_run_status:'budget_exhausted',checkpoint_available:true,checkpoint_bytes:22341,
                worktree_path:'/tmp/worktrees/30/task-301',worktree_branch:'olladex/task-301',
                worktree_available:true,branch_available:true,previous_budget:30,resumed_budget:44,
                max_recovery_attempts:3,recovery_attempt:0,blocking_dependency_ids:[],can_resume:true
              }:null
            },
            {
              id:302,title:'Review callbacks',status:childStatus,agent_role:'reviewer',task_kind:'reviewer',
              progress:0,session_id:82,run_status:childStatus,worktree_branch:'olladex/task-302',
              blocking_dependency_ids:retryRequested?[]:[301],recovery:null
            }
          ]
        },
        summary:{
          total_agents:2,active_agents:resumed&&!rootCompleted?1:0,completed_agents:rootCompleted?1:0,
          failed_agents:retryRequested?0:1,progress:rootCompleted?50:33,max_agents:5,max_concurrency:3,
          integration_ready:false,recovery_available:recoveryAvailable,
          recovery_blockers:recoveryAvailable?[
            ...((!resumed&&!rootCompleted)?[{
              task_id:301,title:'Implement callbacks',status:'budget_exhausted',blocking_dependency_ids:[],
              recovery:{
                task_id:301,status:'budget_exhausted',session_id:81,active_run_id:0,prior_run_id:53,
                prior_run_status:'budget_exhausted',checkpoint_available:true,checkpoint_bytes:22341,
                worktree_path:'/tmp/worktrees/30/task-301',worktree_branch:'olladex/task-301',
                worktree_available:true,branch_available:true,previous_budget:30,resumed_budget:44,
                max_recovery_attempts:3,recovery_attempt:0,blocking_dependency_ids:[],can_resume:true
              }
            }]:[]),
            ...(retryRequested?[]:[{task_id:302,title:'Review callbacks',status:'dependency_failed',blocking_dependency_ids:[301],recovery:null}])
          ]:[],
          integration_blockers:recoveryAvailable?[
            ...((!resumed&&!rootCompleted)?['#301 needs recovery']:[]),
            ...(retryRequested?[]:['#302 is blocked by dependencies 301'])
          ]:[]
        },
        budget_requests:[],
        events:[],coordinator_events:[],blackboard:[],
        cursors:{event:0,coordinator_event:0,blackboard:0},
        repository:{repository:true,has_head:true,remotes:[],has_remote:false,github_remote:'',can_push:false,can_create_pull_request:false},
        locations:{main:'/demo',integration:'',specialists:[
          {task_id:301,title:'Implement callbacks',role:'frontend',path:'/tmp/worktrees/30/task-301',branch:'olladex/task-301',status:rootStatus}
        ]}
      });
      return true;
    }
    if (p === '/api/tasks/301/resume') {
      resumeBody=route.request().postDataJSON();
      resumed=true;
      await json({
        task_id:301,session_id:81,prior_run_id:53,run_id:54,status:'running',
        checkpoint_restored:true,checkpoint_bytes:22341,recovery_attempt:1,fresh_budget:44,
        worktree_path:'/tmp/worktrees/30/task-301',worktree_branch:'olladex/task-301',
        starting_head:'abc123',dirty_work_preserved:true
      });
      return true;
    }
    if (p === '/api/tasks/301/retry-dependants') {
      retryRequested=true;
      await json({task_id:301,retried_task_ids:[302],full_chain:Boolean(route.request().postDataJSON().full_chain)});
      return true;
    }
    return false;
  });

  await page.goto('/');
  await page.locator('.rail').getByRole('button',{name:'Tasks'}).click();

  const recovery=page.locator('.advanced-recovery-banner');
  await expect(recovery.getByText('Recovery available')).toBeVisible();
  await expect(recovery.getByText(/Checkpoint 22341 bytes/)).toBeVisible();
  await expect(recovery.getByText(/prior budget 30 · new budget 44/)).toBeVisible();
  await expect(recovery.getByText('Branch: olladex/task-301',{exact:true})).toBeVisible();
  await expect(recovery.getByText('Worktree: /tmp/worktrees/30/task-301',{exact:true})).toBeVisible();
  await expect(recovery.getByText(/Agent #302 blocked by dependency/)).toBeVisible();
  await expect(recovery.getByText(/Integration unavailable:/)).toBeVisible();
  await expect(page.locator('.agent-board-integration')).toHaveCount(0);
  const lifecycle=page.locator('.agent-board-lifecycle');
  await expect(lifecycle.getByText('Delivery lifecycle')).toBeVisible();
  for (const stage of ['Specialists','Review','Integrate','Checks','Deliver']) await expect(lifecycle.getByText(stage,{exact:true})).toBeVisible();
  const dependencyMap=page.locator('.agent-board-dependency-map');
  await expect(dependencyMap.getByText('Task dependencies')).toBeVisible();
  await expect(dependencyMap.locator('button').filter({hasText:'#301'}).filter({hasText:'#302'})).toBeVisible();

  await recovery.getByRole('button',{name:'Resume from checkpoint'}).click();
  await expect.poll(()=>resumeBody).toEqual({fresh_budget:44});
  await expect(page.getByText(/frontend · running/)).toBeVisible({timeout:4000});
  await expect(recovery.getByRole('button',{name:'Resume from checkpoint'})).toHaveCount(0);

  rootCompleted=true;
  await expect(recovery.getByRole('button',{name:'Retry blocked dependants after #301'})).toBeVisible({timeout:4000});
  await expect(recovery.getByRole('button',{name:'Retry full dependency chain'})).toBeVisible();

  await recovery.getByRole('button',{name:'Retry full dependency chain'}).click();
  await expect.poll(()=>retryRequested).toBe(true);
  await expect(page.getByText(/reviewer · queued/)).toBeVisible({timeout:4000});
  await expect(page.locator('.advanced-recovery-banner')).toHaveCount(0);
});

test('pending agent budget request suppresses duplicate manual resume controls', async ({ page }) => {
  await baseRoutes(page, async (route,url) => {
    const p=url.pathname;
    const json=(data:unknown)=>route.fulfill({json:data});
    if (p === '/api/projects/1/skills/swarm') {
      await json({project_id:1,skill:'swarm',enabled:true});
      return true;
    }
    if (p === '/api/projects/1/swarms') {
      await json([{id:31,title:'Budget decision',status:'recovery_available',max_agents:4,max_concurrency:2,total_agents_created:1}]);
      return true;
    }
    if (p === '/api/swarms/31/board') {
      const recovery={
        task_id:311,status:'budget_exhausted',session_id:91,active_run_id:0,prior_run_id:61,
        prior_run_status:'budget_exhausted',checkpoint_available:true,checkpoint_bytes:4096,
        worktree_path:'/tmp/worktrees/31/task-311',worktree_branch:'olladex/task-311',
        worktree_available:true,branch_available:true,previous_budget:30,resumed_budget:20,
        max_recovery_attempts:3,recovery_attempt:0,blocking_dependency_ids:[],can_resume:true
      };
      await json({
        swarm:{
          id:31,title:'Budget decision',status:'recovery_available',
          coordinator_budget:{used:4,budget:20,remaining:16},
          agents:[{
            id:311,title:'Continue implementation',status:'budget_exhausted',
            agent_role:'backend',task_kind:'backend',progress:70,session_id:91,
            run_id:61,run_status:'budget_exhausted',recovery
          }]
        },
        summary:{
          total_agents:1,active_agents:0,completed_agents:0,failed_agents:0,
          progress:70,max_agents:4,max_concurrency:2,integration_ready:false,
          recovery_available:true,
          recovery_blockers:[{task_id:311,title:'Continue implementation',status:'budget_exhausted',blocking_dependency_ids:[],recovery}],
          integration_blockers:['#311 needs recovery']
        },
        budget_requests:[{
          id:77,swarm_id:31,task_id:311,run_id:61,scope:'agent',status:'pending',
          requested_amount:25,granted_amount:0,
          reason:'Coordinator needs your decision before adding more tool steps.',decided_by:''
        }],
        events:[],coordinator_events:[],blackboard:[],
        cursors:{event:0,coordinator_event:0,blackboard:0}
      });
      return true;
    }
    if (p === '/api/swarm-agents/311') {
      await json({
        task:{
          id:311,title:'Continue implementation',status:'budget_exhausted',
          agent_role:'backend',task_kind:'backend',progress:70,session_id:91,
          recovery:{
            task_id:311,status:'budget_exhausted',session_id:91,active_run_id:0,prior_run_id:61,
            prior_run_status:'budget_exhausted',checkpoint_available:true,checkpoint_bytes:4096,
            worktree_path:'/tmp/worktrees/31/task-311',worktree_branch:'olladex/task-311',
            worktree_available:true,branch_available:true,previous_budget:30,resumed_budget:20,
            max_recovery_attempts:3,recovery_attempt:0,blocking_dependency_ids:[],can_resume:true
          }
        },
        run:{id:61,session_id:91,task_id:311,status:'budget_exhausted',cancel_requested:0},
        commands:[],active_pending_commands:[],blackboard:[],changed_files:[],worktree:null
      });
      return true;
    }
    return false;
  });

  await page.goto('/');
  await page.locator('.rail').getByRole('button',{name:'Tasks'}).click();

  const budget=page.locator('.advanced-budget-banner');
  await expect(budget.getByText('More budget requested')).toBeVisible();
  await expect(budget.getByText(/Agent #311 needs more budget/)).toBeVisible();
  await expect(page.getByText('Waiting for budget decision')).toBeVisible();
  await expect(page.locator('.advanced-recovery-banner').getByRole('button',{name:'Resume from checkpoint'})).toHaveCount(0);
  await expect(page.locator('.agent-board-preview').getByRole('button',{name:'Resume from checkpoint'})).toHaveCount(0);

  await page.getByText('Continue implementation',{exact:true}).click();
  const detail=page.locator('.agent-board-detail');
  await expect(detail.getByText('Waiting for budget decision')).toBeVisible();
  await expect(detail.getByRole('button',{name:'Resume from checkpoint'})).toHaveCount(0);
});

