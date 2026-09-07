import { test, expect } from '@playwright/test';

test('live conversation accepts guidance and isolates a newly selected chat', async ({ page }) => {
  let running = false;
  let steering = '';
  const project = { id:1,name:'Demo',path:'/demo',model:'test',approval_mode:'assisted' };
  const sessions = [{id:1,project_id:1,title:'First conversation'}, {id:2,project_id:1,title:'Second conversation'}];
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()); const p = url.pathname;
    const json = (data: unknown) => route.fulfill({ json: data });
    if (p === '/api/projects') return json([project]);
    if (p === '/api/status') return json({ version:'test',ollama:{connected:true,models:['test']} });
    if (p.endsWith('/sessions')) return json(sessions);
    if (p.endsWith('/memory')) return json({content:''});
    if (p.endsWith('/messages')) return json([]);
    if (p.endsWith('/runs') && route.request().method() === 'POST') { running = true; return json({id:7,status:'running'}); }
    if (p.endsWith('/runs')) return json(p.includes('/sessions/1/') && running ? [{id:7,status:'running'}] : []);
    if (p.endsWith('/events')) return route.fulfill({ contentType:'application/x-ndjson',body:[
      {id:1,run_id:7,kind:'user_message',payload:{content:'Inspect the code'}},
      {id:2,run_id:7,kind:'text_delta',payload:{text:'I found the search handler.'}},
      {id:3,run_id:7,kind:'question',payload:{question:'Should I keep live search?'}},
      {id:4,run_id:7,kind:'status',payload:{status:'waiting_for_input'}},
    ].map(e => JSON.stringify(e)).join('\n')+'\n' });
    if (p.endsWith('/input')) { steering = route.request().postDataJSON().content; return json({status:'received'}); }
    if (p.endsWith('/git/diff')) return json({diff:''});
    if (p.endsWith('/git')) return json({changes:[],branches:[],remotes:[]});
    return json([]);
  });
  await page.goto('/');
  await page.getByRole('textbox', {name:'Message Olladex'}).fill('Inspect the code');
  await page.getByRole('button', {name:'Send', exact:true}).click();
  await expect(page.getByText('I found the search handler.', {exact:true})).toBeVisible();
  await expect(page.getByRole('button', {name:'Stop', exact:true})).toBeVisible();
  await page.screenshot({path:'test-results/conversation.png', fullPage:true});
  await page.getByRole('textbox', {name:'Message Olladex'}).fill('Keep live search');
  await page.getByRole('button', {name:/Reply|Send guidance/, exact:true}).click();
  await expect.poll(() => steering).toBe('Keep live search');
  await page.getByRole('button', {name:/Second conversation/}).click();
  await expect(page.getByText('I found the search handler.', {exact:true})).toHaveCount(0);
  await expect(page.getByRole('button', {name:'Send',exact:true})).toBeVisible();
});

test('late file reads cannot overwrite the selected project', async ({page}) => {
  let release: () => void = () => {};
  const gate = new Promise<void>(resolve => { release = resolve; });
  let firstRead = false;
  await page.route('**/api/**', async route => {
    const p = new URL(route.request().url()).pathname;
    const json = (data: unknown) => route.fulfill({json:data});
    if (p === '/api/projects') return json([1,2].map(id => ({id,name:`Project ${id}`,path:`/project${id}`,model:'test',approval_mode:'assisted'})));
    if (p === '/api/status') return json({ollama:{connected:true,models:['test']}});
    if (p.endsWith('/sessions')) return json([{id:p.includes('/1/') ? 1:2,title:'Chat'}]);
    if (p.endsWith('/tree')) return json([{name:'app.txt',path:'app.txt',type:'file'}]);
    if (p.endsWith('/files')) {
      if (p.includes('/1/')) {firstRead = true; await gate; return json({content:'STALE FIRST PROJECT'});}
      return json({content:'CURRENT SECOND PROJECT'});
    }
    if (p.endsWith('/memory')) return json({content:''});
    if (p.endsWith('/git/diff')) return json({diff:''});
    if (p.endsWith('/git')) return json({changes:[],branches:[],remotes:[]});
    return json([]);
  });
  await page.goto('/');
  await page.getByTitle('app.txt', {exact:true}).click();
  await expect.poll(() => firstRead).toBeTruthy();
  await page.locator('.project-selector select').selectOption('2');
  await page.getByTitle('app.txt', {exact:true}).click();
  await expect(page.locator('.code-editor')).toHaveValue('CURRENT SECOND PROJECT');
  release();
  await expect(page.locator('.code-editor')).toHaveValue('CURRENT SECOND PROJECT');
});
