const { app, BrowserWindow, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const API_PORT = "8001";
const UI_PORT = "5081";
const processes = [];

function rootPath() {
  return app.isPackaged ? process.resourcesPath : path.resolve(__dirname, "..");
}

function executable(name) {
  return process.platform === "win32" ? `${name}.exe` : name;
}

function startServices() {
  const root = rootPath();
  const dataRoot = path.join(app.getPath("userData"), "data");
  fs.mkdirSync(dataRoot, { recursive: true });
  const common = { ...process.env, OLLADEX_DATA_ROOT: dataRoot, OLLADEX_API_PORT: API_PORT };

  if (app.isPackaged) {
    processes.push(spawn(path.join(root, "api", executable("olladex-api")), [], { cwd: root, env: common, stdio: "inherit" }));
  } else {
    const python = process.platform === "win32" ? path.join(root, ".venv", "Scripts", "python.exe") : path.join(root, ".venv", "bin", "python");
    processes.push(spawn(python, ["-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", API_PORT], { cwd: root, env: common, stdio: "inherit" }));
  }

  const frontend = app.isPackaged ? path.join(root, "frontend") : path.join(root, "frontend", ".next", "standalone");
  processes.push(spawn(process.execPath, [path.join(frontend, "server.js")], {
    cwd: frontend,
    env: { ...process.env, ELECTRON_RUN_AS_NODE: "1", NODE_ENV: "production", HOSTNAME: "127.0.0.1", PORT: UI_PORT },
    stdio: "inherit",
  }));
}

async function waitFor(url, attempts = 80) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try { const response = await fetch(url); if (response.ok) return; } catch {}
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Olladex did not become ready at ${url}`);
}

async function createWindow() {
  await Promise.all([waitFor(`http://127.0.0.1:${API_PORT}/health`), waitFor(`http://127.0.0.1:${UI_PORT}`)]);
  const window = new BrowserWindow({
    width: 1500,
    height: 940,
    minWidth: 1050,
    minHeight: 680,
    backgroundColor: "#071a38",
    title: "Olladex",
    webPreferences: { preload: path.join(__dirname, "preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  window.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: "deny" }; });
  window.webContents.on("will-navigate", (event, url) => { if (!url.startsWith(`http://127.0.0.1:${UI_PORT}`)) { event.preventDefault(); shell.openExternal(url); } });
  await window.loadURL(`http://127.0.0.1:${UI_PORT}`);
}

function stopServices() {
  for (const child of processes.splice(0)) if (!child.killed) child.kill("SIGTERM");
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.whenReady().then(async () => {
    startServices();
    try { await createWindow(); } catch (error) { console.error(error); app.quit(); }
  });
  app.on("before-quit", stopServices);
  app.on("window-all-closed", () => { stopServices(); if (process.platform !== "darwin") app.quit(); });
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
}
