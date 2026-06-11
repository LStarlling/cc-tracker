"""cc-tracker 收集器：收 Claude Code hook / Codex notify 事件，聚合成桌面浮标的实时状态。

路由：
  POST /event      收一条事件（hook http 直推 或 capture 脚本上报 或 codex adapter）
  GET  /activity   桌面浮标轮询的聚合视图 {busy, working, waiting, done_seq, last_done, sessions}
  POST /focus      把某会话的终端窗口拉到前台 {session_id}
  GET  /health     存活探针
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import store, winfocus

app = FastAPI(title="cc-tracker")

# Electron 渲染层从 file:// 跨源 fetch 本服务 → 放开 CORS（仅本机自用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True, "sessions": len(store.activity()["sessions"])}


@app.post("/event")
async def event(req: Request):
    try:
        payload = await req.json()
    except Exception:
        payload = {}
    store.handle_event(payload or {})
    return {"ok": True}


@app.get("/activity")
def activity():
    return store.activity()


@app.post("/focus")
async def focus(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    sid = body.get("session_id")
    tgt = store.focus_target(sid) if sid else None
    if not tgt:
        # 会话已被剪枝（窗口关了/进程没了）：告诉前端这是"已消失"，而非"聚焦失败可重试"
        return {"ok": False, "reason": "session_gone"}
    ok = winfocus.focus(term_pid=tgt.get("term_pid"), hwnd=tgt.get("hwnd"))
    return {"ok": ok, "reason": None if ok else "focus_failed"}
