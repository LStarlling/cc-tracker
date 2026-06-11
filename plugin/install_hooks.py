#!/usr/bin/env python3
"""把 cc-tracker 的 hooks 合并进 ~/.claude/settings.json（直装路径，免插件市场）。

用法：
    python install_hooks.py            安装/更新（幂等：先清掉旧的 cc-tracker 条目再写）
    python install_hooks.py --uninstall 卸载（移除所有 cc-tracker 条目）

为什么用 Python 合并而非 PowerShell：settings.json 里 hooks 是 事件→匹配组列表 的嵌套结构，
json 模块能精确保留用户已有的其它 hooks，PowerShell 改 JSON 易踩坑。
SessionStart 用本仓库 venv 的 python 跑 capture 脚本（绝对路径，确保解释器一定在）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EVENT_URL = "http://127.0.0.1:8765/event"
HTTP_EVENTS = [
    "UserPromptSubmit", "Notification", "PostToolUse", "Stop", "StopFailure",
    "SubagentStart", "SubagentStop", "SessionEnd",
]

REPO = Path(__file__).resolve().parent.parent          # cc-tracker/
CAPTURE = REPO / "plugin" / "scripts" / "capture_session.py"
SETTINGS = Path.home() / ".claude" / "settings.json"


def _venv_python() -> str:
    win = REPO / ".venv" / "Scripts" / "python.exe"
    nix = REPO / ".venv" / "bin" / "python"
    if win.exists():
        return str(win)
    if nix.exists():
        return str(nix)
    return sys.executable                               # 兜底：当前解释器


def _is_ours(group: dict) -> bool:
    for h in (group or {}).get("hooks", []):
        if h.get("type") == "http" and EVENT_URL in (h.get("url") or ""):
            return True
        if h.get("type") == "command" and "capture_session.py" in (" ".join(h.get("args") or []) + (h.get("command") or "")):
            return True
    return False


def _our_groups() -> dict:
    groups = {
        "SessionStart": {
            "hooks": [{
                "type": "command",
                "command": _venv_python(),
                "args": [str(CAPTURE)],
                "timeout": 10,
                "statusMessage": "cc-tracker: 登记会话",
            }],
        },
    }
    for ev in HTTP_EVENTS:
        groups[ev] = {"hooks": [{"type": "http", "url": EVENT_URL, "timeout": 5}]}
    return groups


def _load() -> dict:
    if SETTINGS.exists():
        try:
            return json.loads(SETTINGS.read_text(encoding="utf-8"))
        except Exception:
            print(f"[warn] {SETTINGS} 解析失败，将另存备份后重写")
            SETTINGS.rename(SETTINGS.with_suffix(".json.bak"))
    return {}


def _save(data: dict) -> None:
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _strip_ours(hooks: dict) -> None:
    for ev in list(hooks.keys()):
        kept = [g for g in hooks[ev] if not _is_ours(g)]
        if kept:
            hooks[ev] = kept
        else:
            del hooks[ev]


def install() -> None:
    data = _load()
    hooks = data.setdefault("hooks", {})
    _strip_ours(hooks)                                  # 幂等：先清旧
    for ev, group in _our_groups().items():
        hooks.setdefault(ev, []).append(group)
    _save(data)
    print(f"[ok] 已写入 {SETTINGS}")
    print(f"     SessionStart 用解释器：{_venv_python()}")
    print("     新开的 Claude Code 会话即生效（已开的需重启）。")


def uninstall() -> None:
    data = _load()
    hooks = data.get("hooks", {})
    _strip_ours(hooks)
    if not hooks:
        data.pop("hooks", None)
    _save(data)
    print(f"[ok] 已从 {SETTINGS} 移除 cc-tracker 条目")


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        install()
