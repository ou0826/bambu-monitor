"""开机自启（写 HKCU Run 键）。"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

LOG = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "BambuMonitor"


def _command() -> str:
    """构造开机启动命令：优先用打包后的 exe，其次 pythonw + main.py。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    root = Path(__file__).resolve().parent.parent
    entry = root / "main.py"
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{exe}" "{entry}" --minimized'


def is_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            try:
                winreg.QueryValueEx(key, VALUE_NAME)
                return True
            except FileNotFoundError:
                return False
    except Exception:
        return False


def set_enabled(enabled: bool) -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception as e:
        LOG.warning("设置开机自启失败: %s", e)
        return False


def stored_command() -> str | None:
    """读注册表里当前记录的自启命令。"""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            try:
                return winreg.QueryValueEx(key, VALUE_NAME)[0]
            except FileNotFoundError:
                return None
    except Exception:
        return None


def repair_if_stale() -> bool:
    """程序被移动/改名后，注册表里还指向旧路径 —— 自动改回当前路径。

    只在"已勾选自启"且"旧路径确实不存在"时动手，
    如果旧路径还在（可能是另一份拷贝），保持原样不管。
    """
    cmd = stored_command()
    if not cmd:
        return False
    current = _command()
    if cmd == current:
        return False
    m = re.match(r'"([^"]+)"', cmd.strip())
    target = m.group(1) if m else cmd.strip().split(" ")[0]
    try:
        if Path(target).exists():
            return False
    except (OSError, ValueError):
        pass
    if set_enabled(True):
        LOG.info("开机自启路径已自动修复: %s -> %s", cmd, current)
        return True
    return False
