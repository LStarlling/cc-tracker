#!/usr/bin/env python3
"""Claude Code SessionStart hook：捕获该会话所在的终端宿主窗口，上报给 cc-tracker。

http 型 hook 拿不到进程信息（它在 CC 的 HTTP 客户端里发），所以"找终端窗口"必须用一个
本地脚本完成：读 hook 的 stdin JSON，沿父进程链找到终端进程（cmd/powershell/WindowsTerminal/
VSCode…），把它的 pid + 控制台窗口句柄补进去，POST 给收集器 /event。

零三方依赖（只用标准库 + ctypes）。永不阻塞 CC —— 任何异常都吞掉、总是 exit 0。
"""
import json
import os
import sys
import urllib.request

SERVER = os.environ.get("CC_TRACKER_URL", "http://127.0.0.1:8765").rstrip("/") + "/event"

# 沿父链遇到这些 exe 即认定为"终端宿主"，记录其 pid（聚焦时把它的窗口拉到前台）
TERMINALS = {
    "windowsterminal.exe", "wt.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
    "conhost.exe", "code.exe", "code - insiders.exe", "cursor.exe",
    "alacritty.exe", "wezterm-gui.exe", "hyper.exe", "tabby.exe",
}


def _win_chain(pid):
    """[(pid, exe_lower), ...] 沿父进程链，含自身，最近在前。仅 Windows。"""
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002

    class PE32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    k = ctypes.windll.kernel32
    snap = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    info = {}
    try:
        e = PE32()
        e.dwSize = ctypes.sizeof(PE32)
        if k.Process32First(snap, ctypes.byref(e)):
            while True:
                exe = e.szExeFile.decode("utf-8", "ignore").lower()
                info[e.th32ProcessID] = (e.th32ParentProcessID, exe)
                if not k.Process32Next(snap, ctypes.byref(e)):
                    break
    finally:
        k.CloseHandle(snap)

    chain = []
    cur = pid
    for _ in range(12):
        if cur not in info:
            break
        ppid, exe = info[cur]
        chain.append((cur, exe))
        if not ppid or ppid == cur:
            break
        cur = ppid
    return chain


def _console_hwnd():
    try:
        import ctypes
        from ctypes import wintypes
        k = ctypes.windll.kernel32
        k.GetConsoleWindow.restype = wintypes.HWND   # 64 位防句柄截断
        h = k.GetConsoleWindow()
        return int(h) if h else None
    except Exception:
        return None


def _foreground_terminal_hwnd():
    """会话刚启动时，承载它的终端通常正处于前台。抓前台窗口，并校验它确属某个终端进程
    （直接 pid 或其父链命中 TERMINALS）→ 返回这个**可见且按窗口唯一**的 hwnd。

    这是 Win11 下的关键：Windows Terminal 把多个窗口/标签塞进同一个进程，每个会话的
    GetConsoleWindow() 是隐藏的伪控制台窗（聚焦时被判无效），而前台窗口才是那个真正可见、
    可精确聚焦、且各窗口互不相同的 WT/conhost/VSCode 顶层窗口。
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        # 64 位下必须声明类型，否则 HWND 句柄被按 c_int 截断 → 存进去的 hwnd 是错的
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        fg_pid = int(wpid.value)
        if not fg_pid:
            return None
        # 前台窗口所属进程（或其父链）是不是终端宿主
        for _pid, exe in _win_chain(fg_pid):
            if exe in TERMINALS:
                return int(hwnd)
    except Exception:
        pass
    return None


# mac/linux：沿父进程链命中这些名字即认定为"终端宿主 app"（聚焦时把它激活到前台）。
# 取 ps 的 comm 末级名小写来比对（Terminal.app → terminal、iTerm2 → iterm2）。
_UNIX_TERMINALS = {
    "terminal", "iterm2", "iterm", "wezterm", "wezterm-gui", "alacritty", "kitty",
    "hyper", "tabby", "warp", "ghostty", "code", "code helper", "cursor",
    "konsole", "gnome-terminal", "gnome-terminal-", "xterm", "tilix", "rxvt",
}


def _unix_terminal_pid():
    """mac/linux：从本进程沿父进程链上溯，找到承载该会话的终端 app 进程 pid。
    用 `ps -o ppid=,comm=` 逐级读，命中 _UNIX_TERMINALS 即返回那一层的 pid——
    它是 GUI app 进程的 unix id，osascript `set frontmost ... unix id is X` 能把它激活到前台
    （多窗口/多 tab 终端只能到 app 层、切不到具体 tab，与 Windows Terminal 同属固有限制）。"""
    import subprocess

    try:
        cur = os.getpid()
        for _ in range(12):
            out = subprocess.run(
                ["ps", "-o", "ppid=,comm=", "-p", str(cur)],
                capture_output=True, text=True, timeout=2,
            ).stdout.strip()
            parts = out.split(None, 1)
            if len(parts) < 2:
                break
            ppid_s, comm = parts[0], parts[1]
            name = os.path.basename(comm).strip().lower()
            if name in _UNIX_TERMINALS or any(name.startswith(t) for t in _UNIX_TERMINALS):
                return cur
            ppid = int(ppid_s)
            if ppid <= 1 or ppid == cur:
                break
            cur = ppid
    except Exception:
        pass
    return None


def find_terminal():
    """返回 (term_pid, hwnd)。
    Windows：hwnd 优先取**可见的前台终端窗口**（按窗口唯一、可精确聚焦），取不到再退回
      GetConsoleWindow()（独立 conhost 时可见、WT 时是隐藏伪控制台）。
    mac/linux：无窗口句柄，只沿父链抓终端 app 的 pid（聚焦时按 pid 激活该 app）。"""
    if not sys.platform.startswith("win"):
        return _unix_terminal_pid(), None
    hwnd = _foreground_terminal_hwnd() or _console_hwnd()
    try:
        for pid, exe in _win_chain(os.getpid()):
            if exe in TERMINALS:
                return pid, hwnd
    except Exception:
        pass
    return None, hwnd


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    payload["event"] = payload.get("hook_event_name") or "SessionStart"
    payload["source"] = "claude"
    term_pid, hwnd = find_terminal()
    if term_pid:
        payload["term_pid"] = term_pid
    if hwnd:
        payload["hwnd"] = hwnd
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            SERVER, data=data, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=1.5).read()
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
