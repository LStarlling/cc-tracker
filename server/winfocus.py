"""把某个终端进程的窗口拉到前台（按平台分派）。

Windows：纯 ctypes（零三方依赖）。已知 term_pid → 沿父链找到第一个拥有可见顶层窗口的祖先 →
AttachThreadInput 绕过前台锁 → SetForegroundWindow。
mac/linux：best-effort 桩（osascript / wmctrl），后续完善。

已知限制：分页式终端（Windows Terminal / VSCode 集成终端）多个会话共用同一个窗口，
只能把窗口拉到前台、无法切到具体那个 tab —— 这是终端无公开 API 的固有限制。
cmd / conhost / 独立窗口可精确聚焦。
"""
from __future__ import annotations

import subprocess
import sys
from typing import List, Optional, Set


def focus(term_pid: Optional[int] = None, hwnd: Optional[int] = None) -> bool:
    if sys.platform.startswith("win"):
        return _focus_windows(term_pid, hwnd)
    if sys.platform == "darwin":
        return _focus_mac(term_pid)
    return _focus_linux(term_pid)


# ---------------------------------------------------------------- Windows ----
def _hwnd_argtypes(user32) -> None:
    """声明所有以 HWND 为参数/返回的调用类型——否则 64 位下大句柄被截断为 c_int，
    表现为"窗口时而能聚焦、时而打不开"。一次设好，全模块受用。"""
    import ctypes
    from ctypes import wintypes

    H = wintypes.HWND
    user32.IsWindow.argtypes = [H]
    user32.IsWindowVisible.argtypes = [H]
    user32.IsIconic.argtypes = [H]
    user32.ShowWindow.argtypes = [H, ctypes.c_int]
    user32.BringWindowToTop.argtypes = [H]
    user32.SetForegroundWindow.argtypes = [H]
    user32.GetForegroundWindow.restype = H
    user32.GetWindowThreadProcessId.argtypes = [H, ctypes.POINTER(wintypes.DWORD)]


def _focus_windows(term_pid: Optional[int], hwnd: Optional[int]) -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    _hwnd_argtypes(user32)
    target = None
    if hwnd:
        try:
            h = int(hwnd)
            if user32.IsWindow(h) and user32.IsWindowVisible(h):
                target = h
        except Exception:
            target = None
    if target is None and term_pid:
        target = _find_main_window(int(term_pid))
    if not target:
        return False
    return _bring_to_front(target)


def _ancestor_pids(pid: int, max_depth: int = 12) -> List[int]:
    """沿父进程链（含自身）返回 pid 列表，最近的在前。"""
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
    parent: dict = {}
    try:
        e = PE32()
        e.dwSize = ctypes.sizeof(PE32)
        if k.Process32First(snap, ctypes.byref(e)):
            while True:
                parent[e.th32ProcessID] = e.th32ParentProcessID
                if not k.Process32Next(snap, ctypes.byref(e)):
                    break
    finally:
        k.CloseHandle(snap)

    chain: List[int] = []
    cur = pid
    for _ in range(max_depth):
        chain.append(cur)
        nxt = parent.get(cur)
        if not nxt or nxt == cur or nxt in chain:
            break
        cur = nxt
    return chain


def _windows_of_pid(pid: int) -> Optional[int]:
    """该 pid 拥有的可见、无 owner（顶层）窗口；优先有标题的。"""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    GW_OWNER = 4
    found: List = []  # (hwnd, title_len)

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _l):
        if not user32.IsWindowVisible(h):
            return True
        if user32.GetWindow(h, GW_OWNER):     # 有 owner = 非主窗口
            return True
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(wpid))
        if wpid.value == pid:
            found.append((h, user32.GetWindowTextLengthW(h)))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    if not found:
        return None
    found.sort(key=lambda t: t[1], reverse=True)
    return found[0][0]


def _find_main_window(pid: int) -> Optional[int]:
    # 沿父链由近及远，返回第一个拥有顶层窗口的祖先（避免命中 explorer 桌面窗口）
    for p in _ancestor_pids(pid):
        h = _windows_of_pid(p)
        if h:
            return h
    return None


def _bring_to_front(hwnd: int) -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    SW_RESTORE, SW_SHOW = 9, 5

    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    cur = kernel32.GetCurrentThreadId()
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    tgt_thread = user32.GetWindowThreadProcessId(hwnd, None)

    # 模拟一次 ALT 键：解除"非前台进程不得抢前台"的系统锁，让 SetForegroundWindow 真正生效
    # （否则常表现为窗口只在任务栏闪、不弹到前台 = 用户说的"点了开不了窗"）。
    KEYEVENTF_KEYUP, VK_MENU = 0x0002, 0x12
    try:
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    except Exception:
        pass

    attached: Set[int] = set()
    for t in (fg_thread, tgt_thread):
        if t and t != cur:
            user32.AttachThreadInput(cur, t, True)
            attached.add(t)
    try:
        user32.BringWindowToTop(hwnd)
        user32.ShowWindow(hwnd, SW_SHOW)
        ok = bool(user32.SetForegroundWindow(hwnd))
        if not ok:
            # 兜底：最小化再还原会强制把窗口带到前台（SetForegroundWindow 仍被系统拒时）
            user32.ShowWindow(hwnd, 6)          # SW_MINIMIZE
            user32.ShowWindow(hwnd, SW_RESTORE)
            ok = bool(user32.SetForegroundWindow(hwnd)) or user32.GetForegroundWindow() == hwnd
    finally:
        for t in attached:
            user32.AttachThreadInput(cur, t, False)
    return ok


# -------------------------------------------------------------- mac/linux ----
def _focus_mac(term_pid: Optional[int]) -> bool:
    if not term_pid:
        return False
    script = (
        'tell application "System Events" to set frontmost of '
        f"(first process whose unix id is {int(term_pid)}) to true"
    )
    try:
        return subprocess.run(["osascript", "-e", script], timeout=3).returncode == 0
    except Exception:
        return False


def _focus_linux(term_pid: Optional[int]) -> bool:
    if not term_pid:
        return False
    try:
        return subprocess.run(["wmctrl", "-ia", str(int(term_pid))], timeout=3).returncode == 0
    except Exception:
        return False
