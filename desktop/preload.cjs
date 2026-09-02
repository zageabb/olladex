const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("olladexDesktop", Object.freeze({
  platform: process.platform,
  versions: Object.freeze({ chrome: process.versions.chrome, electron: process.versions.electron }),
  updates: Object.freeze({
    getState: () => ipcRenderer.invoke("olladex:update-state"),
    check: () => ipcRenderer.invoke("olladex:check-updates"),
    onStatus: (callback) => {
      const listener = (_event, state) => callback(state);
      ipcRenderer.on("olladex:update-status", listener);
      return () => ipcRenderer.removeListener("olladex:update-status", listener);
    },
  }),
}));
