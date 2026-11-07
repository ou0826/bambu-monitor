"""检测 Bambu Studio 是否在运行。

两条通道互为备份：
1. Toolhelp32 快照 —— 最常用，一次不到 1 毫秒；
2. EnumProcesses + QueryFullProcessImageName —— 在快照被裁剪/受限的环境里兜底。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _names_toolhelp() -> set[str]:
    names: set[str] = set()
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        return names
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        ok = k32.Process32FirstW(ctypes.c_void_p(snap), ctypes.byref(entry))
        while ok:
            names.add(entry.szExeFile.lower())
            ok = k32.Process32NextW(ctypes.c_void_p(snap), ctypes.byref(entry))
    finally:
        k32.CloseHandle(ctypes.c_void_p(snap))
    return names


def _names_enum_processes() -> set[str]:
    names: set[str] = set()
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    buf_size = 2048
    while buf_size <= 65536:
        arr = (wintypes.DWORD * buf_size)()
        needed = wintypes.DWORD()
        if not psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed)):
            return names
        count = needed.value // ctypes.sizeof(wintypes.DWORD)
        if count < buf_size:
            for i in range(count):
                pid = arr[i]
                if not pid:
                    continue
                h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if not h:
                    continue
                try:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(1024)
                    if k32.QueryFullProcessImageNameW(
                        ctypes.c_void_p(h), 0, buf, ctypes.byref(size)
                    ):
                        names.add(buf.value.rsplit("\\", 1)[-1].lower())
                finally:
                    k32.CloseHandle(ctypes.c_void_p(h))
            return names
        buf_size *= 2
    return names


def running_process_names() -> set[str]:
    """当前进程名集合（小写）。快照结果过少时自动换第二条通道。"""
    names: set[str] = set()
    try:
        names = _names_toolhelp()
    except Exception:
        names = set()
    if len(names) < 15:
        try:
            alt = _names_enum_processes()
            if len(alt) > len(names):
                names = alt
        except Exception:
            pass
    return names


def is_bambu_studio(name: str) -> bool:
    n = name.lower()
    if not n.endswith(".exe"):
        return False
    if "bambu" in n and ("studio" in n or "slicer" in n):
        return True
    return n in ("bambustudio.exe", "bambu studio.exe", "bambu_studio.exe")


def bambu_studio_window() -> bool:
    """兜底：找标题里同时含 bambu 与 studio 的可见窗口。

    只在进程表明显被裁剪时才用（某些受限环境里进程枚举拿不到完整列表）。
    """
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
    except OSError:
        return False
    hit: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if not user32.IsWindowVisible(h):
            return True
        n = user32.GetWindowTextLengthW(h)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(h, buf, n + 1)
        t = buf.value.lower()
        if "bambu" in t and "studio" in t:
            hit.append(1)
            return False
        return True

    try:
        user32.EnumWindows(cb, 0)
    except Exception:
        return bool(hit)
    return bool(hit)


def bambu_studio_running() -> bool:
    """两条通道都试一遍，任一条命中即视为运行中。"""
    for getter in (_names_toolhelp, _names_enum_processes):
        try:
            if any(is_bambu_studio(n) for n in getter()):
                return True
        except Exception:
            continue
    return False
