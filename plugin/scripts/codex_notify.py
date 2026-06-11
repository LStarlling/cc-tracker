#!/usr/bin/env python3
"""Codex 适配器：把 OpenAI Codex CLI 的 notify 事件喂给同一只萌宠。

Codex 的 ~/.codex/config.toml 里：
    notify = ["python", "/绝对路径/cc-tracker/plugin/scripts/codex_notify.py"]
Codex 会把事件 JSON 作为 argv[1] 传进来（不是 stdin），目前只有 agent-turn-complete。
我们把它映射成一条 source=codex 的 Stop 事件 POST 给收集器 /event —— 于是 CC 和 Codex
的"完成"提醒汇到同一个浮标。零三方依赖。
"""
import json
import os
import sys
import urllib.request

SERVER = os.environ.get("CC_TRACKER_URL", "http://127.0.0.1:8765").rstrip("/") + "/event"


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
    try:
        ev = json.loads(raw)
    except Exception:
        ev = {}

    kind = ev.get("type") or "agent-turn-complete"
    payload = {
        "source": "codex",
        "event": "Stop" if kind == "agent-turn-complete" else "Notification",
        # Codex 一个 turn 没有持久 session 概念，用 turn-id / cwd 兜出一个稳定 id
        "session_id": "codex:" + str(ev.get("turn-id") or ev.get("cwd") or "default"),
        "cwd": ev.get("cwd"),
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(SERVER, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=1.5).read()
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
