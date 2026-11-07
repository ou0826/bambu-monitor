"""开机自启（写 HKCU Run 键）。"""
from __future__ import annotations

import logging
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
