// ============================================================================
// cc-tracker · 桌面萌宠（Electron 主进程）—— 跨 Claude Code 会话的实时状态浮标。
//
// 铺满可视区的透明 / 无边框 / 置顶 / 点击穿透窗当画布，里面只画那颗苹果（复用萌宠组件）。
// 每 1.5s 轮询收集器 :8765/activity → 推给渲染层：
//   busy(working>0) → 雷达扫描 ; activity(sessions/waiting) → 面板+红色急态 ; done_seq 增长 → 完成提醒。
// 点会话行 / 急态徽章 → POST /focus 把那个终端窗口拉到前台。
// ============================================================================
const { app, BrowserWindow, Tray, Menu, ipcMain, screen, nativeImage } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

const BASE = process.env.CC_TRACKER_URL || 'http://127.0.0.1:8765';
const ACTIVITY_URL = new URL('/activity', BASE).href;
const FOCUS_URL = new URL('/focus', BASE).href;
const HEALTH_URL = new URL('/health', BASE).href;
const REPO = path.join(__dirname, '..');     // cc-tracker/

let win = null, tray = null, pollTimer = null, lastBusy = null, lastDoneSeq = -1;
const primary = () => screen.getPrimaryDisplay();

if (!app.requestSingleInstanceLock()) { app.quit(); }

// 独立 AppUserModelID + 显式 path/args：开机自启注册表项才会指向「本 app」而非裸 electron，
// 且不与同机其它 electron 应用（如上级项目的 dashboard/desktop）共用默认键互相覆盖。
app.setAppUserModelId('cc-tracker.float');
const LOGIN_OPTS = { path: process.execPath, args: [path.resolve(__dirname)] };

function createWindow() {
  const wa = primary().workArea;     // 不含任务栏
  win = new BrowserWindow({
    x: wa.x, y: wa.y, width: wa.width, height: wa.height,
    transparent: true, frame: false, resizable: false, movable: false,
    skipTaskbar: true, hasShadow: false, alwaysOnTop: true, show: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false },
  });
  win.setAlwaysOnTop(true, 'floating');
  win.once('ready-to-show', () => win.showInactive());
  win.setIgnoreMouseEvents(true, { forward: true });
  win.loadFile(path.join(__dirname, 'host.html'));
}

// ---- IPC ----
ipcMain.on('set-ignore', (_e, ignore) => {
  if (win && !win.isDestroyed()) win.setIgnoreMouseEvents(!!ignore, { forward: true });
});
ipcMain.on('hide-mascot', () => { if (win) { win.hide(); refreshTrayMenu(); } });
ipcMain.handle('focus-session', async (_e, id) => {
  if (!id) return { ok: false, reason: 'no_id' };
  try {
    const r = await fetch(FOCUS_URL, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: id }),
    });
    return r.ok ? await r.json() : { ok: false, reason: 'http_' + r.status };
  } catch (e) { return { ok: false, reason: 'unreachable' }; }
});

// ---- 开机自启的关键：浮标启动时确保收集器在跑 ----
// 托盘「开机自启」只自启本浮标(electron)；收集器(:8765)不会跟着起 → 轮询全失败=黑屏。
// 故浮标起来先探测 /health，没起就用本仓库 venv 的 pythonw(无窗口)拉起 `python -m server`，
// detached + unref → 收集器脱离浮标独立存活（关浮标它仍在，hooks 始终有接收端）。
function venvPython() {
  const winw = path.join(REPO, '.venv', 'Scripts', 'pythonw.exe');  // 无控制台窗口
  const win = path.join(REPO, '.venv', 'Scripts', 'python.exe');
  const nix = path.join(REPO, '.venv', 'bin', 'python');
  if (process.platform === 'win32') {
    if (fs.existsSync(winw)) return winw;
    if (fs.existsSync(win)) return win;
  } else if (fs.existsSync(nix)) return nix;
  return null;     // venv 还没建（run.bat 没跑过）→ 放弃，由 run.bat 负责首次装依赖
}

async function collectorAlive() {
  try {
    const ctrl = new AbortController();
    const to = setTimeout(() => ctrl.abort(), 1500);
    const r = await fetch(HEALTH_URL, { signal: ctrl.signal });
    clearTimeout(to);
    return r.ok;
  } catch (e) { return false; }
}

async function ensureCollector() {
  if (await collectorAlive()) return;          // 已在跑（run.bat 起的 / 上次残留）→ 不重复起
  const py = venvPython();
  if (!py) return;
  try {
    const child = spawn(py, ['-m', 'server'], {
      cwd: REPO, detached: true, stdio: 'ignore', windowsHide: true,
    });
    child.unref();                             // 脱离父进程，浮标退出不连带杀收集器
  } catch (e) { /* 拉起失败：轮询会持续重试，无害 */ }
}

// ---- 轮询收集器：进度态 + 会话列表 + 完成提醒 ----
function startPolling() {
  let lastEnsure = 0;
  const tick = async () => {
    let act = null;
    try {
      const ctrl = new AbortController();
      const to = setTimeout(() => ctrl.abort(), 2000);
      const r = await fetch(ACTIVITY_URL, { signal: ctrl.signal });
      clearTimeout(to);
      if (r.ok) act = await r.json();
    } catch (e) { act = null; }
    // 自愈：收集器掉线（run.bat 的收集器窗口被关 / 崩溃 / 重启时序）→ 浮标作为常驻监工
    // 持续把它拉回来，不再是「只在启动时拉一次」。节流 10s，避免狂刷。
    if (!act) {
      const now = Date.now();
      if (now - lastEnsure > 10000) { lastEnsure = now; ensureCollector(); }
    }
    if (!win || win.isDestroyed()) return;

    const busy = !!(act && act.busy);
    if (busy !== lastBusy) { lastBusy = busy; win.webContents.send('busy', busy); }

    win.webContents.send('activity', act || { sessions: [], working: 0, waiting: 0 });

    // 完成提醒：done_seq 增长即推一次（启动时对齐基线，服务重启 seq 回退也重新对齐，不补历史）
    const doneSeq = act && typeof act.done_seq === 'number' ? act.done_seq : null;
    if (typeof doneSeq === 'number') {
      if (lastDoneSeq < 0 || doneSeq < lastDoneSeq) lastDoneSeq = doneSeq;
      else if (doneSeq > lastDoneSeq) {
        const delta = doneSeq - lastDoneSeq;
        lastDoneSeq = doneSeq;
        win.webContents.send('mascot-done', { delta, last: act.last_done });
      }
    }
  };
  tick();
  pollTimer = setInterval(tick, 1500);
}

// ---- 托盘 ----
// 运行时用 zlib 真生成一个红苹果托盘图标（纯 Node，无外部文件、无三方依赖）。
function trayIcon() {
  const zlib = require('zlib');
  const W = 32, SS = 3;
  const inC = (x, y, cx, cy, r) => (x - cx) ** 2 + (y - cy) ** 2 <= r * r;
  const sample = (x, y) => {
    if (inC(x, y, 13, 17, 1.2) || inC(x, y, 20, 17, 1.2)) return [31, 32, 36];      // 瞳孔
    if (inC(x, y, 12.5, 17, 2.7) || inC(x, y, 19.5, 17, 2.7)) return [255, 255, 255]; // 眼白
    if (((x - 21) ** 2) / 12 + ((y - 7) ** 2) / 4 <= 1) return [22, 163, 74];        // 叶子
    if (x >= 15 && x <= 17 && y >= 4 && y <= 11) return [124, 74, 34];               // 果柄
    if (inC(x, y, 12, 17, 8) || inC(x, y, 20, 17, 8) || inC(x, y, 16, 20, 8.5)) return [222, 42, 52];
    return null;
  };
  const raw = Buffer.alloc(W * (1 + W * 4));
  let p = 0;
  for (let y = 0; y < W; y++) {
    raw[p++] = 0;
    for (let x = 0; x < W; x++) {
      let r = 0, g = 0, b = 0, a = 0;
      for (let sy = 0; sy < SS; sy++) for (let sx = 0; sx < SS; sx++) {
        const c = sample(x + (sx + 0.5) / SS, y + (sy + 0.5) / SS);
        if (c) { r += c[0]; g += c[1]; b += c[2]; a += 255; }
      }
      const n = SS * SS;
      raw[p++] = Math.round(r / n); raw[p++] = Math.round(g / n);
      raw[p++] = Math.round(b / n); raw[p++] = Math.round(a / n);
    }
  }
  const crc32 = (buf) => {                 // 手写 CRC32（不依赖 zlib.crc32，兼容 Node 20）
    let c = ~0;
    for (let i = 0; i < buf.length; i++) {
      c ^= buf[i];
      for (let k = 0; k < 8; k++) c = (c & 1) ? (c >>> 1) ^ 0xEDB88320 : c >>> 1;
    }
    return ~c >>> 0;
  };
  const chunk = (type, data) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length, 0);
    const t = Buffer.from(type, 'ascii');
    const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(Buffer.concat([t, data])), 0);
    return Buffer.concat([len, t, data, crc]);
  };
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(W, 0); ihdr.writeUInt32BE(W, 4); ihdr[8] = 8; ihdr[9] = 6;
  const png = Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0)),
  ]);
  return nativeImage.createFromBuffer(png);
}
function buildTray() {
  let img;
  try { img = trayIcon(); } catch (e) { img = nativeImage.createEmpty(); }
  tray = new Tray(img);
  tray.setToolTip('cc-tracker · Claude Code 任务状态');
  refreshTrayMenu();
  tray.on('click', () => toggleShow());
}
function refreshTrayMenu() {
  const shown = win && win.isVisible();
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: shown ? '隐藏浮标' : '显示浮标', click: () => toggleShow() },
    { type: 'separator' },
    {
      label: '开机自启', type: 'checkbox',
      checked: app.getLoginItemSettings(LOGIN_OPTS).openAtLogin,
      click: (item) => { app.setLoginItemSettings({ ...LOGIN_OPTS, openAtLogin: item.checked }); refreshTrayMenu(); },
    },
    { type: 'separator' },
    { label: '退出', click: () => { app.isQuitting = true; app.quit(); } },
  ]));
}
function toggleShow() {
  if (!win) return;
  if (win.isVisible()) win.hide(); else win.showInactive();
  refreshTrayMenu();
}

app.on('second-instance', () => { if (win) { win.showInactive(); win.moveTop(); } });

app.whenReady().then(async () => {
  await ensureCollector();     // 先保证收集器在跑（开机自启场景下浮标负责拉起它）
  createWindow();
  buildTray();
  startPolling();
});

app.on('window-all-closed', () => { /* 常驻：由托盘"退出"控制 */ });
app.on('before-quit', () => { if (pollTimer) clearInterval(pollTimer); });
