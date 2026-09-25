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
