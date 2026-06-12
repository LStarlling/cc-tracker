"""会话状态机 + 进程内注册表（cc-tracker 的核心）。

把 Claude Code（或 Codex）的生命周期事件，归并成每个会话的一个稳定状态：
    idle    空闲（已注册 / 一轮答完）
    working 进行中（用户发了指令，agent 在干活）
    waiting 等你输入（被授权弹窗 / 空闲提示阻塞）—— 最有价值的信号
    error   出错（一轮以 API 错误结束）

并维护一个单调递增的 done_seq + last_done 指针（沿用 dashboard 萌宠的完成通知机制），
桌面浮标据 done_seq 增长弹"完成"提醒。全部在内存，进程级，线程安全。
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOCK = threading.Lock()
_SESSIONS: Dict[str, Dict[str, Any]] = {}
_DONE_SEQ = 0
_LAST_DONE: Optional[Dict[str, Any]] = None

# 窗口定位信息（term_pid/hwnd）只在 SessionStart（唯一的 command 型 hook）抓得到。
# 但会话可能「被剪枝(STALE/窗口暂判死) → 又被轻量 http 事件唤醒」而不经过新的 SessionStart，
# 那条路径拿不到窗口信息 → 重建出的会话无法聚焦。这份旁路缓存让定位信息跨剪枝存活，
# 唤醒时还原；窗口若真关了由 IsWindow 拦住，缓存陈旧无害。
_WINDOW_INFO: Dict[str, Dict[str, Any]] = {}

# 超过该时长没有任何事件 → 视为僵尸会话（CC 崩溃没发 SessionEnd），清掉避免浮标永远转圈
STALE_SECONDS = 3 * 3600

# 真正"卡着等你选择/确认"的通知类型——授权弹窗 / MCP 征询。
# 注意：**不含空闲提示**。一轮答完后 CC 还会发一条"在等你下一句"的空闲通知，那不是阻塞、不该变红。
WAITING_TYPES = {"permission_prompt", "elicitation_dialog"}

# 排序：等你输入 > 进行中 > 出错 > 空闲；同级按进入时间
_STATE_ORDER = {"waiting": 0, "working": 1, "error": 2, "idle": 3}


def _now() -> float:
    return time.time()


def _project_name(cwd: Optional[str]) -> str:
    if not cwd:
        return "未知项目"
    try:
        name = Path(cwd).name
        return name or str(cwd)
    except Exception:
        return str(cwd)


def _touch(sid: str, cwd: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    """取出会话（不存在则建），刷新存活时间，写入非空的额外字段。调用方已持锁。"""
    s = _SESSIONS.get(sid)
    if s is None:
        cached = _WINDOW_INFO.get(sid) or {}   # 剪枝前抓到的窗口定位，唤醒时还原 → 仍可聚焦
        s = {
            "id": sid,
            "project": _project_name(cwd),
            "cwd": cwd,
            "state": "idle",
            "term_pid": cached.get("term_pid"),
            "hwnd": cached.get("hwnd"),
            "sub": 0,
            "since": _now(),
            "last_seen": _now(),
        }
        _SESSIONS[sid] = s
    s["last_seen"] = _now()
    if cwd and not s.get("cwd"):
        s["cwd"] = cwd
        s["project"] = _project_name(cwd)
    for k, v in extra.items():
        if v is not None:
            s[k] = v
    return s


def _event_name(payload: Dict[str, Any]) -> str:
    return str(payload.get("event") or payload.get("hook_event_name") or "").strip()


def handle_event(payload: Dict[str, Any]) -> None:
    """收一条 hook/notify 事件，推进对应会话的状态机。"""
    global _DONE_SEQ, _LAST_DONE
    event = _event_name(payload)
    sid = payload.get("session_id") or payload.get("sessionId")
    if not sid:
        return
    sid = str(sid)
    cwd = payload.get("cwd")
    source = payload.get("source") or "claude"

    with _LOCK:
        if event == "SessionStart":
            s = _touch(sid, cwd, term_pid=payload.get("term_pid"), hwnd=payload.get("hwnd"))
            s["state"] = "idle"
            s["since"] = _now()
            if s.get("term_pid") or s.get("hwnd"):
                _WINDOW_INFO[sid] = {"term_pid": s.get("term_pid"), "hwnd": s.get("hwnd")}

        elif event == "UserPromptSubmit":
            s = _touch(sid, cwd)
            s["state"] = "working"
            s["since"] = _now()

        elif event == "Notification":
            ntype = (payload.get("notification_type") or "").strip()
            s = _touch(sid, cwd)
            # 区分"卡着等你确认" vs "答完在等你下一句"：
            #  - 带类型（未来 CC 才有）：按白名单。
            #  - 不带类型（当前 CC 只给 message）：靠状态机——权限/确认弹窗只在一轮进行中(working)
            #    插进来；一轮已结束(idle/error)后到的通知=空闲提示，不是阻塞、不变红。
            blocking = (ntype in WAITING_TYPES) if ntype else (s["state"] in ("working", "waiting"))
            if blocking:
                s["state"] = "waiting"
                s["since"] = _now()

        elif event == "PostToolUse":
            # 一个工具刚跑完 = agent 又在干活了。授权弹窗批准后 CC 不发"已恢复"事件，
            # 而被批准的那个工具执行完会触发它自己的 PostToolUse——这是唯一能拿到的恢复信号。
            # 只把 waiting 拉回 working（不从 idle 复活，防 Stop 之后到的乱序 PostToolUse 把已完成会话弄回忙）：
            # 否则红态会一直挂到 Stop，压住本会话/别人的"完成"绿提醒。
            s = _touch(sid, cwd)
            if s["state"] == "waiting":
                s["state"] = "working"
                s["since"] = _now()

        elif event == "Stop":
            s = _touch(sid, cwd)
            s["state"] = "idle"
            _DONE_SEQ += 1
            _LAST_DONE = {"title": f"{s['project']} 完成 ✅", "session_id": sid, "source": source}

        elif event == "StopFailure":
            s = _touch(sid, cwd)
            s["state"] = "error"
            s["since"] = _now()
            _DONE_SEQ += 1
            _LAST_DONE = {"title": f"{s['project']} 出错 ⚠️", "session_id": sid, "source": source}

        elif event == "SubagentStart":
            s = _touch(sid, cwd)
            s["sub"] = int(s.get("sub", 0)) + 1
            if s["state"] == "idle":
                s["state"] = "working"

        elif event == "SubagentStop":
            s = _touch(sid, cwd)
            s["sub"] = max(0, int(s.get("sub", 0)) - 1)

        elif event == "SessionEnd":
            _SESSIONS.pop(sid, None)
            _WINDOW_INFO.pop(sid, None)   # 会话真正结束 → 缓存一并清掉

        else:
            # 未知事件：仅刷新存活，不改状态
            _touch(sid, cwd)


def _pid_alive(pid: int) -> bool:
    """Windows：pid 是否仍存活。OpenProcess 拿不到句柄即视为已退出。"""
    try:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:
        return True  # 探测失败宁可保留，交给 STALE 兜底


def _session_alive(s: Dict[str, Any]) -> bool:
    """会话是否还活着。核心信号 = 捕获到的控制台窗口句柄是否仍是一个有效窗口：
    关窗 / 杀进程后该窗口即销毁（conhost 是终端窗本身；Windows Terminal 是该 tab 的
    ConPTY 伪控制台窗，按 tab 独立）。没有 hwnd 时退化到 term_pid 进程存活。
    非 Windows 无此信号，返回 True 交给 STALE 兜底。"""
    if not sys.platform.startswith("win"):
        return True
    hwnd = s.get("hwnd")
    if hwnd:
        try:
            import ctypes

            return bool(ctypes.windll.user32.IsWindow(int(hwnd)))
        except Exception:
            return True
    pid = s.get("term_pid")
    if pid:
        return _pid_alive(int(pid))
    return True


def _prune() -> None:
    """清掉已死会话（关窗/杀进程）和长时间无事件的僵尸会话。调用方已持锁。"""
    now = _now()
    dead = []   # (sid, alive)：alive=False 表示窗口已销毁，缓存失效需一并清
    for sid, s in _SESSIONS.items():
        alive = _session_alive(s)
        if (now - s.get("last_seen", now) > STALE_SECONDS) or not alive:
            dead.append((sid, alive))
    for sid, alive in dead:
        _SESSIONS.pop(sid, None)
        if not alive:
            _WINDOW_INFO.pop(sid, None)   # 窗口没了→缓存陈旧；STALE 但窗口还在则保留以便唤醒后恢复聚焦


def activity() -> Dict[str, Any]:
    """桌面浮标轮询的聚合视图。字段对齐 dashboard 萌宠的 /api/activity，并扩展 waiting/sessions。"""
    with _LOCK:
        _prune()
        sessions: List[Dict[str, Any]] = []
        working = waiting = 0
        for s in _SESSIONS.values():
            st = s["state"]
            if st == "working":
                working += 1
            elif st == "waiting":
                waiting += 1
            sessions.append({
                "id": s["id"],
                "project": s["project"],
                "state": st,
                "since": s["since"],
                "focusable": bool(s.get("term_pid") or s.get("hwnd")),
            })
        sessions.sort(key=lambda x: (_STATE_ORDER.get(x["state"], 9), x["since"]))
        return {
            "busy": working > 0,        # 雷达扫描 = 有会话在干活
            "working": working,
            "waiting": waiting,         # 红色急态徽章 = 有会话在等你
            "done_seq": _DONE_SEQ,
            "last_done": _LAST_DONE,
            "sessions": sessions,
        }


def focus_target(sid: str) -> Optional[Dict[str, Any]]:
    """取某会话的终端定位信息（供 /focus 把窗口拉到前台）。"""
    with _LOCK:
        s = _SESSIONS.get(str(sid))
        if not s:
            return None
        if not _session_alive(s):
            # 会话已死（关窗/杀进程）：剔除，别回退去聚焦共享的终端宿主窗口
            _SESSIONS.pop(str(sid), None)
            return None
        return {"term_pid": s.get("term_pid"), "hwnd": s.get("hwnd")}


def first_waiting() -> Optional[str]:
    with _LOCK:
        cand = [s for s in _SESSIONS.values() if s["state"] == "waiting"]
        cand.sort(key=lambda s: s["since"])
        return cand[0]["id"] if cand else None
