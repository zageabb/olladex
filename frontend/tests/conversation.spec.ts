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


test('renders GFM tables in chat and markdown file preview', async ({ page }) => {
  const project = { id:1,name:'Demo',path:'/demo',model:'test',approval_mode:'assisted' };
  const table = '| Name | Status |\n| --- | --- |\n| Search | Ready |';

  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    const json = (data: unknown) => route.fulfill({ json: data });
    if (p === '/api/projects') return json([project]);
    if (p === '/api/status') return json({ version:'test',ollama:{connected:true,models:['test']} });
    if (p === '/api/projects/1/sessions') return json([{id:1,project_id:1,title:'Chat'}]);
    if (p === '/api/sessions/1/messages') return json([{id:1,role:'assistant',content:table}]);
    if (p === '/api/sessions/1/runs') return json([]);
    if (p === '/api/sessions/1/memory') return json({content:''});
    if (p === '/api/projects/1/tree') return json([{name:'README.md',path:'README.md',type:'file'}]);
    if (p === '/api/projects/1/files') return json({content:'# Overview\n\n'+table});
    if (p.endsWith('/git/diff')) return json({diff:''});
    if (p.endsWith('/git')) return json({changes:[],branches:[],remotes:[]});
    if (p.endsWith('/changes')) return json([]);
    return json([]);
  });

  await page.goto('/');

  const chatTable = page.locator('.message.assistant table');
  await expect(chatTable).toBeVisible();
  await expect(chatTable.getByRole('columnheader', {name:'Name'})).toBeVisible();
  await expect(chatTable.getByRole('cell', {name:'Ready'})).toBeVisible();

  await page.getByTitle('README.md', {exact:true}).click();
  await expect(page.getByRole('button', {name:'Preview'})).toHaveClass(/active/);

  const previewTable = page.locator('.markdown-document table');
  await expect(previewTable).toBeVisible();
  await expect(previewTable.getByRole('columnheader', {name:'Status'})).toBeVisible();
  await expect(previewTable.getByRole('cell', {name:'Search'})).toBeVisible();

  await page.getByRole('button', {name:'Edit'}).click();
  await expect(page.locator('.code-editor')).toHaveValue('# Overview\n\n'+table);
});

test('keeps long fenced code readable inside the conversation column', async ({ page }) => {
  const project = { id:1,name:'Demo',path:'/demo',model:'test',approval_mode:'assisted' };
  const longLine = `const result = "${'readable-content-'.repeat(80)}";`;

  await page.route('**/api/**', async route => {
    const p = new URL(route.request().url()).pathname;
    const json = (data: unknown) => route.fulfill({ json: data });
    if (p === '/api/projects') return json([project]);
    if (p === '/api/status') return json({ version:'test',ollama:{connected:true,models:['test']} });
    if (p === '/api/projects/1/sessions') return json([{id:1,project_id:1,title:'Chat'}]);
    if (p === '/api/sessions/1/messages') return json([{id:1,role:'assistant',content:`\`\`\`ts\n${longLine}\n\`\`\``}]);
    if (p === '/api/sessions/1/runs') return json([]);
    if (p === '/api/sessions/1/memory') return json({content:''});
    if (p === '/api/projects/1/tree') return json([]);
    if (p.endsWith('/git/diff')) return json({diff:''});
    if (p.endsWith('/git')) return json({changes:[],branches:[],remotes:[]});
    if (p.endsWith('/changes')) return json([]);
    return json([]);
  });

  await page.goto('/');

  const messages = page.locator('.messages');
  const bubble = page.locator('.message.assistant .bubble');
  const code = bubble.locator('pre');
  await expect(code).toContainText('readable-content');
  await expect.poll(() => messages.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  await expect.poll(() => code.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  await expect.poll(() => bubble.evaluate(element => element.getBoundingClientRect().right <= (element.parentElement?.getBoundingClientRect().right || 0))).toBe(true);
});


test('project AI model selectors show every detected Ollama model', async ({ page }) => {
  const models = Array.from({length: 28}, (_, index) => `model-${String(index + 1).padStart(2, '0')}:latest`);
  const project = {
    id:1,name:'Demo',path:'/demo',model:models[0],approval_mode:'assisted',
    instructions:'',git_author_name:'Olladex User',git_author_email:'olladex@local'
  };

  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    const json = (data: unknown) => route.fulfill({json:data});
    if (p === '/api/projects') return json([project]);
    if (p === '/api/status') return json({version:'test',ollama:{connected:true,models}});
    if (p === '/api/projects/1/sessions') return json([{id:1,project_id:1,title:'Chat'}]);
    if (p === '/api/sessions/1/messages') return json([]);
    if (p === '/api/sessions/1/runs') return json([]);
    if (p === '/api/sessions/1/memory') return json({content:''});
    if (p === '/api/projects/1/tree') return json([]);
    if (p === '/api/projects/1/changes') return json([]);
    if (p === '/api/projects/1/git/diff') return json({diff:''});
    if (p === '/api/projects/1/git') return json({changes:[],branches:[],remotes:[]});
    if (p === '/api/projects/1/intelligence') return json({name:'Demo',path:'/demo',file_count:0,total_bytes:0,languages:[],frameworks:[],test_commands:[],build_commands:[],symbols:[],instructions_configured:false});
    if (p === '/api/model-profiles') return json([]);
    if (p === '/api/projects/1/index') return json({files:0,embedded:0});
    if (p === '/api/settings/ollama') return json({
      ollama_url:'http://127.0.0.1:11434',
      ollama_model:models[0],
      ollama_embedding_model:models[1],
      connected:true,
      models,
      model_available:true,
      embedding_available:true
    });
    return json([]);
  });

  await page.goto('/');
  await page.locator('.inspector-tabs').getByRole('button', {name:'project'}).click();

  const defaultSelect = page.getByLabel('Default chat model');
  const effectiveSelect = page.getByLabel('Effective project model');

  await expect(defaultSelect).toBeVisible();

  // The Ollama settings request is loaded asynchronously after the project
  // panel renders. Assert option values after that request has populated the
  // selectors rather than reading their initial configured-only state.
  await expect.poll(async () => defaultSelect.locator('option').count()).toBeGreaterThanOrEqual(models.length + 1);
  await expect.poll(async () => effectiveSelect.locator('option').count()).toBeGreaterThanOrEqual(models.length + 1);

  const defaultOptions = await defaultSelect.locator('option').evaluateAll(
    options => options.map(option => (option as HTMLOptionElement).value)
  );
  const effectiveOptions = await effectiveSelect.locator('option').evaluateAll(
    options => options.map(option => (option as HTMLOptionElement).value)
  );

  for (const model of models) {
    expect(defaultOptions).toContain(model);
    expect(effectiveOptions).toContain(model);
  }
});


test('development slash command executes structured action without starting an LLM run', async ({ page }) => {
  const project = { id:1,name:'Demo',path:'/demo',model:'test',approval_mode:'assisted' };
  let runStarted = false;
  let actionCalled = false;

  await page.route('**/api/**', async route => {
    const p = new URL(route.request().url()).pathname;
    const json = (data: unknown) => route.fulfill({json:data});
    if (p === '/api/projects') return json([project]);
    if (p === '/api/status') return json({version:'test',ollama:{connected:true,models:['test']}});
    if (p === '/api/projects/1/sessions') return json([{id:1,project_id:1,title:'Chat'}]);
    if (p === '/api/sessions/1/messages') return json([]);
    if (p === '/api/sessions/1/runs' && route.request().method() === 'POST') {
      runStarted = true;
      return json({id:99,status:'running'});
    }
    if (p === '/api/sessions/1/runs') return json([]);
    if (p === '/api/sessions/1/development-action') {
      actionCalled = true;
      return json({
        action:'status',
        report:{},
        messages:[
          {id:10,session_id:1,role:'user',content:'/status',activities:[]},
          {id:11,session_id:1,role:'assistant',content:'Development action: /status\nCurrent item: DEV-001 — Verified Development',activities:[]},
        ],
      });
    }
    if (p === '/api/sessions/1/memory') return json({content:''});
    if (p === '/api/projects/1/tree') return json([]);
    if (p.endsWith('/git/diff')) return json({diff:''});
    if (p.endsWith('/git')) return json({changes:[],branches:[],remotes:[]});
    if (p.endsWith('/changes')) return json([]);
    return json([]);
  });

  await page.goto('/');
  await page.getByRole('textbox', {name:'Message Olladex'}).fill('/status');
  await page.getByRole('button', {name:'Send', exact:true}).click();

  await expect.poll(() => actionCalled).toBe(true);
  await expect.poll(() => runStarted).toBe(false);
  await expect(page.getByText('Development action: /status', {exact:false})).toBeVisible();
  await expect(page.getByText('DEV-001 — Verified Development', {exact:false})).toBeVisible();
});
