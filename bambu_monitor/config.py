"""配置读写。

配置文件位置: %APPDATA%\\BambuMonitor\\config.json
"""
from __future__ import annotations

import copy
import json
import os
import sys
import threading
from pathlib import Path

APP_NAME = "BambuMonitor"
APP_TITLE = "拓竹打印监控"

DEFAULT_CONFIG = {
    "app": {
        # 主界面「主页」按钮跳转的地址（可改成你自己的 fork 地址）
        "homepage_url": "https://github.com/ou0826/bambu-monitor",
        # 界面语言：zh / en
        "language": "zh",
    },
    "printer": {
        "host": "",
        "serial": "",
        "access_code": "",
        "name": "",
        # 机型：留空=自动识别（连上打印机后从 get_version 读），也可手动指定
        "model": "",
    },
    "notify": {
        "toast": True,          # 系统通知中心（右下角横幅）
        "popup": True,          # 置顶弹窗
        "popup_seconds": 20,
        "sound": True,
        "volume": 80,           # 0-100
        "repeat_need_action": True,   # 需要人工处理时重复提醒
        "repeat_interval": 60,        # 秒
        # 事件开关
        "on_start": False,
        "on_finish": True,
        "on_fail": True,
        "on_pause": True,
        "on_cancel": False,
        "on_filament": True,    # 换料 / 进料退料
        "on_hms": True,         # 打印机告警（HMS）
        "on_offline": True,     # 连接断开
    },
    "behavior": {        "auto_connect": True,
        "reconnect": True,
        "start_minimized": False,
        "autostart": False,
        # 跟随 Bambu Studio：它一启动，本程序就自动弹出并连接
        "follow_bambu_studio": True,
        # 它关掉时是否把本程序最小化（默认保持可见）
        "hide_when_bambu_closes": False,
        # 点窗口右上角 X 时：False=缩到任务栏继续后台监控（推荐），True=直接退出
        "exit_on_close": False,
        "pushall_interval": 90,   # 秒，定期拉全量状态（P1 系列只增量上报）
        "offline_alert_seconds": 120,
    },
    # 云端模式：打印机和电脑不在同一网络时，通过拓竹云中转
    "cloud": {
        "enabled": False,
        "account": "",
        "token": "",
        "uid": "",
        "region": "China",
        "serial": "",
        "model": "",
        "name": "",
        "remember_account": True,
    },
    "window": {
        "geometry": "",
    },
}


def _candidates() -> list[Path]:
    out: list[Path] = []
    base = os.environ.get("APPDATA")
    if base:
        out.append(Path(base) / APP_NAME)
    # 绿色/便携模式：exe 同目录下的 data/
    if getattr(sys, "frozen", False):
        out.append(Path(sys.executable).resolve().parent / "data")
    tmp = os.environ.get("TEMP") or os.environ.get("TMP")
    if tmp:
        out.append(Path(tmp) / APP_NAME)
    out.append(Path.cwd() / APP_NAME)
    return out


_cached_dir: Path | None = None


def app_dir() -> Path:
    """配置/日志目录：优先 %APPDATA%，不可写时自动降级。"""
    global _cached_dir
    if _cached_dir is not None:
        return _cached_dir
    last_err: Exception | None = None
    for d in _candidates():
        writable = False
        try:
            d.mkdir(parents=True, exist_ok=True)
            # 目录存在不等于可写，实际写一个探针文件确认
            probe = d / ".write_probe"
            probe.write_text("1", encoding="utf-8")
            probe.unlink(missing_ok=True)
            writable = True
        except OSError as e:
            last_err = e
        # 只读但已有配置的情况也要用，否则用户会看到「配置消失」
        if writable or (d.is_dir() and (d / "config.json").exists()):
            _cached_dir = d
            return d
    # 全都不可写时的最后兜底，避免程序直接崩掉
    _cached_dir = Path(".")
    print(f"警告: 无法创建数据目录（{last_err}），改用当前目录")
    return _cached_dir


def _sub(name: str) -> Path:
    """app_dir 下建子目录，失败时退回临时目录。"""
    d = app_dir() / name
    try:
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError:
        tmp = os.environ.get("TEMP") or os.environ.get("TMP") or "."
        alt = Path(tmp) / APP_NAME / name
        try:
            alt.mkdir(parents=True, exist_ok=True)
            return alt
        except OSError:
            return app_dir()


def config_path() -> Path:
    return app_dir() / "config.json"


def log_dir() -> Path:
    return _sub("logs")


def sound_dir() -> Path:
    return _sub("sounds")


def _deep_fill(dst: dict, src: dict) -> dict:
    """把默认配置补进用户配置。"""
    for k, v in src.items():
        if k not in dst:
            dst[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_fill(dst[k], v)
    return dst


class Config:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config_path()
        self._lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        self.load()

    # ---------- 读写 ----------
    def load(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        merged = copy.deepcopy(DEFAULT_CONFIG)
                        _deep_fill(raw, DEFAULT_CONFIG)
                        merged.update({})
                        self.data = raw
                except Exception:
                    # 配置损坏时保留默认值，不阻塞启动
                    self.data = copy.deepcopy(DEFAULT_CONFIG)
            _deep_fill(self.data, DEFAULT_CONFIG)

    def save(self) -> None:
        with self._lock:
            try:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                os.replace(tmp, self.path)
            except OSError as e:
                # 配置目录不可写时不应该让整个程序崩掉
                print(f"警告: 保存配置失败（{e}）")

    # ---------- 访问 ----------
    def get(self, section: str, key: str, default=None):
        with self._lock:
            sec = self.data.get(section) or {}
            return sec.get(key, default)

    def set(self, section: str, key: str, value, save: bool = True) -> None:
        with self._lock:
            sec = self.data.setdefault(section, {})
            sec[key] = value
        if save:
            self.save()

    def section(self, name: str) -> dict:
        with self._lock:
            return self.data.setdefault(name, {})

    # ---------- 便捷属性 ----------
    @property
    def printer(self) -> dict:
        return self.section("printer")

    @property
    def notify(self) -> dict:
        return self.section("notify")

    @property
    def behavior(self) -> dict:
        return self.section("behavior")

    @property
    def cloud(self) -> dict:
        return self.section("cloud")

    def has_printer(self) -> bool:
        p = self.printer
        return bool(p.get("host") and p.get("serial") and p.get("access_code"))
