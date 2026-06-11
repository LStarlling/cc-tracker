# cc-tracker · Claude Code 任务状态跟进

一只常驻桌面的萌宠浮标，跨你所有 Claude Code 会话实时显示三态 —— **进行中 / 已完成 / 等你输入**，
不用再频繁切窗口确认"那个跑完没、这个是不是卡着等我授权"。点"等你输入"的红色急态徽章，
**一键把那个被阻塞的终端窗口拉到前台**。

> 派生自本仓库「AI 洞察」的桌面萌宠（复用其状态镜面模型 + 萌宠组件），但**完全独立**：自带收集器(:8765)
> 与 Electron 外壳，不依赖 AI 洞察后端(:8001) 运行。

## 它和现有"通知插件"的区别

生态里 CCNotify / claude-notifier 之类都是**"叮一声"的瞬时通知**——告诉你"完成了"，但不告诉你
**现在哪个会话在跑、哪个正卡着等你**。cc-tracker 是一面**常驻状态镜面**：

| 信号 | 来自哪个 hook | 浮标表现 |
|---|---|---|
| 进行中 | `UserPromptSubmit` | 萌宠天线雷达扫描 |
| 等你输入（**最有价值**） | `Notification`(授权/空闲) | **红色脉动徽章** + 一键聚焦那个终端 |
| 已完成 | `Stop` | 绿气泡庆祝 + 未读徽章 |
| 出错 | `StopFailure` | 出错提示 |

> Codex 的 `notify` 只有 `agent-turn-complete` 一个事件，给不了"等你输入"这种中间态——这正是
> Claude Code hooks 生命周期更丰富的地方。

## 架构

```
Claude Code 会话(多个) ──hooks(http 直推 / SessionStart 抓窗口)──▶ 收集器 :8765 /event
                                                                          │ 会话状态机
桌面浮标(Electron) ──轮询 /activity (1.5s)──▶ {busy, working, waiting, done_seq, sessions}
    点会话行 / 急态徽章 ──▶ POST /focus ──▶ 把该终端窗口拉到前台(ctypes SetForegroundWindow)
```

- `server/` FastAPI 收集器：`store.py` 会话状态机、`winfocus.py` 终端聚焦、`app.py` 路由。
- `plugin/` Claude Code 插件：`hooks/hooks.json`（http 直推）、`scripts/capture_session.py`
  （SessionStart 抓终端窗口）、`install_hooks.py`（合并进 settings.json）。
- `desktop/` 复用萌宠组件的独立浮标（`assets/mascot.js` 加了"等你输入"红色急态）。

## 用法

```bat
:: 1) 起收集器 + 桌面浮标（首次自动建 venv、装 electron）
run.bat

:: 2) 把 hooks 接进 Claude Code（只需一次；幂等，可反复跑）
install-hooks.bat
::    卸载： install-hooks.bat --uninstall
```

macOS / Linux 用 `./run.sh` 和 `./install-hooks.sh`。装好后**新开**的 Claude Code 会话即生效
（已开的需重启）。

## 隐私

**只读会话状态，不读会话内容**。浮标里显示的"项目名"取自会话 `cwd` 的末级目录名，不解析
任何对话/transcript 文本。事件全程留在 `127.0.0.1`，不出本机。

## 已知限制（终端聚焦）

- **cmd / conhost / 独立窗口**：精确聚焦 ✅
- **Windows Terminal / VSCode 集成终端**：多个会话共用一个窗口，只能把**窗口**拉到前台、
  **切不到具体那个 tab**（终端无公开切 tab 的 API）。会话已存 PID/句柄，后续可针对性改进。
- v1 仅 Windows 原生聚焦；mac/linux 为 best-effort 桩。

## 扩展：也跟进 Codex

收集器的 `/event` 是通用入口。把 `plugin/scripts/codex_notify.py` 配进 Codex：

```toml
# ~/.codex/config.toml
notify = ["python", "C:/.../cc-tracker/plugin/scripts/codex_notify.py"]
```

Codex 的 `agent-turn-complete` 就会作为 `source=codex` 的完成事件汇进**同一只萌宠**。
