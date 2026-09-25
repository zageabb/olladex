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
      coordinator_tool_budget:20,is_builtin:1
    }]);
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

  await baseRoutes(page, async (route,url) => {
    const p=url.pathname;
    const json=(data:unknown)=>route.fulfill({json:data});
    if (p === '/api/projects/1/skills/swarm') {
      if (route.request().method() === 'PUT') swarmEnabled = Boolean(route.request().postDataJSON().enabled);
      await json({project_id:1,skill:'swarm',enabled:swarmEnabled});
      return true;
    }
    if (p === '/api/projects/1/swarms/preflight') {
      await json({ready:true,project_id:1,profile_id:1,max_agents:5,max_concurrency:3,checks:[
        {name:'sqlite_wal',ok:true,detail:'journal_mode=wal'},
        {name:'git_repository',ok:true,detail:'true'},
        {name:'ollama_models',ok:true,detail:'test'}
      ]});
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
  await page.getByText(/Swarm controls/).click();
  await expect(page.getByRole('button', {name:'Enable Swarm'})).toBeVisible();

  await page.getByRole('button', {name:'Enable Swarm'}).click();
  await expect.poll(() => swarmEnabled).toBe(true);

  await page.getByPlaceholder('Describe the larger outcome for the Swarm…').fill('Harden authentication');
  await page.getByRole('button', {name:'Preflight & start Swarm'}).click();

  await expect.poll(() => createdObjective).toBe('Harden authentication');
  await expect(page.getByText(/Swarm #7 started/)).toBeVisible();
});

test('interaction agent board renders and controls a live swarm', async ({ page }) => {
  let pauseCalled = false;
  let coordinatorGuidance = '';
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
      await json([run]);
      return true;
    }
    if (p === '/api/swarms/7/board') {
      await json({
        swarm:{
          id:7,title:'Auth hardening',status:'reviewing',
          coordinator_activity:{category:'decision',content:'Coordinator opened final verification.'},
          coordinator_budget:{used:3,budget:20,remaining:17},
          agents:[
            {id:11,title:'Inspect auth',status:'completed',agent_role:'backend',progress:100,assigned_model:'test',tool_usage:6,tool_budget:30,current_activity:'Done',latest_insight:{category:'finding',content:'Auth dependency is centralized.'}},
            {id:12,title:'Final review',status:'queued',agent_role:'reviewer',progress:0,assigned_model:'test',tool_usage:0,tool_budget:30,current_activity:''}
          ]
        },
        summary:{
          total_agents:2,active_agents:0,completed_agents:1,failed_agents:0,
          progress:50,max_agents:5,max_concurrency:3,integration_ready:false
        },
        events:[],coordinator_events:[],blackboard:[],
        cursors:{event:0,coordinator_event:0,blackboard:0}
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
    if (p === '/api/swarm-agents/11') {
      await json({
        task:{id:11,title:'Inspect auth',status:'completed',agent_role:'backend',progress:100,tool_usage:6,tool_budget:30,current_activity:'Done'},
        commands:[{id:1,command:'pytest backend/tests/test_auth.py',output:'12 passed',exit_code:0,status:'completed'}],
        blackboard:[{id:2,category:'finding',content:'Auth dependency is centralized.'}],
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
  await expect(page.getByText(/Swarm #7 · reviewing · 50% complete/)).toBeVisible();
  await expect(page.getByText('Inspect auth')).toBeVisible();
  await expect(page.getByText(/backend · completed · 100%/)).toBeVisible();
  await expect(page.getByText('Final review')).toBeVisible();
  await expect(page.getByText(/reviewer · queued · 0%/)).toBeVisible();
  await expect(page.getByText(/budget 3\/20/)).toBeVisible();
  await expect(page.getByText('Coordinator opened final verification.')).toBeVisible();

  await page.getByPlaceholder('Guide the Swarm…').fill('Prioritise regression tests.');
  await page.getByRole('button', {name:'Coordinator'}).click();
  await expect.poll(() => coordinatorGuidance).toBe('Prioritise regression tests.');

  await page.getByRole('button', {name:'Pause'}).click();
  await expect.poll(() => pauseCalled).toBe(true);

  await page.getByText('Inspect auth').click();
  await expect(page.getByText('backend/app/auth.py')).toBeVisible();
  await expect(page.getByText('pytest backend/tests/test_auth.py')).toBeVisible();
  await expect(page.getByText('Auth dependency is centralized.').last()).toBeVisible();
});
