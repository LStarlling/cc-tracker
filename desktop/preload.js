// 安全桥：只暴露渲染层需要的能力（contextIsolation 下）。
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktopBridge', {
  setIgnore: (ignore) => ipcRenderer.send('set-ignore', ignore),
  hide: () => ipcRenderer.send('hide-mascot'),
  focusSession: (id) => ipcRenderer.invoke('focus-session', id),
  onBusy: (cb) => ipcRenderer.on('busy', (_e, busy) => cb(busy)),
  onActivity: (cb) => ipcRenderer.on('activity', (_e, act) => cb(act)),
  onDone: (cb) => ipcRenderer.on('mascot-done', (_e, payload) => cb(payload)),
});
