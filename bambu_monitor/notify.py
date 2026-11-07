"""Windows 通知：系统 Toast + 提示音。

设计要点
--------
* 零第三方依赖：Toast 走 PowerShell 调 WinRT，提示音走标准库 wave + winsound。
* 所有中文都通过 UTF-8 JSON 文件传给 PowerShell，绕开命令行编码问题。
* Toast 的音频设为 silent，声音由本模块自己播放，保证音色可控、可关闭。
"""
from __future__ import annotations

import json
import logging
import math
import os
import struct
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

from .config import app_dir, sound_dir

LOG = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000
APP_USER_MODEL_ID = "BambuMonitor.Desktop"
APP_DISPLAY_NAME = "拓竹打印监控"

_TOAST_PS = r"""
param([string]$PayloadPath)
$ErrorActionPreference = "Stop"
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$raw = [System.IO.File]::ReadAllText($PayloadPath, [System.Text.Encoding]::UTF8)
$p = $raw | ConvertFrom-Json
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text></text><text></text><text></text></binding></visual><audio silent="true"/></toast>')
$texts = $xml.GetElementsByTagName("text")
$texts.Item(0).InnerText = [string]$p.title
$texts.Item(1).InnerText = [string]$p.body
if ($p.footer) { $texts.Item(2).InnerText = [string]$p.footer }
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($p.app_id).Show($toast)
"""


# --------------------------------------------------------------------------
# 提示音合成
# --------------------------------------------------------------------------
def _synth(path: Path, notes, sr: int = 22050) -> None:
    """notes: [(频率Hz, 时长秒, 音量0-1), ...]"""
    frames = bytearray()
    for freq, dur, amp in notes:
        n = max(1, int(sr * dur))
        attack = max(1, int(sr * 0.008))
        release = max(1, int(sr * min(0.12, dur * 0.6)))
        for i in range(n):
            env = 1.0
            if i < attack:
                env = i / attack
            elif i > n - release:
                env = (n - i) / release
            t = i / sr
            s = (
                math.sin(2 * math.pi * freq * t)
                + 0.22 * math.sin(4 * math.pi * freq * t)
                + 0.08 * math.sin(6 * math.pi * freq * t)
            )
            v = s * amp * env
            v = max(-1.0, min(1.0, v))
            frames += struct.pack("<h", int(v * 32000))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(frames))


SOUND_SPECS = {
    # 打印完成：上行三音
    "finish": [(523.25, 0.16, 0.55), (659.25, 0.16, 0.55), (783.99, 0.16, 0.55), (1046.5, 0.42, 0.6)],
    # 报错/需要处理：下行双音 + 重音
    "error": [(440.0, 0.22, 0.7), (311.13, 0.26, 0.7), (233.08, 0.5, 0.75)],
    # 提醒（换料、暂停等）：两下轻响
    "attention": [(880.0, 0.1, 0.45), (0.0, 0.06, 0.0), (880.0, 0.1, 0.45), (1174.66, 0.22, 0.45)],
}


def ensure_sounds() -> dict[str, Path]:
    out = {}
    d = sound_dir()
    for name, notes in SOUND_SPECS.items():
        p = d / f"{name}.wav"
        if not p.exists() or p.stat().st_size < 1000:
            try:
                _synth(p, notes)
            except Exception as e:  # 合成失败不影响通知
                LOG.warning("生成提示音失败 %s: %s", name, e)
                continue
        out[name] = p
    return out


# --------------------------------------------------------------------------
# 通知器
# --------------------------------------------------------------------------
class Notifier:
    def __init__(self, cfg):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._sounds = {}
        self._ps1 = app_dir() / "notify.ps1"
        self._aumid_ok = False
        self._winsound = None
        if sys.platform == "win32":
            try:
                import winsound

                self._winsound = winsound
            except Exception:
                pass
            self._prepare()

    # ---------- 初始化 ----------
    def _prepare(self) -> None:
        try:
            self._ps1.write_text(_TOAST_PS, encoding="utf-8-sig")
        except OSError as e:
            LOG.warning("写入通知脚本失败: %s", e)
        self._register_aumid()
        self._sounds = ensure_sounds()

    def _register_aumid(self) -> None:
        """注册 AppUserModelID，否则 Toast 在部分机器上不显示应用名。"""
        try:
            import winreg

            key = winreg.CreateKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Classes\AppUserModelId" + "\\" + APP_USER_MODEL_ID,
            )
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_DISPLAY_NAME)
            icon = Path(__file__).resolve().parent.parent / "assets" / "app.ico"
            if icon.exists():
                winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon))
            winreg.CloseKey(key)
            self._aumid_ok = True
        except Exception as e:
            LOG.debug("注册 AUMID 失败: %s", e)

    # ---------- 对外接口 ----------
    def toast(self, title: str, body: str, footer: str = "") -> None:
        if not self.cfg.get("notify", "toast", True):
            return
        if sys.platform != "win32":
            print(f"[通知] {title} - {body}")
            return
        payload = {
            "title": title,
            "body": body,
            "footer": footer,
            "app_id": APP_USER_MODEL_ID,
        }
        path = Path(tempfile.gettempdir()) / f"bambumon-{os.getpid()}-{threading.get_ident()}.json"
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            LOG.warning("写通知载荷失败: %s", e)
            return

        def work():
            try:
                subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(self._ps1),
                        "-PayloadPath",
                        str(path),
                    ],
                    creationflags=CREATE_NO_WINDOW,
                    timeout=15,
                    capture_output=True,
                )
            except Exception as e:
                LOG.warning("Toast 发送失败: %s", e)
            finally:
                try:
                    path.unlink()
                except OSError:
                    pass

        threading.Thread(target=work, daemon=True, name="toast").start()

    def play(self, name: str) -> None:
        if not name:
            return
        if not self.cfg.get("notify", "sound", True):
            return
        if self._winsound is None:
            return
        wav = self._sounds.get(name)
        if not wav or not wav.exists():
            wav = ensure_sounds().get(name)
        if not wav:
            return
        try:
            self._winsound.PlaySound(
                str(wav), self._winsound.SND_FILENAME | self._winsound.SND_ASYNC
            )
        except Exception as e:
            LOG.debug("播放提示音失败: %s", e)

    def stop_sound(self) -> None:
        if self._winsound is not None:
            try:
                self._winsound.PlaySound(None, 0)
            except Exception:
                pass

    def notify(self, title: str, body: str, level: str = "info", sound: str = "", footer: str = "") -> None:
        """发一条通知：系统 Toast + 提示音。弹窗由 UI 层负责。"""
        self.toast(title, body, footer=footer)
        self.play(sound or ("error" if level == "error" else ""))
