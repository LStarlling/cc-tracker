# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 这是什么

**cc-tracker** —— 一只常驻桌面的萌宠浮标，跨**所有** Claude Code 会话实时显示三态：**进行中 / 已完成 / 等你输入**。最有价值的信号是「等你输入」（授权弹窗/空闲阻塞）——点它的红色急态徽章，一键把那个被阻塞的终端窗口拉到前台。

与 CCNotify 之类「叮一声」的瞬时通知不同：cc-tracker 是一面**常驻状态镜面**——它利用 Claude Code hooks 生命周期更丰富的特点（不止「完成」事件，还有 `Notification` 这种「正卡着等你」的中间态）。

> 派生自上级目录「AI 洞察」项目的桌面萌宠（复用其状态镜面模型 + `mascot.js` 组件），但**完全独立**：自带收集器 + Electron 外壳，不依赖那个后端(:8001) 运行。**上级 `../CLAUDE.md` 是另一个项目，与本仓库无关，不要混淆。**

## 启动 / 接入（跨平台）

```bat
:: 起收集器(:8765) + 桌面浮标（首次自动建 .venv、npm install electron）
run.bat              ::（mac/linux: ./run.sh）

:: 把 hooks 合并进 ~/.claude/settings.json（幂等，可反复跑）；新开的 CC 会话才生效
install-hooks.bat            ::（mac/linux: ./install-hooks.sh）
install-hooks.bat --uninstall
```

- **开机自启**：托盘菜单「开机自启」勾上即可——它自启浮标(electron loginItem)，浮标作为常驻监工持续保活收集器。**一个开关 = 整套开机就绪**，无需给收集器单独注册自启项。两个 Windows 坑已规避：① loginItem 显式带 `path=electron.exe + args=[appDir]`（否则 boot 只起裸 electron、加载不了 app）；② `setAppUserModelId('cc-tracker.float')` 让注册表项独立命名，不与同机其它 electron 应用（如上级项目 `dashboard/desktop`）共用默认键 `electron.app.Electron` 互相覆盖。**改了 appId 后旧的开机自启勾选会读不到、显示未勾——需重启浮标后再勾一次**。
- **收集器是常驻 detached 进程**（关浮标不连带杀，保证 hooks 始终有接收端）。但这意味着「重跑 `run.bat`」默认连不到新代码、也清不掉内存里 stuck 的状态——所以 **`run.bat`/`run.sh` 启动时会先 `taskkill`/`kill` 掉 :8765 上的旧收集器再起新的**（`netstat`/`lsof` 定位 PID），让重跑 = 干净重启 + 加载最新代码。
- **收集器保活靠浮标自愈**：`main.js` 的轮询循环（1.5s）每次 fetch `/activity` 失败就调 `ensureCollector()`（节流 10s）——探 `/health`、没起就用 venv 的 `pythonw`(无控制台窗，回退 `python.exe`)把 `python -m server` detached 拉起。**不是只在启动拉一次**：收集器无论因何掉线（run.bat 的收集器窗被关 / 崩溃 / 重启时序），浮标都会在数秒内把它带回来。这条是「新开 CC 会话识别不到」类故障的根因防线——收集器死了，SessionStart 事件就 POST 进空，会话永远登记不上。
- **要求**：Python 3.9+（`py -3`）+ Node.js。**类型注解禁止 `X | None`，统一 `Optional[X]`**（沿用 3.9 兼容）。
- **无测试 / 无 lint / 无 formatter**：仓库不带任何配置。验证靠跑起来手动走链路——开几个 Claude Code 会话观察浮标三态、点急态徽章看是否聚焦。
- 收集器端口**硬编码** `127.0.0.1:8765`（`server/__main__.py`）；可用 `CC_TRACKER_URL` 环境变量覆盖各客户端指向。
- 单独跑收集器：`python -m server`。

## 架构（三段 + 一条数据流）

```
Claude Code 会话(多个) ──hooks──▶ 收集器 :8765 POST /event ──▶ 会话状态机(内存)
                                                                      │
桌面浮标(Electron) ──轮询 GET /activity (1.5s)──▶ {busy, working, waiting, done_seq, last_done, sessions}
    点会话行/急态徽章 ──▶ POST /focus ──▶ winfocus 把该终端窗口拉到前台
    /activity 拉不到 ──▶ ensureCollector() 探 GET /health、没起就拉起收集器（节流 10s 自愈）
```

| 目录 | 角色 | 关键文件 |
|---|---|---|
| `server/` | FastAPI 收集器 | `store.py` 会话状态机（核心）· `app.py` 4 个路由（`/event` 收事件 · `/activity` 聚合视图 · `/focus` 聚焦终端 · `/health` 存活探针，浮标 `collectorAlive()` 据它判收集器死活）· `winfocus.py` 终端聚焦 · `__main__.py` 入口 |
| `plugin/` | CC 插件 / hooks 接入 | `hooks/hooks.json` 声明 · `install_hooks.py` 合并进 settings · `scripts/capture_session.py` 抓窗口 · `scripts/codex_notify.py` Codex 适配 |
| `desktop/` | Electron 浮标 | `main.js` 主进程（轮询循环里持续自愈拉起收集器 + 托盘 + 开机自启 loginItem + 聚焦 IPC）· `host.html` 覆盖窗 · `assets/mascot.js` 萌宠组件（加了「等你输入」红色急态）· `preload.js` |

### 状态机是核心（`server/store.py`）

全部在**进程内存**、线程安全（一把 `_LOCK`）、不落盘。把 hook 事件归并成每会话一个稳定状态，事件→状态映射：

| hook 事件 | 状态 | 浮标表现 |
|---|---|---|
| `SessionStart` | `idle` | 登记会话（**并带终端 pid/hwnd**，见下） |
| `UserPromptSubmit` | `working` | 雷达扫描 |
| `Notification`（**进行中**到达=授权/确认弹窗） | `waiting` | **红色脉动徽章 + 一键聚焦** |
| `Notification`（**已 idle/error 后**到达=空闲提示） | 不变 | 忽略（"答完在等你下一句"≠阻塞） |
| `PostToolUse` | `waiting`→`working`（其余不动） | 清掉授权批准后的红态，别压住后续提醒 |
| `Stop` | `idle` + `done_seq+1` | 绿气泡庆祝 + 未读徽章 |
| `StopFailure` | `error` + `done_seq+1` | 出错提示 |
| `SubagentStart/Stop` | 维护 `sub` 计数 | — |
| `SessionEnd` | 删除会话 | — |

- **`done_seq` + `last_done`**：单调递增的完成通知指针（沿用 dashboard 萌宠机制）。浮标据 `done_seq` 增长弹一次提醒，**重启 seq 回退会重新对齐基线、不补历史**。每条完成的 `last_done.session_id` 在浮标侧压入 `doneStack`（`host.html`），**点天线徽章 = 从栈顶弹出最新一条、聚焦它、未读数减一**（多条完成逐次点击按时间从新到旧打开）；聚焦失败（窗口已关/拉前台失败）弹 toast 说明原因，不再"只清数字不开窗"。`/focus` 返回 `{ok, reason}`（`session_gone`/`focus_failed`）驱动该提示。
- **会话剪枝（两条信号，`_prune`/`_session_alive`）**：①**窗口存活**——`IsWindow(hwnd)`（退化到 `term_pid` 进程存活）判断，关窗/杀进程后**立即**剔除，不用等超时；这也是为什么 `SessionStart` 必须抓到 `hwnd`。②**STALE 兜底**——`STALE_SECONDS=3h` 没事件即剪掉（CC 崩溃没发 `SessionEnd`，否则浮标永远转圈）。`focus_target` 同样在会话已死时剔除并**拒绝回退**聚焦共享的终端宿主窗。非 Windows 无窗口信号，只靠 STALE。
- **waiting 怎么判（关键，别退回"凡通知即变红"）**：CC 的 `Notification` hook **不带 `notification_type`，只给 `message`**，所以靠**状态机自身**而非抠文案来分辨——授权/确认弹窗只在一轮**进行中（`working`）**插进来，而 CC 在一轮答完后还会发一条"在等你下一句"的空闲通知（彼时已 `idle`）。规则：`Notification` 到达时 `state∈{working,waiting}` 才置 `waiting`，`idle/error` 时忽略。否则每次完成都会误亮红灯（曾经的 bug）。`notification_type` 若哪天上游真带了，按 `WAITING_TYPES={permission_prompt,elicitation_dialog}` 白名单走。
- **waiting 怎么解（别让红态挂死压住后续提醒）**：授权批准后 CC **不发"已恢复"事件**，靠 **`PostToolUse`**（被批准的那个工具执行完触发它自己的 PostToolUse）把 `waiting`→`working`。前端 `host.html::reconcile` 里 waiting 优先级高于"完成"绿提醒——若红态一直挂到 `Stop`，会把本会话乃至**别的会话**的完成提醒一起压住，所以必须尽早解。`PostToolUse` **只清 waiting、不从 idle 复活**（防 `Stop` 之后乱序到达的 PostToolUse 把已完成会话弄回忙）。
- 排序：`waiting > working > error > idle`，同级按进入时间。

### 为什么 SessionStart 要单独跑一个本地脚本

http 型 hook 在 CC 的 HTTP 客户端里发，**拿不到进程信息**——而「聚焦那个终端」必须知道终端窗口。所以 `SessionStart` 用 **command 型** hook 跑 `capture_session.py`：读 hook stdin → 沿**父进程链**找到终端宿主进程（cmd/pwsh/WindowsTerminal/VSCode…，白名单匹配 exe 名）拿 `term_pid` → 抓 **hwnd**：优先 `_foreground_terminal_hwnd()`（会话刚启动时承载它的终端通常在前台，抓前台窗口并校验其属终端进程），取不到再退回 `GetConsoleWindow()`。其余 8 个事件（含 `PostToolUse`）都是轻量 **http 直推**。

> **为什么不直接用 `GetConsoleWindow()`**：Win11 默认终端是 Windows Terminal，它把多个窗口/标签塞进**同一个 WindowsTerminal.exe 进程**，每个会话的 `GetConsoleWindow()` 是**隐藏的伪控制台窗**（聚焦时 `IsWindowVisible` 判否 → 回退到共享的 `term_pid` → 永远挑同一个"标题最长"窗 = **开错窗**）。改抓**前台窗口**后，即便一个进程下多个窗口，也能拿到各自**可见且唯一**的顶层窗口 → 独立 cmd/WT/VSCode 窗口都能精确聚焦。WT 多 tab 仍是固有限制（无切 tab API），只能定位到窗口。

> 改动「能聚焦哪些终端」= 改 `capture_session.py::TERMINALS` 集合。两个脚本零三方依赖（标准库 + ctypes），任何异常都吞掉、永远 `exit 0`，绝不阻塞 CC。

### 终端聚焦的固有限制（`server/winfocus.py`）

Windows 纯 ctypes：`AttachThreadInput` 绕过前台锁 → `SetForegroundWindow`。
- **cmd / conhost / 独立窗口**：精确聚焦 ✅
- **Windows Terminal / VSCode 集成终端**：多会话共用一个窗口，只能拉**窗口**到前台、**切不到具体 tab**（终端无公开切 tab 的 API）——这是固有限制，不是 bug。
- mac/linux 是 best-effort 桩（osascript / wmctrl）。

## 接入机制要点（`plugin/install_hooks.py`）

- **直装路径**，不走插件市场：把 hooks **合并**进 `~/.claude/settings.json`（用 Python 而非 PowerShell，精确保留用户已有的其它 hooks）。
- **幂等**：每次先 `_strip_ours`（按 `/event` URL + `capture_session.py` 识别自己的条目）清旧再写。
- `SessionStart` 写的是**本仓库 `.venv` 的 python 绝对路径**（`_venv_python()`），确保解释器一定在。改 hook 集合时 `hooks.json`（插件市场版）和 `install_hooks.py`（直装版）两处要同步。

## 扩展：Codex

`/event` 是通用入口（payload 带 `source` 字段，`claude`/`codex`）。把 `plugin/scripts/codex_notify.py` 配进 `~/.codex/config.toml` 的 `notify`，Codex 的 `agent-turn-complete` 会作为 `source=codex` 的 `Stop` 事件汇进同一只萌宠。注意 Codex 事件走 **argv[1]** 不是 stdin，且无持久 session 概念（用 turn-id/cwd 兜一个稳定 id）。

## 隐私铁律

**只读会话状态，不读会话内容**。项目名只取会话 `cwd` 的末级目录名，绝不解析任何对话/transcript 文本。事件全程留在 `127.0.0.1`，不出本机。新增字段时守住这条线。
