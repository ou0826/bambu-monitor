"""界面：状态面板 + 置顶弹窗 + 设置。

界面线程只通过队列接收后台线程的消息，所有 tkinter 操作都在主线程完成。
"""
from __future__ import annotations

import logging
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from dataclasses import dataclass
from tkinter import messagebox, ttk

from . import __version__, autostart, cloud as cloud_mod, discovery, models
from .config import APP_TITLE, Config
from .mqtt_client import PrinterClient, probe
from .notify import Notifier
from .procwatch import bambu_studio_running, bambu_studio_window, is_bambu_studio, running_process_names
from .state import ERROR, SUCCESS, WARNING, Event, Watcher

LOG = logging.getLogger(__name__)

# ---------------- 配色 ----------------
BG = "#0E1014"
PANEL = "#171A21"
PANEL2 = "#1E222B"
LINE = "#2A2F3A"
TEXT = "#E8EAF0"
MUTED = "#8B93A7"
ACCENT = "#2ED573"
WARN = "#FFB020"
DANGER = "#FF4D4F"
BLUE = "#4C8DFF"
LEVEL_COLOR = {SUCCESS: ACCENT, ERROR: DANGER, WARNING: WARN, "info": BLUE}

# 输入里常见的隐形字符（从剪贴板/输入法带进来的），密码里混进去就会登录失败
_INVISIBLE = "\u200b\u200c\u200d\u2060\ufeff\u00a0\u0000"


def clean_input(text: str, strip_inner_space: bool = False) -> str:
    s = "".join(ch for ch in (text or "") if ch not in _INVISIBLE)
    if strip_inner_space:
        s = "".join(s.split())
    return s.strip()

EVENT_SWITCH = {
    "start": "on_start",
    "finish": "on_finish",
    "fail": "on_fail",
    "pause": "on_pause",
    "cancel": "on_cancel",
    "filament": "on_filament",
    "hms": "on_hms",
    "offline": "on_offline",
    "resume": None,   # 恢复打印不通知
    "online": None,
}

# 设置窗口里属于 behavior 段的键
BEHAVIOR_KEYS = {
    "auto_connect",
    "autostart",
    "start_minimized",
    "follow_bambu_studio",
    "hide_when_bambu_closes",
    "exit_on_close",
}


def pick_font() -> str:
    try:
        families = set(tkfont.families())
    except Exception:
        return "Microsoft YaHei UI"
    for name in ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "SimHei", "Arial"):
        if name in families:
            return name
    return "Arial"


def fmt_temp(v, target=None) -> str:
    try:
        cur = float(v)
    except (TypeError, ValueError):
        return "--"
    s = f"{cur:.0f}°C"
    try:
        t = float(target)
        if t > 0:
            s += f" / {t:.0f}°"
    except (TypeError, ValueError):
        pass
    return s


# --------------------------------------------------------------------------
# 置顶弹窗
# --------------------------------------------------------------------------
class AlertPopup(tk.Toplevel):
    _stack: list["AlertPopup"] = []

    def __init__(self, app: "App", ev: Event, seconds: int):
        super().__init__(app.root)
        self.app = app
        self.ev = ev
        self.seconds = max(5, int(seconds or 15))
        self._left = self.seconds
        self._job = None

        color = LEVEL_COLOR.get(ev.level, BLUE)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.98)
        except tk.TclError:
            pass
        self.configure(bg=color)

        body = tk.Frame(self, bg=PANEL)
        body.pack(fill="both", expand=True, padx=2, pady=2)

        head = tk.Frame(body, bg=PANEL)
        head.pack(fill="x", padx=16, pady=(14, 0))
        tk.Label(head, text=f"  {ev.title}", bg=PANEL, fg=color,
                 font=(app.ui_font, 12, "bold"), anchor="w").pack(side="left")

        msg = tk.Label(body, text=ev.body, bg=PANEL, fg=TEXT, font=(app.ui_font, 10),
                       wraplength=350, justify="left", anchor="w")
        msg.pack(fill="x", padx=16, pady=(6, 4))

        self.tip = tk.Label(body, text="", bg=PANEL, fg=MUTED, font=(app.ui_font, 9), anchor="w")
        self.tip.pack(fill="x", padx=16, pady=(0, 10))

        for w in (self, body, head, msg, self.tip):
            w.bind("<Button-1>", self._on_click)

        self.geometry("420x132")
        self._place()
        AlertPopup._stack.append(self)
        self._tick()

    # ---------- 布局 ----------
    def _place(self) -> None:
        try:
            idx = AlertPopup._stack.index(self)
        except ValueError:
            idx = 0
        sw = self.winfo_screenwidth()
        w, h = 420, 132
        # 放在右上角，避开右下角的系统通知
        x = sw - w - 24
        y = 84 + idx * (h + 10)
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(40, y)}")

    def _restack(self) -> None:
        sw = self.winfo_screenwidth()
        for i, p in enumerate(list(AlertPopup._stack)):
            try:
                p.geometry(f"420x132+{sw - 444}+{84 + i * 142}")
            except tk.TclError:
                pass

    # ---------- 定时 ----------
    def _tick(self) -> None:
        if not self.winfo_exists():
            return
        self.tip.configure(text=f"{self._left} 秒后自动关闭 · 点击打开面板")
        if self._left <= 0:
            self.close()
            return
        self._left -= 1
        self._job = self.after(1000, self._tick)

    def _on_click(self, _evt=None) -> None:
        self.app.show_window()
        self.close()

    def close(self) -> None:
        if self._job:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        try:
            AlertPopup._stack.remove(self)
        except ValueError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass
        AlertPopup._restack()


# --------------------------------------------------------------------------
# 设置窗口
# --------------------------------------------------------------------------
class SettingsDialog(tk.Toplevel):
    def __init__(self, app: "App"):
        super().__init__(app.root)
        self.app = app
        self.cfg = app.cfg
        self.f = app.ui_font
        self.title("设置")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(app.root)
        self.grab_set()
        self._vars: dict[str, tk.Variable] = {}
        self._found: list[dict] = []
        # 后台线程（扫描/测试连接）只往队列丢结果，主线程轮询更新界面
        self.q: queue.Queue = queue.Queue()
        self._build()
        self._center()
        self.after(120, self._poll)

    def _poll(self) -> None:
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "say":
                    self._say(item[1], item[2] if len(item) > 2 else MUTED)
                elif kind == "scan_done":
                    self._scan_done(item[1])
        except queue.Empty:
            pass
        except Exception:
            LOG.exception("设置窗口处理结果出错")
        try:
            self.after(120, self._poll)
        except tk.TclError:
            pass

    def _center(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{max(30, (sh - h) // 2 - 40)}")

    # ---------- 构件 ----------
    def _label(self, parent, text, **kw):
        return tk.Label(parent, text=text, bg=BG, fg=MUTED, font=(self.f, 9), anchor="w", **kw)

    def _entry(self, parent, key: str, value: str, show=None, width=28):
        var = tk.StringVar(value=value or "")
        self._vars[key] = var
        e = tk.Entry(parent, textvariable=var, bg=PANEL2, fg=TEXT, insertbackground=TEXT,
                     relief="flat", font=(self.f, 10), width=width, show=show,
                     highlightthickness=1, highlightbackground=LINE, highlightcolor=BLUE)
        return e

    def _check(self, parent, key: str, text: str, value: bool):
        var = tk.BooleanVar(value=bool(value))
        self._vars[key] = var
        return tk.Checkbutton(parent, text=text, variable=var, bg=BG, fg=TEXT, selectcolor=PANEL2,
                              activebackground=BG, activeforeground=TEXT, font=(self.f, 9),
                              bd=0, highlightthickness=0, anchor="w")

    def _build(self) -> None:
        pad = {"padx": 18}
        tk.Label(self, text="打印机连接", bg=BG, fg=TEXT, font=(self.f, 11, "bold")).pack(
            anchor="w", pady=(16, 6), **pad)

        conn = tk.Frame(self, bg=BG)
        conn.pack(fill="x", **pad)
        for i, (key, title, show) in enumerate(
            (("host", "IP 地址", None), ("serial", "序列号", None), ("access_code", "访问码", "•"))
        ):
            self._label(conn, title).grid(row=i, column=0, sticky="w", pady=4)
            self._entry(conn, key, self.cfg.printer.get(key, ""), show=show).grid(
                row=i, column=1, sticky="we", pady=4, padx=(10, 10))

        # 机型：默认自动识别，也可手动指定（识别不出来时用这个）
        self._label(conn, "机型").grid(row=3, column=0, sticky="w", pady=4)
        model_var = tk.StringVar(value=models.normalize(self.cfg.printer.get("model")) or "自动识别")
        self._vars["model"] = model_var
        ttk.Combobox(conn, textvariable=model_var, state="readonly", width=24,
                     values=["自动识别"] + models.CHOICES).grid(
            row=3, column=1, sticky="we", pady=4, padx=(10, 10))
        conn.columnconfigure(1, weight=1)

        tools = tk.Frame(self, bg=BG)
        tools.pack(fill="x", pady=(6, 0), **pad)
        self._btn(tools, "自动搜索打印机", self._scan).pack(side="left")
        self._btn(tools, "从 Bambu Studio 导入访问码", self._import_codes).pack(side="left", padx=8)
        self._btn(tools, "测试连接", self._test_conn).pack(side="left")

        self.scan_box = tk.Listbox(self, height=3, bg=PANEL2, fg=TEXT, relief="flat",
                                   font=(self.f, 9), highlightthickness=1, highlightbackground=LINE,
                                   selectbackground=BLUE)
        self.scan_box.pack(fill="x", pady=(8, 0), **pad)
        self.scan_box.bind("<<ListboxSelect>>", self._pick_found)

        tk.Frame(self, bg=LINE, height=1).pack(fill="x", pady=12, **pad)

        # ---- 跨网络（云端）----
        tk.Label(self, text="跨网络（云端）", bg=BG, fg=TEXT, font=(self.f, 11, "bold")).pack(
            anchor="w", **pad)
        crow = tk.Frame(self, bg=BG)
        crow.pack(fill="x", pady=(4, 0), **pad)
        self._check(crow, "cloud_enabled", "通过拓竹云连接（打印机不在同一网络时用）",
                    self.cfg.cloud.get("enabled", False)).pack(side="left")
        self._btn(crow, "登录 / 更换账号", self._open_cloud).pack(side="left", padx=12)
        tk.Label(self, text=self._cloud_status_text(), bg=BG, fg=MUTED, font=(self.f, 9),
                 anchor="w", justify="left", wraplength=500).pack(fill="x", padx=18, pady=(4, 0))

        tk.Frame(self, bg=LINE, height=1).pack(fill="x", pady=12, **pad)

        # ---- 通知 ----
        tk.Label(self, text="提醒方式", bg=BG, fg=TEXT, font=(self.f, 11, "bold")).pack(
            anchor="w", pady=(0, 6), **pad)
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", **pad)
        self._check(row, "toast", "系统通知", self.cfg.notify.get("toast", True)).pack(side="left")
        self._check(row, "popup", "置顶弹窗", self.cfg.notify.get("popup", True)).pack(side="left", padx=14)
        self._check(row, "sound", "提示音", self.cfg.notify.get("sound", True)).pack(side="left")
        self._check(row, "repeat_need_action", "需要处理时重复提醒",
                    self.cfg.notify.get("repeat_need_action", True)).pack(side="left", padx=14)

        row2 = tk.Frame(self, bg=BG)
        row2.pack(fill="x", pady=(8, 0), **pad)
        self._label(row2, "弹窗停留(秒)").pack(side="left")
        self._entry(row2, "popup_seconds", str(self.cfg.notify.get("popup_seconds", 20)), width=5).pack(
            side="left", padx=(6, 18))
        self._btn(row2, "试听/测试通知", self._test_notify).pack(side="left")

        tk.Label(self, text="触发事件", bg=BG, fg=TEXT, font=(self.f, 11, "bold")).pack(
            anchor="w", pady=(16, 6), **pad)
        grid = tk.Frame(self, bg=BG)
        grid.pack(fill="x", **pad)
        items = [
            ("on_start", "开始打印"), ("on_finish", "打印完成"), ("on_fail", "打印失败"),
            ("on_pause", "打印暂停"), ("on_cancel", "打印取消"), ("on_filament", "换料提醒"),
            ("on_hms", "故障告警"), ("on_offline", "连接断开"),
        ]
        for i, (key, text) in enumerate(items):
            self._check(grid, key, text, self.cfg.notify.get(key, True)).grid(
                row=i // 4, column=i % 4, sticky="w", padx=(0, 22), pady=3)

        tk.Frame(self, bg=LINE, height=1).pack(fill="x", pady=14, **pad)

        # ---- 行为 ----
        beh = tk.Frame(self, bg=BG)
        beh.pack(fill="x", **pad)
        self._check(beh, "auto_connect", "启动后自动连接打印机",
                    self.cfg.behavior.get("auto_connect", True)).pack(side="left")
        self._check(beh, "autostart", "开机自动启动",
                    autostart.is_enabled()).pack(side="left", padx=16)
        self._check(beh, "start_minimized", "启动时最小化",
                    self.cfg.behavior.get("start_minimized", False)).pack(side="left")

        beh2 = tk.Frame(self, bg=BG)
        beh2.pack(fill="x", padx=18, pady=(8, 0))
        self._check(beh2, "follow_bambu_studio", "打开 Bambu Studio 时自动显示并连接",
                    self.cfg.behavior.get("follow_bambu_studio", True)).pack(side="left")
        self._check(beh2, "hide_when_bambu_closes", "关闭 Bambu Studio 时最小化",
                    self.cfg.behavior.get("hide_when_bambu_closes", False)).pack(
            side="left", padx=16)

        beh3 = tk.Frame(self, bg=BG)
        beh3.pack(fill="x", padx=18, pady=(8, 0))
        self._check(beh3, "exit_on_close", "点关闭按钮时直接退出程序（默认只是缩到任务栏继续监控）",
                    self.cfg.behavior.get("exit_on_close", False)).pack(side="left")
        tk.Label(
            self, text="提示：勾了「开机自动启动 + 启动时最小化」，开机后本程序在后台待命，"
                       "你打开 Bambu Studio 它就会自己出来。",
            bg=BG, fg=MUTED, font=(self.f, 9), anchor="w", justify="left", wraplength=500,
        ).pack(fill="x", padx=18, pady=(6, 0))

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", pady=(18, 16), **pad)
        self._btn(foot, "保存", self._save, primary=True).pack(side="right")
        self._btn(foot, "取消", self.destroy).pack(side="right", padx=10)

        self.hint = tk.Label(self, text="", bg=BG, fg=MUTED, font=(self.f, 9), anchor="w")
        self.hint.pack(fill="x", padx=18, pady=(0, 12))

    def _btn(self, parent, text, cmd, primary=False):
        bg = ACCENT if primary else PANEL2
        fg = "#07110A" if primary else TEXT
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, relief="flat", bd=0,
                         font=(self.f, 9), padx=12, pady=6, activebackground=bg,
                         activeforeground=fg, cursor="hand2")

    # ---------- 动作 ----------
    def _say(self, text: str, color: str = MUTED) -> None:
        self.hint.configure(text=text, fg=color)

    def _scan(self) -> None:
        self._say("正在扫描局域网（约 5-10 秒）...", BLUE)
        self.scan_box.delete(0, tk.END)

        def work():
            try:
                found = discovery.discover(timeout=0.5)
            except Exception as e:
                found = []
                self.q.put(("say", f"扫描失败：{e}", DANGER))
            self.q.put(("scan_done", found))

        threading.Thread(target=work, daemon=True).start()

    def _scan_done(self, found: list[dict]) -> None:
        self._found = found
        if not found:
            self._say("没有发现打印机。请确认打印机已开机且与本机在同一局域网（或手动填写 IP）。", WARN)
            return
        codes = discovery.import_access_codes()
        for item in found:
            code = codes.get(item["serial"], "")
            self.scan_box.insert(
                tk.END,
                f"{item['host']}   序列号 {item['serial'] or '未知'}"
                f"{'   （已有访问码）' if code else ''}",
            )
        self._say(f"发现 {len(found)} 台，点击选择即可填入。", ACCENT)
        self.scan_box.selection_set(0)
        self._pick_found()

    def _pick_found(self, _evt=None) -> None:
        sel = self.scan_box.curselection()
        if not sel or sel[0] >= len(self._found):
            return
        item = self._found[sel[0]]
        codes = discovery.import_access_codes()
        self._vars["host"].set(item["host"])
        if item["serial"]:
            self._vars["serial"].set(item["serial"])
        code = codes.get(item["serial"], "")
        if code and not self._vars["access_code"].get():
            self._vars["access_code"].set(code)
            self._say("已填入 Bambu Studio 中保存的访问码。", ACCENT)

    def _import_codes(self) -> None:
        codes = discovery.import_access_codes()
        if not codes:
            self._say("没在 Bambu Studio 配置里找到访问码，请手动输入（打印机屏幕：设置 → 网络）。", WARN)
            return
        serial = self._vars["serial"].get().strip()
        if serial in codes:
            self._vars["access_code"].set(codes[serial])
            self._say(f"已填入序列号 {serial} 的访问码。", ACCENT)
        else:
            self._say("找到 %d 个访问码，但没有匹配当前序列号的，可先自动搜索。" % len(codes), WARN)

    def _open_cloud(self) -> None:
        self.grab_release()
        self.destroy()
        self.app.open_cloud_login()

    def _cloud_status_text(self) -> str:
        c = self.cfg.cloud
        if c.get("token"):
            acc = c.get("account") or "（已保存登录凭证）"
            dev = c.get("name") or c.get("serial", "")
            model = models.normalize(c.get("model")) or ""
            tail = f"｜设备 {dev}" + (f"（{model}）" if model else "")
            return f"状态：已登录 {acc}{tail}"
        return "状态：未登录。点“登录 / 更换账号”，填邮箱 → 发送验证码 → 填入邮件里的 6 位数字。"

    def _test_conn(self) -> None:
        host = self._vars["host"].get().strip()
        serial = self._vars["serial"].get().strip()
        code = self._vars["access_code"].get().strip()
        if not (host and serial and code):
            self._say("请先填写 IP、序列号、访问码。", WARN)
            return
        self._say("正在连接...", BLUE)

        def work():
            try:
                data = probe(host, serial, code, timeout=8)
                p = data.get("print", {})
                self.q.put(("say",
                            f"连接成功！当前状态 {p.get('gcode_state', '?')}，"
                            f"进度 {p.get('mc_percent', 0)}%", ACCENT))
            except Exception as e:
                msg = str(e)
                try:
                    if discovery.same_subnet(host) is False:
                        msg += (f"。原因：打印机 {host} 与本机（{discovery.local_networks_text()}）"
                                f"不在同一网络，本程序走局域网直连，跨网络连不上。"
                                f"把打印机连到同一个 WiFi 即可。")
                except Exception:
                    pass
                self.q.put(("say", f"连接失败：{msg}", DANGER))

        threading.Thread(target=work, daemon=True).start()

    def _test_notify(self) -> None:
        self.app.test_notification()

    def _save(self) -> None:
        host = self._vars["host"].get().strip()
        serial = self._vars["serial"].get().strip()
        code = self._vars["access_code"].get().strip()
        cloud_on = bool(self._vars.get("cloud_enabled").get()) if "cloud_enabled" in self._vars else False
        if not host and not cloud_on:
            self._say("请填打印机 IP；如果改用云端，勾上“通过拓竹云连接”。", WARN)
            return
        self.cfg.printer.update({"host": host, "serial": serial, "access_code": code})
        # 云端开关
        if "cloud_enabled" in self._vars:
            self.cfg.cloud["enabled"] = bool(self._vars.pop("cloud_enabled").get())
        # 机型单独处理：选「自动识别」就清空，交给 get_version 去读
        model_raw = str(self._vars.pop("model", tk.StringVar(value="")).get()).strip()
        self.cfg.printer["model"] = "" if model_raw in ("", "自动识别", "AUTO", "auto") else model_raw
        for key, var in self._vars.items():
            if key in ("host", "serial", "access_code", "model"):
                continue
            value = var.get()
            if key in ("popup_seconds",):
                try:
                    value = max(5, min(120, int(str(value).strip())))
                except ValueError:
                    value = 20
            if key in BEHAVIOR_KEYS:
                self.cfg.behavior[key] = bool(value)
            else:
                self.cfg.notify[key] = bool(value) if isinstance(value, bool) else value
        self.cfg.save()
        autostart.set_enabled(bool(self.cfg.behavior.get("autostart")))
        self.app.on_config_saved()
        self.destroy()


# --------------------------------------------------------------------------
# 云端登录窗口
# --------------------------------------------------------------------------
class CloudLoginDialog(tk.Toplevel):
    """登录拓竹账号，走云端中转（打印机和电脑不在同一网络时用）。"""

    def __init__(self, app: "App"):
        super().__init__(app.root)
        self.app = app
        self.cfg = app.cfg
        self.f = app.ui_font
        self.title("登录拓竹账号（跨网络监控）")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(app.root)
        self.grab_set()
        self._devices: list[dict] = []
        # 工作线程不能直接碰 tkinter，只往队列里丢结果，由主线程轮询
        self.q: queue.Queue = queue.Queue()
        self._login_finished = True
        self._build()
        self._center()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(120, self._poll)

    def _poll(self) -> None:
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "say":
                    self._say(item[1], item[2] if len(item) > 2 else MUTED)
                elif kind == "fail":
                    self._fail(item[1])
                elif kind == "done":
                    self._done(item[1], item[2], item[3])
                elif kind == "btn_ok":
                    self.btn_code.configure(state="normal")
        except queue.Empty:
            pass
        except Exception:
            LOG.exception("处理登录结果出错")
        try:
            self.after(120, self._poll)
        except tk.TclError:
            pass

    def _close(self) -> None:
        try:
            self.app._cloud_dialog_closed()
        except Exception:
            pass
        self.destroy()

    def _center(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{max(40, (sh - h) // 2 - 30)}")

    def _say(self, text: str, color: str = MUTED) -> None:
        self.status.configure(text=text, fg=color)

    def _build(self) -> None:
        pad = {"padx": 18}
        tk.Label(self, text="打印机和你不在同一个网络？", bg=BG, fg=TEXT,
                 font=(self.f, 12, "bold")).pack(anchor="w", pady=(16, 4), **pad)
        tk.Label(
            self,
            text="登录拓竹账号后，状态改走拓竹云中转（和 Bambu Studio 跨网络打印是一个通道）。\n"
                 "· 手机号账号：填手机号 → 点“发送短信验证码” → 填入手机收到的数字\n"
                 "· 邮箱账号：填邮箱 → 点“发送邮件验证码” → 填入邮件里的数字\n"
                 "· 也可以直接用密码登录（服务器不支持密码时会提示改用验证码）",
            bg=BG, fg=MUTED, font=(self.f, 9), justify="left", anchor="w",
        ).pack(fill="x", **pad)

        # 账号
        box = tk.Frame(self, bg=BG)
        box.pack(fill="x", pady=(12, 0), **pad)
        tk.Label(box, text="拓竹账号（邮箱或手机号）", bg=BG, fg=MUTED,
                 font=(self.f, 9), anchor="w").pack(anchor="w")
        self.account_var = tk.StringVar(value=self.cfg.cloud.get("account", ""))
        self.account = tk.Entry(box, textvariable=self.account_var, bg=PANEL2, fg=TEXT,
                                insertbackground=TEXT, relief="flat",
                                font=(self.f, 10), highlightthickness=1,
                                highlightbackground=LINE, highlightcolor=BLUE)
        self.account.pack(fill="x", pady=(4, 0))
        self.account_var.trace_add("write", self._on_account_change)

        # 验证码 + 密码
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", pady=(10, 0), **pad)
        tk.Label(row, text="验证码", bg=BG, fg=MUTED, font=(self.f, 9)).pack(side="left")
        self.code = tk.Entry(row, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat",
                             font=(self.f, 10), width=10, highlightthickness=1,
                             highlightbackground=LINE, highlightcolor=BLUE)
        self.code.pack(side="left", padx=(8, 10))
        self.btn_code = self._btn(row, "发送验证码", self._send_code)
        self.btn_code.pack(side="left")

        row2 = tk.Frame(self, bg=BG)
        row2.pack(fill="x", pady=(10, 0), **pad)
        tk.Label(row2, text="密码", bg=BG, fg=MUTED, font=(self.f, 9)).pack(side="left")
        self.password = tk.Entry(row2, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat",
                                 font=(self.f, 10), width=22, show="•", highlightthickness=1,
                                 highlightbackground=LINE, highlightcolor=BLUE)
        self.password.pack(side="left", padx=(8, 0))
        tk.Label(row2, text="（手机号登录填这个）", bg=BG, fg=MUTED,
                 font=(self.f, 9)).pack(side="left", padx=6)
        self.show_pwd = tk.BooleanVar(value=False)
        tk.Checkbutton(row2, text="显示", variable=self.show_pwd, command=self._toggle_pwd,
                       bg=BG, fg=MUTED, selectcolor=PANEL2, activebackground=BG,
                       activeforeground=TEXT, font=(self.f, 9), bd=0,
                       highlightthickness=0).pack(side="left", padx=4)

        self.status = tk.Label(self, text="", bg=BG, fg=MUTED, font=(self.f, 9),
                               anchor="w", wraplength=430, justify="left")
        self.status.pack(fill="x", padx=18, pady=(12, 0))

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", pady=(14, 16), **pad)
        self.btn_login = self._btn(foot, "登录", self._login, primary=True)
        self.btn_login.pack(side="right")
        self._btn(foot, "取消", self.destroy).pack(side="right", padx=10)

        if self.cfg.cloud.get("token"):
            self._say("当前已登录，可重新登录以切换账号。", MUTED)
        self._on_account_change()

    def _btn(self, parent, text, cmd, primary=False):
        bg = ACCENT if primary else PANEL2
        fg = "#07110A" if primary else TEXT
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, relief="flat", bd=0,
                         font=(self.f, 9), padx=12, pady=6, activebackground=bg,
                         activeforeground=fg, cursor="hand2")

    # ---------- 动作 ----------
    def _toggle_pwd(self) -> None:
        self.password.configure(show="" if self.show_pwd.get() else "•")

    def _on_account_change(self, *_args) -> None:
        acc = clean_input(self.account_var.get(), strip_inner_space=True)
        # 两种账号都能发验证码了（短信走 api.bambulab.cn）
        if "@" in acc:
            self.btn_code.configure(state="normal", text="发送邮件验证码")
        else:
            self.btn_code.configure(state="normal", text="发送短信验证码")

    def _account_text(self) -> str:
        return self.account_var.get().strip()

    def _send_code(self) -> None:
        account = clean_input(self.account_var.get(), strip_inner_space=True)
        if not account:
            self._say("请先填账号（手机号或邮箱）", WARN)
            return
        is_email = "@" in account
        self.btn_code.configure(state="disabled")
        self._say("正在发送验证码...", BLUE)

        def work():
            try:
                cloud_mod.BambuCloud(region=self.cfg.cloud.get("region", "China")).send_code(account)
                tip = ("验证码已发到你的邮箱，请查看邮件（几分钟内有效）" if is_email
                       else "验证码已通过短信发出，请查看手机（1~2 分钟内）")
                self.q.put(("say", tip, ACCENT))
                self.q.put(("btn_ok", None))
            except Exception as exc:
                msg = str(exc)
                LOG.warning("发送验证码失败: %s", msg)
                self.q.put(("say", f"发送失败：{msg}", DANGER))
                self.q.put(("btn_ok", None))

        threading.Thread(target=work, daemon=True).start()

    def _login(self) -> None:
        account = clean_input(self.account_var.get(), strip_inner_space=True)
        code = clean_input(self.code.get(), strip_inner_space=True)
        password = clean_input(self.password.get())
        if not account:
            self._say("请先填账号", WARN)
            return
        if not code and not password:
            self._say("请填密码（手机号账号）或验证码（邮箱账号），再点登录", WARN)
            return
        self.account_var.set(account)
        if not password:
            self.password.delete(0, "end")
        self._say("正在登录，请稍候...", BLUE)
        self.btn_login.configure(state="disabled")
        self._login_finished = False
        # 20 秒还没结果就告诉用户，别让它一直转
        self.after(20000, self._login_timeout)

        def work():
            api = cloud_mod.BambuCloud(region=self.cfg.cloud.get("region", "China"))
            try:
                if code:
                    api.login_code(account, code)
                else:
                    api.login_password(account, password)
            except Exception as exc:
                msg = str(exc)
                LOG.warning("云端登录失败: %s", msg)
                self.q.put(("fail", msg))
                return
            LOG.info("云端登录成功，拉取设备列表")
            try:
                devices = api.devices()
            except Exception as exc:
                msg = f"登录成功，但取不到设备列表：{exc}"
                LOG.warning(msg)
                self.q.put(("fail", msg))
                return
            self.q.put(("done", account, api, devices))

        threading.Thread(target=work, daemon=True).start()

    def _login_timeout(self) -> None:
        if getattr(self, "_login_finished", True):
            return
        self.btn_login.configure(state="normal")
        self._say("登录超时：20 秒没有响应。请检查这台电脑能不能上外网，或稍后再试。", WARN)

    def _fail(self, msg: str) -> None:
        self._login_finished = True
        self.btn_login.configure(state="normal")
        if "密码" in msg and "不正确" in msg:
            msg += ("。若确认密码没错，勾上密码框后面的「显示」核对一下，"
                    "注意别让输入法带进全角字符；也注意别连续试太多次，会被限流。")
        self._say(msg, DANGER)

    def _done(self, account: str, api: cloud_mod.BambuCloud, devices: list[dict]) -> None:
        self._login_finished = True
        self.btn_login.configure(state="normal")
        if not devices:
            self._fail("这个账号下没有绑定打印机，请先在 Bambu Studio 或 Bambu Handy 里绑定")
            return
        # 优先选本地已配置的那台
        want = self.cfg.printer.get("serial", "")
        pick = next((d for d in devices if d["dev_id"] == want), None)
        if pick is None:
            online = [d for d in devices if d.get("online")]
            pick = (online or devices)[0]

        c = self.cfg.cloud
        region = "China" if getattr(api, "_base", "") == cloud_mod.API_CN else "US"
        uid = api.fetch_uid()          # 云 MQTT 用户名要用 u_<uid>，必须查一次
        c.update(
            {
                "enabled": True,
                "account": account if self.cfg.cloud.get("remember_account", True) else "",
                "token": api.token,
                "region": region,
                "uid": uid,
                "serial": pick["dev_id"],
                "model": pick.get("model") or "",
                "name": pick.get("name") or "",
            }
        )
        # 顺带把机型写上（云端返回的 dev_product_name 最准）
        if pick.get("model") and not models.normalize(self.cfg.printer.get("model")):
            self.cfg.printer["model"] = models.normalize(pick["model"]) or self.cfg.printer.get("model", "")
        self.cfg.save()
        self._say(f"登录成功：{pick.get('name') or pick['dev_id']}（{pick.get('model') or '未知机型'}）", ACCENT)
        self.app.on_cloud_logged_in()
        self.after(600, self._close)


# --------------------------------------------------------------------------
# 主窗口
# --------------------------------------------------------------------------
class App:
    def __init__(self, cfg: Config, notifier: Notifier, start_minimized: bool = False):
        self.cfg = cfg
        self.notifier = notifier
        self.watcher = Watcher()
        self.client: PrinterClient | None = None
        self.q: queue.Queue = queue.Queue()
        self.events: list[Event] = []
        self._connected = False
        self._job_started: float | None = None
        self._last_summary: dict = {}
        self._last_ams_sig = ""
        self._repeat_job = None
        self._pending_action: Event | None = None
        self._offline_at: float | None = None
        self._bambu_running: bool | None = None
        self._detected_model = ""
        self._autoconnecting = False

        self.root = tk.Tk()
        self.ui_font = pick_font()
        self.root.title(APP_TITLE)
        self.root.configure(bg=BG)
        self.root.minsize(920, 660)
        self.root.option_add("*Font", (self.ui_font, 10))

        geo = self.cfg.get("window", "geometry", "")
        geom = geo if isinstance(geo, str) and geo else ""
        if geom:
            try:
                self.root.geometry(geom)
            except tk.TclError:
                self.root.geometry("1020x720")
        else:
            self.root.geometry("1020x720")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._set_icon()
        self._build()
        self._refresh_buttons()
        # 先按配置画一遍，否则没连上时顶栏会一直显示「未配置打印机」
        try:
            self._paint()
        except Exception:
            LOG.debug("首次绘制失败", exc_info=True)
        self.root.after(150, self._pump)

        if start_minimized or self.cfg.behavior.get("start_minimized"):
            self.root.iconify()

        if self.cfg.behavior.get("auto_connect") and self.cfg.has_printer():
            self.root.after(600, self.connect)

        # 跟随 Bambu Studio：它开着就自动出现在前台
        self.root.after(900, self._poll_bambu)

    # ---------------- 跟随 Bambu Studio ----------------
    def _poll_bambu(self) -> None:
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return

        cnt = -1
        running = False
        try:
            names = running_process_names()
            cnt = len(names)
            running = any(is_bambu_studio(n) for n in names)
            if not running and cnt < 15:
                # 进程表被裁剪时的兜底：看有没有 Bambu Studio 的窗口
                running = bambu_studio_window()
        except Exception as e:
            LOG.warning("进程检测失败: %s", e)

        if self._bambu_running is None:
            LOG.info("进程跟随已启动：可见进程 %s 个，Bambu Studio 运行中=%s", cnt, running)

        if running != self._bambu_running:
            prev = self._bambu_running
            self._bambu_running = running
            follow = bool(self.cfg.behavior.get("follow_bambu_studio", True))
            if running and follow:
                # 启动时它就已经开着，或者刚刚被打开，都走这里
                self._on_bambu_started(initial=(prev is None))
            elif not running and prev is True:
                self._on_bambu_closed()

        try:
            self.root.after(2000, self._poll_bambu)
        except tk.TclError:
            pass

    def _on_bambu_started(self, initial: bool = False) -> None:
        if initial:
            LOG.info("启动时检测到 Bambu Studio 正在运行")
            self._log(Event("bambu", SUCCESS, "检测到 Bambu Studio 正在运行",
                            "监控已就绪"))
        else:
            LOG.info("检测到 Bambu Studio 启动，自动显示监控窗口")
            self._log(Event("bambu", SUCCESS, "检测到 Bambu Studio 已启动",
                            "监控已自动打开并准备连接"))
        self.show_window()
        if not (self.client and self.client.connected) and self.cfg.has_printer():
            self.connect()

    def _on_bambu_closed(self) -> None:
        LOG.info("检测到 Bambu Studio 已退出")
        self._log(Event("bambu", SUCCESS, "Bambu Studio 已关闭", "监控继续在后台盯着打印机"))
        if self.cfg.behavior.get("hide_when_bambu_closes"):
            try:
                self.root.iconify()
            except tk.TclError:
                pass

    # ---------------- 布局 ----------------
    def _set_icon(self) -> None:
        try:
            bases = [Path(__file__).resolve().parent.parent]
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                bases.append(Path(meipass))
            for base in bases:
                ico = base / "assets" / "app.ico"
                if ico.exists():
                    self.root.iconbitmap(default=str(ico))
                    return
        except Exception:
            pass

    def _label(self, parent, text="", size=10, fg=TEXT, bold=False, **kw):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=fg,
                        font=(self.ui_font, size, "bold" if bold else "normal"), **kw)

    def _card(self, parent, title: str) -> tk.Frame:
        outer = tk.Frame(parent, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        head = tk.Frame(outer, bg=PANEL)
        head.pack(fill="x", padx=16, pady=(12, 0))
        tk.Label(head, text=title, bg=PANEL, fg=MUTED, font=(self.ui_font, 9)).pack(side="left")
        body = tk.Frame(outer, bg=PANEL)
        body.pack(fill="both", expand=True, padx=16, pady=(6, 14))
        return outer, body

    def _build(self) -> None:
        # ================= 顶栏 =================
        header = tk.Frame(self.root, bg=PANEL)
        header.pack(fill="x", side="top")
        inner = tk.Frame(header, bg=PANEL)
        inner.pack(fill="x", padx=18, pady=12)

        self.dot = tk.Canvas(inner, width=14, height=14, bg=PANEL, highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 8))
        self._dot = self.dot.create_oval(3, 3, 11, 11, fill=MUTED, outline="")

        tk.Label(inner, text="拓竹打印监控", bg=PANEL, fg=TEXT,
                 font=(self.ui_font, 13, "bold")).pack(side="left")

        self.conn_badge = tk.Label(inner, text="未连接", bg=PANEL2, fg=MUTED,
                                   font=(self.ui_font, 9), padx=9, pady=2)
        self.conn_badge.pack(side="left", padx=(12, 8))
        self.printer_label = tk.Label(inner, text="未配置打印机", bg=PANEL, fg=MUTED,
                                      font=(self.ui_font, 9))
        self.printer_label.pack(side="left")

        self.btn_settings = self._btn(inner, "设置", self.open_settings)
        self.btn_settings.pack(side="right")
        self.btn_connect = self._btn(inner, "连接", self.toggle_connect, primary=True)
        self.btn_connect.pack(side="right", padx=8)

        tk.Frame(self.root, bg=LINE, height=1).pack(fill="x")

        # ================= 底部状态栏（先占位，保证永远贴底）=================
        tk.Frame(self.root, bg=LINE, height=1).pack(fill="x", side="bottom")
        status = tk.Frame(self.root, bg=PANEL)
        status.pack(fill="x", side="bottom")
        self.status_label = tk.Label(status, text="就绪", bg=PANEL, fg=MUTED,
                                     font=(self.ui_font, 9), anchor="w")
        self.status_label.pack(side="left", padx=14, pady=6)
        self.clock_label = tk.Label(status, text="", bg=PANEL, fg=MUTED, font=(self.ui_font, 9))
        self.clock_label.pack(side="right", padx=14)
        self.btn_quit = tk.Button(status, text="退出", command=lambda: self._on_close(force=True),
                                  bg=PANEL, fg=MUTED, relief="flat", bd=0, font=(self.ui_font, 9),
                                  activebackground=PANEL, activeforeground=DANGER, cursor="hand2")
        self.btn_quit.pack(side="right", padx=(0, 8))
        self._tick_clock()

        # ================= 主体 =================
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        body.columnconfigure(0, weight=62, uniform="c")
        body.columnconfigure(1, weight=38, uniform="c")
        body.rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        # ---------------- 打印状态 ----------------
        card, box = self._card(left, "打印状态")
        card.pack(fill="x")

        top = tk.Frame(box, bg=PANEL)
        top.pack(fill="x")
        self.state_badge = tk.Label(top, text="未连接", bg=PANEL2, fg=MUTED,
                                    font=(self.ui_font, 11, "bold"), padx=10, pady=3)
        self.state_badge.pack(side="left")
        self.stage_label = tk.Label(top, text="", bg=PANEL, fg=MUTED, font=(self.ui_font, 9))
        self.stage_label.pack(side="left", padx=10)
        self.elapsed_label = tk.Label(top, text="", bg=PANEL, fg=MUTED, font=(self.ui_font, 9))
        self.elapsed_label.pack(side="right")

        self.file_label = tk.Label(box, text="—", bg=PANEL, fg=TEXT,
                                   font=(self.ui_font, 12, "bold"), anchor="w", justify="left")
        self.file_label.pack(fill="x", pady=(10, 8))

        self.canvas_bar = tk.Canvas(box, height=26, bg=PANEL, highlightthickness=0)
        self.canvas_bar.pack(fill="x")
        self.canvas_bar.bind("<Configure>", lambda e: self._draw_progress())

        # 三个指标块：进度 / 层数 / 剩余
        metrics = tk.Frame(box, bg=PANEL)
        metrics.pack(fill="x", pady=(10, 0))
        metrics.columnconfigure(0, weight=1)
        metrics.columnconfigure(1, weight=1)
        metrics.columnconfigure(2, weight=1)
        self.metric = {}
        for i, (key, title) in enumerate((("progress", "进度"), ("layer", "层数"), ("remain", "剩余时间"))):
            cell = tk.Frame(metrics, bg=PANEL2)
            cell.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))
            tk.Label(cell, text=title, bg=PANEL2, fg=MUTED,
                     font=(self.ui_font, 8)).pack(anchor="w", padx=10, pady=(6, 0))
            val = tk.Label(cell, text="--", bg=PANEL2, fg=TEXT, font=(self.ui_font, 12, "bold"))
            val.pack(anchor="w", padx=10, pady=(0, 6))
            self.metric[key] = val

        # ---------------- 温度 ----------------
        card2, box2 = self._card(left, "温度")
        card2.pack(fill="x", pady=(10, 0))
        temps = tk.Frame(box2, bg=PANEL)
        temps.pack(fill="x")
        temps.columnconfigure(0, weight=1)
        temps.columnconfigure(1, weight=1)
        temps.columnconfigure(2, weight=1)
        self.temp_labels = {}
        self.temp_bars = {}
        for i, (key, title) in enumerate((("nozzle", "喷嘴"), ("bed", "热床"), ("chamber", "腔体"))):
            cell = tk.Frame(temps, bg=PANEL)
            cell.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 14, 0))
            head = tk.Frame(cell, bg=PANEL)
            head.pack(fill="x")
            tk.Label(head, text=title, bg=PANEL, fg=MUTED, font=(self.ui_font, 9)).pack(side="left")
            val = tk.Label(head, text="--", bg=PANEL, fg=TEXT, font=(self.ui_font, 11, "bold"))
            val.pack(side="right")
            self.temp_labels[key] = val
            bar = tk.Canvas(cell, height=6, bg=PANEL, highlightthickness=0)
            bar.pack(fill="x", pady=(4, 0))
            self.temp_bars[key] = bar

        info = tk.Frame(box2, bg=PANEL)
        info.pack(fill="x", pady=(10, 0))
        self.net_label = tk.Label(info, text="", bg=PANEL, fg=MUTED, font=(self.ui_font, 9))
        self.net_label.pack(side="left")
        self.ams_state_label = tk.Label(info, text="", bg=PANEL, fg=MUTED, font=(self.ui_font, 9))
        self.ams_state_label.pack(side="left", padx=16)

        # ---------------- AMS ----------------
        card3, box3 = self._card(left, "AMS 料盘")
        card3.pack(fill="both", expand=True, pady=(10, 0))
        self.ams_frame = tk.Frame(box3, bg=PANEL)
        self.ams_frame.pack(fill="both", expand=True)

        # ---------------- 右栏：事件记录 ----------------
        card4, box4 = self._card(right, "事件记录")
        card4.pack(fill="both", expand=True)
        wrap = tk.Frame(box4, bg=PANEL)
        wrap.pack(fill="both", expand=True)
        self.log = tk.Text(wrap, bg=PANEL2, fg=TEXT, relief="flat", font=(self.ui_font, 9),
                           wrap="word", height=10, insertbackground=TEXT,
                           highlightthickness=0, padx=10, pady=8, spacing1=3, spacing3=3)
        self.log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=sb.set, state="disabled")
        for level, color in LEVEL_COLOR.items():
            self.log.tag_configure(level, foreground=color)
        self.log.tag_configure("time", foreground=MUTED)

        # ---------------- 右栏：控制按钮 ----------------
        ctrl = tk.Frame(right, bg=BG)
        ctrl.pack(fill="x", pady=(10, 0))
        self.btn_pause = self._btn(ctrl, "暂停", lambda: self._cmd("pause"))
        self.btn_pause.pack(side="left")
        self.btn_resume = self._btn(ctrl, "继续", lambda: self._cmd("resume"))
        self.btn_resume.pack(side="left", padx=8)
        self.btn_stop = self._btn(ctrl, "停止打印", self._confirm_stop, danger=True)
        self.btn_stop.pack(side="left")
        self.btn_test = self._btn(ctrl, "测试通知", self.test_notification)
        self.btn_test.pack(side="right")

    def _btn(self, parent, text, cmd, primary=False, danger=False):
        bg = ACCENT if primary else (DANGER if danger else PANEL2)
        fg = "#07110A" if primary else (TEXT if danger else TEXT)
        btn = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg, relief="flat", bd=0,
                        font=(self.ui_font, 9), padx=14, pady=6, activebackground=bg,
                        activeforeground=fg, cursor="hand2", disabledforeground=MUTED)
        return btn

    # ---------------- 连接管理 ----------------
    def use_cloud(self) -> bool:
        c = self.cfg.cloud
        return bool(c.get("enabled") and c.get("token") and c.get("serial"))

    def _connect_cloud(self) -> None:
        c = self.cfg.cloud
        self.disconnect()
        self.watcher.reset()
        host = cloud_mod.BambuCloud(region=c.get("region", "China")).mqtt_host
        token = c.get("token", "")
        uid = str(c.get("uid") or "")
        username = f"u_{uid}" if uid else cloud_mod.jwt_username(token)
        if not username:
            self._set_status("云端凭证缺少 uid，请重新登录")
            return
        self._set_status(f"正在通过拓竹云连接 {c.get('name') or c.get('serial')} ...")
        self.client = PrinterClient(
            host=host,
            serial=c.get("serial", ""),
            access_code="",
            username=username,
            password=token,
            cloud=True,
            on_report=lambda d: self.q.put(("report", d)),
            on_connected=lambda: self.q.put(("connected", None)),
            on_disconnected=lambda: self.q.put(("disconnected", None)),
            on_status=lambda t: self.q.put(("status", t)),
            on_info=lambda d: self.q.put(("info", d)),
            pushall_interval=int(self.cfg.behavior.get("pushall_interval", 90)),
        )
        self.client.start()

    def connect(self) -> None:
        if self.client and self.client.connected:
            return
        if self.cfg.cloud.get("enabled") and not self.cfg.cloud.get("token"):
            self.open_cloud_login()
            return
        if self.use_cloud():
            self._connect_cloud()
            return
        p = self.cfg.printer
        host, serial, code = p.get("host"), p.get("serial"), p.get("access_code")
        if not (host and serial and code):
            self.open_settings()
            return
        self.disconnect()
        self.watcher.reset()
        self._set_status(f"正在连接 {host} ...")
        self.client = PrinterClient(
            host=host,
            serial=serial,
            access_code=code,
            on_report=lambda d: self.q.put(("report", d)),
            on_connected=lambda: self.q.put(("connected", None)),
            on_disconnected=lambda: self.q.put(("disconnected", None)),
            on_status=lambda t: self.q.put(("status", t)),
            on_info=lambda d: self.q.put(("info", d)),
            pushall_interval=int(self.cfg.behavior.get("pushall_interval", 90)),
        )
        self.client.start()

    def disconnect(self) -> None:
        if self.client:
            self.client.stop()
            self.client = None
        self._connected = False
        self._refresh_buttons()

    def toggle_connect(self) -> None:
        if self.client and self.client.connected:
            self.disconnect()
            self._set_status("已断开")
            self._set_badge("未连接", MUTED)
        else:
            self.connect()

    def _cmd(self, name: str) -> None:
        if not self.client or not self.client.connected:
            self._set_status("未连接打印机")
            return
        ok = {"pause": self.client.pause, "resume": self.client.resume,
              "stop": self.client.stop_print}[name]()
        self._set_status("指令已发送" if ok else "指令发送失败")

    def _confirm_stop(self) -> None:
        if not messagebox.askyesno("停止打印", "确定要停止当前打印吗？这个操作不可撤销。", parent=self.root):
            return
        self._cmd("stop")

    # ---------------- 事件泵 ----------------
    def _pump(self) -> None:
        while True:
            try:
                kind, payload = self.q.get_nowait()
            except queue.Empty:
                break
            try:
                if kind == "report":
                    self._on_report(payload)
                elif kind == "connected":
                    self._connected = True
                    self._offline_at = None
                    self._set_status("已连接打印机")
                    self._refresh_buttons()
                    self._log(Event("online", SUCCESS, "已连接", self._conn_target_text()))
                elif kind == "disconnected":
                    was_connected = self._connected
                    self._connected = False
                    self._set_status(self._offline_hint() or "连接已断开，正在自动重连…")
                    self._set_badge("离线", MUTED)
                    self._refresh_buttons()
                    if was_connected:
                        self._offline_at = time.time()
                        secs = int(self.cfg.behavior.get("offline_alert_seconds", 120))
                        self.root.after(max(10, secs) * 1000, self._check_offline)
                elif kind == "info":
                    self._on_info(payload)
                elif kind == "status":
                    text = str(payload)
                    if text.startswith("连接失败"):
                        hint = self._offline_hint()
                        if self.use_cloud():
                            hint = f"云端连接失败（{self.cfg.cloud.get('serial', '')}），可能是登录已过期，请重新登录"
                        if hint:
                            text = f"{text}｜{hint}"
                            if not getattr(self, "_hinted_offline", False):
                                self._hinted_offline = True
                                LOG.info("连接失败提示: %s", hint)
                                self._log(Event("offline", WARNING, "连不上打印机", hint))
                                # 局域网跨网段时，自动弹一次登录窗
                                if (not self.use_cloud()
                                        and not getattr(self, "_cloud_prompted", False)
                                        and self._offline_hint()):
                                    self._cloud_prompted = True
                                    self.root.after(1200, self.open_cloud_login)
                        self._set_badge("离线", DANGER)
                    elif text.startswith("已连接"):
                        self._hinted_offline = False
                    self._set_status(text)
            except Exception:
                LOG.exception("处理消息出错")
        self.root.after(150, self._pump)

    def _on_report(self, payload: dict) -> None:
        events = self.watcher.feed(payload)
        self._paint()
        for ev in events:
            self._handle_event(ev)

    # ---------------- 机型 ----------------
    def _on_info(self, info: dict) -> None:
        model = models.from_get_version(info)
        if not model:
            return
        if model != self._detected_model:
            self._detected_model = model
            LOG.info("识别到机型: %s", model)
            self._log(Event("model", SUCCESS, f"识别到机型：{model}", ""))
        if self.cfg.printer.get("model_detected") != model:
            self.cfg.printer["model_detected"] = model
            self.cfg.save()
        self._paint()

    def model_text(self) -> str:
        manual = models.normalize(self.cfg.printer.get("model"))
        if manual:
            return manual
        return (self.cfg.printer.get("model_detected")
                or self._detected_model
                or models.normalize(self.cfg.cloud.get("model"))
                or "未知机型")

    # ---------------- 云端登录 ----------------
    def open_cloud_login(self) -> None:
        dlg = getattr(self, "_cloud_dialog", None)
        if dlg is not None:
            try:
                if dlg.winfo_exists():
                    dlg.deiconify()
                    dlg.lift()
                    dlg.focus_force()
                    return
            except tk.TclError:
                pass
        try:
            self._cloud_dialog = CloudLoginDialog(self)
        except tk.TclError:
            self._cloud_dialog = None

    def _cloud_dialog_closed(self) -> None:
        self._cloud_dialog = None

    def on_cloud_logged_in(self) -> None:
        c = self.cfg.cloud
        name = c.get("name") or c.get("serial")
        LOG.info("已登录拓竹账号，云端设备 %s", c.get("serial"))
        self._log(Event("cloud", SUCCESS, "已登录拓竹账号",
                        f"将通过拓竹云监控 {name}"))
        self._set_status(f"已登录，正在通过云端连接 {name} ...")
        self._detected_model = models.normalize(c.get("model")) or self._detected_model
        self._last_ams_sig = ""
        try:
            self._paint()
        except Exception:
            LOG.debug("刷新界面失败", exc_info=True)
        self.connect()

    def _conn_target_text(self) -> str:
        """日志里显示的连接目标：云端不暴露局域网 IP。"""
        if self.use_cloud():
            c = self.cfg.cloud
            name = c.get("name") or c.get("serial", "")
            return f"{name}（拓竹云）" if name else "拓竹云"
        return self.cfg.printer.get("host", "")

    def _offline_hint(self) -> str:
        """连不上时，如果能判断是跨网段，就把原因说清楚。"""
        host = self.cfg.printer.get("host", "")
        if not host:
            return ""
        try:
            same = discovery.same_subnet(host)
        except Exception:
            same = None
        if same is False:
            return (f"跨网段：打印机 {host} 不在本机网络（本机 {discovery.local_networks_text()}），"
                    f"局域网直连不可达")
        return ""

    def _check_offline(self) -> None:
        """断开超过设定时长仍未重连，才提醒，避免 WiFi 抖动时误报。"""
        if self._connected or self._offline_at is None:
            return
        secs = int(self.cfg.behavior.get("offline_alert_seconds", 120))
        if time.time() - self._offline_at < max(10, secs):
            return
        self._handle_event(
            Event(
                "offline",
                WARNING,
                "打印机失联",
                f"已经 {secs} 秒连不上 {self.cfg.printer.get('host', '打印机')}，"
                "请检查电源、WiFi 或打印是否被中断",
                need_action=True,
                sound="error",
            )
        )
        self._offline_at = None
        for ev in events:
            self._handle_event(ev)

    def _handle_event(self, ev: Event) -> None:
        self._log(ev)
        key = EVENT_SWITCH.get(ev.kind)
        if key is None:
            return
        if not self.cfg.notify.get(key, True):
            return
        self.notifier.notify(
            ev.title,
            ev.body,
            level="error" if ev.level == ERROR else ("success" if ev.level == SUCCESS else "warning"),
            sound=ev.sound,
            footer=self._footer(),
        )
        if self.cfg.notify.get("popup", True):
            AlertPopup(self, ev, int(self.cfg.notify.get("popup_seconds", 20)))
        if ev.need_action and self.cfg.notify.get("repeat_need_action", True):
            self._schedule_repeat(ev)

    def _schedule_repeat(self, ev: Event) -> None:
        if self._repeat_job:
            try:
                self.root.after_cancel(self._repeat_job)
            except tk.TclError:
                pass
            self._repeat_job = None
        self._pending_action = ev
        interval = int(self.cfg.behavior.get("repeat_interval", self.cfg.notify.get("repeat_interval", 60))) * 1000

        def again():
            self._repeat_job = None
            st = self.watcher.summary()
            if st.get("gcode_state") not in ("PAUSE", "FAILED") or not self._pending_action:
                return
            self.notifier.play("error" if ev.level == ERROR else "attention")
            self._repeat_job = self.root.after(interval, again)

        self._repeat_job = self.root.after(interval, again)

    def _footer(self) -> str:
        p = self.cfg.printer
        return f"{p.get('name') or '打印机'} · {p.get('host', '')}"

    # ---------------- 渲染 ----------------
    def _paint(self) -> None:
        s = self.watcher.summary()
        self._last_summary = s
        gs = s["gcode_state"]
        color = {"RUNNING": ACCENT, "PAUSE": WARN, "FAILED": DANGER, "FINISH": BLUE}.get(gs, MUTED)
        self._set_badge(s["state_text"], color)
        self.dot.itemconfigure(self._dot, fill=color if self._connected else MUTED)

        # 顶栏：连接方式 + 在线状态
        if self.use_cloud():
            mode = "云端"
        elif self.cfg.printer.get("host"):
            mode = "局域网"
        else:
            mode = "未配置"
        if self._connected:
            self.conn_badge.configure(text=f"{mode} · 在线", fg=ACCENT)
        else:
            self.conn_badge.configure(text=f"{mode} · 离线", fg=MUTED)

        self.stage_label.configure(text=s["stage_text"] or "")
        name = s["file"] or "（未在打印）"
        self.file_label.configure(text=name)

        pct = s["percent"] if isinstance(s["percent"], int) else 0
        self._progress = max(0, min(100, pct))
        self._draw_progress()
        self.metric["progress"].configure(text=f"{pct}%")

        if s["layer"] is not None and s["total_layer"]:
            self.metric["layer"].configure(text=f"{s['layer']}/{s['total_layer']}")
        else:
            self.metric["layer"].configure(text="--")
        remain = s["remaining_text"].replace("约 ", "") if s["remaining_text"] else "--"
        self.metric["remain"].configure(text=remain)

        if gs == "RUNNING" and self._job_started is None:
            self._job_started = time.time()
        if gs in ("FINISH", "IDLE", "FAILED"):
            self._job_started = None
        if self._job_started:
            el = int(time.time() - self._job_started)
            self.elapsed_label.configure(text=f"已用 {el // 3600}:{el % 3600 // 60:02d}:{el % 60:02d}")
        else:
            self.elapsed_label.configure(text="")

        # 温度
        self.temp_labels["nozzle"].configure(text=fmt_temp(s["nozzle"]))
        self._draw_temp_bar("nozzle", s["nozzle"], s["nozzle_target"])
        self.temp_labels["bed"].configure(text=fmt_temp(s["bed"]))
        self._draw_temp_bar("bed", s["bed"], s["bed_target"])
        ch = s["chamber"]
        try:
            chv = float(ch)
        except (TypeError, ValueError):
            chv = None
        if chv is None or not models.has_chamber_sensor(self.model_text()) or chv <= 6:
            self.temp_labels["chamber"].configure(text="—", fg=MUTED)
            self._draw_temp_bar("chamber", 0, 0)
        else:
            self.temp_labels["chamber"].configure(text=f"{chv:.0f}°C", fg=TEXT)
            self._draw_temp_bar("chamber", chv, 60)
        self.net_label.configure(text=f"WiFi {s['wifi'] or '--'}")
        self.ams_state_label.configure(text=f"AMS {s['ams_text'] or '--'}")

        self._paint_ams(s)

        p = self.cfg.printer
        if self.use_cloud():
            c = self.cfg.cloud
            parts = [self.model_text()]
            if c.get("name"):
                parts.insert(0, c["name"])
            parts += [c.get("serial", "")]
            self.printer_label.configure(text="  ·  ".join(x for x in parts if x))
        elif p.get("host"):
            parts = [self.model_text()]
            if p.get("name"):
                parts.insert(0, p["name"])
            parts += [p.get("host", "")]
            self.printer_label.configure(text="  ·  ".join(x for x in parts if x))
        else:
            self.printer_label.configure(text="未配置打印机，请点「设置」")
        self._refresh_buttons(gs)

    def _draw_temp_bar(self, key: str, cur, target) -> None:
        c = self.temp_bars.get(key)
        if c is None:
            return
        c.delete("all")
        w = max(10, c.winfo_width())
        h = 6
        c.create_rectangle(0, 1, w, h - 1, fill=PANEL2, outline="")
        try:
            cv = float(cur)
        except (TypeError, ValueError):
            return
        try:
            tv = float(target)
        except (TypeError, ValueError):
            tv = 0
        scale = max(tv, cv * 1.15, 40)
        if scale <= 0:
            return
        ratio = max(0.0, min(1.0, cv / scale))
        if ratio <= 0:
            return
        tcolor = WARN if (tv and tv - cv > 15) else (ACCENT if tv else MUTED)
        c.create_rectangle(0, 1, int(w * ratio), h - 1, fill=tcolor, outline="")

    def _paint_ams(self, s: dict) -> None:
        units = s.get("ams") or []
        sig = repr([(u.get("id"), u.get("humidity"), u.get("temp"),
                     [(t.get("id"), t.get("tray_type"), t.get("tray_color"), t.get("remain"))
                      for t in (u.get("tray") or [])]) for u in units])
        sig += repr(s.get("vt_tray"))
        if sig == self._last_ams_sig:
            return
        self._last_ams_sig = sig
        for w in self.ams_frame.winfo_children():
            w.destroy()

        if not units:
            tk.Label(self.ams_frame, text="没有 AMS（单色打印，或没装 AMS）", bg=PANEL, fg=MUTED,
                     font=(self.ui_font, 9), anchor="w").pack(fill="x")
            return

        for unit in units:
            head = tk.Frame(self.ams_frame, bg=PANEL)
            head.pack(fill="x", pady=(0, 6))
            tk.Label(head, text=f"AMS {int(unit.get('id', 0)) + 1}", bg=PANEL, fg=TEXT,
                     font=(self.ui_font, 9, "bold")).pack(side="left")
            tk.Label(head, text=f"湿度 {unit.get('humidity', '--')}  ·  温度 {unit.get('temp', '--')}°C",
                     bg=PANEL, fg=MUTED, font=(self.ui_font, 9)).pack(side="left", padx=10)

            grid = tk.Frame(self.ams_frame, bg=PANEL)
            grid.pack(fill="x")
            grid.columnconfigure(0, weight=1)
            grid.columnconfigure(1, weight=1)
            trays = unit.get("tray") or []
            for i, tray in enumerate(trays):
                self._ams_card(grid, tray, i)

    def _ams_card(self, parent, tray: dict, index: int) -> None:
        used = bool(tray.get("tray_type"))
        cell = tk.Frame(parent, bg=PANEL2)
        cell.grid(row=index // 2, column=index % 2, sticky="ew",
                  padx=(0 if index % 2 == 0 else 8, 0), pady=(0, 6))

        # 颜色块
        color_hex = (tray.get("tray_color") or "333333FF")[:6]
        try:
            rgb = "#" + color_hex
        except Exception:
            rgb = "#333333"
        chip = tk.Canvas(cell, width=26, height=26, bg=PANEL2, highlightthickness=0)
        chip.create_rectangle(0, 0, 26, 26, fill=rgb, outline=MUTED if not used else "")
        chip.pack(side="left", padx=(10, 8), pady=10)

        info = tk.Frame(cell, bg=PANEL2)
        info.pack(side="left", fill="both", expand=True, pady=8)
        material = tray.get("tray_type") or "空槽"
        sub = tray.get("tray_sub_brands") or ""
        title = f"槽位 {index + 1} · {material}"
        if sub and sub not in material:
            title += f" {sub}"
        tk.Label(info, text=title, bg=PANEL2, fg=TEXT if used else MUTED,
                 font=(self.ui_font, 9, "bold" if used else "normal"), anchor="w").pack(
            fill="x", padx=(0, 10))
        remain = tray.get("remain")
        remain_text = f"剩余 {remain}%" if isinstance(remain, int) and remain >= 0 else "余量未知"
        tk.Label(info, text=remain_text, bg=PANEL2, fg=MUTED,
                 font=(self.ui_font, 8), anchor="w").pack(fill="x", padx=(0, 10))
        bar = tk.Canvas(info, height=5, bg=PANEL2, highlightthickness=0)
        bar.pack(fill="x", padx=(0, 10), pady=(3, 0))

        def draw(_evt=None, canvas=bar, val=remain):
            canvas.delete("all")
            w = max(10, canvas.winfo_width())
            canvas.create_rectangle(0, 1, w, 4, fill=LINE, outline="")
            if isinstance(val, int) and val > 0:
                canvas.create_rectangle(0, 1, int(w * min(100, val) / 100), 4,
                                        fill=ACCENT if val > 20 else WARN, outline="")

        bar.bind("<Configure>", draw)
        self.root.after(30, draw)

    def _draw_progress(self) -> None:
        c = self.canvas_bar
        c.delete("all")
        w = max(10, c.winfo_width())
        h = 26
        c.create_rectangle(0, 7, w, h - 7, fill=PANEL2, outline="")
        pct = getattr(self, "_progress", 0)
        if pct > 0:
            fill_w = max(6, int((w - 2) * pct / 100))
            c.create_rectangle(0, 7, fill_w, h - 7, fill=ACCENT, outline="")
        c.create_text(w // 2, h // 2, text=f"{pct}%", fill=TEXT,
                      font=(self.ui_font, 9, "bold"))

    def _set_badge(self, text: str, color: str) -> None:
        self.state_badge.configure(text=text, fg=color)

    def _set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def _refresh_buttons(self, gs: str | None = None) -> None:
        connected = bool(self.client and self.client.connected)
        if connected:
            self.btn_connect.configure(text="断开", bg=PANEL2, fg=TEXT, activebackground=PANEL2)
        else:
            self.btn_connect.configure(text="连接", bg=ACCENT, fg="#07110A", activebackground=ACCENT)
        gs = gs if gs is not None else self.watcher.summary().get("gcode_state", "")
        state = "normal" if connected else "disabled"
        for b in (self.btn_pause, self.btn_stop):
            b.configure(state=state if gs in ("RUNNING", "PAUSE") else "disabled")
        self.btn_pause.configure(state="normal" if (connected and gs == "RUNNING") else "disabled")
        self.btn_resume.configure(state="normal" if (connected and gs == "PAUSE") else "disabled")

    def _log(self, ev: Event) -> None:
        self.events.append(ev)
        if len(self.events) > 500:
            del self.events[:200]
        stamp = time.strftime("%H:%M:%S", time.localtime(ev.ts))
        self.log.configure(state="normal")
        self.log.insert("end", f"[{stamp}] ", "time")
        self.log.insert("end", f"{ev.title}", ev.level if ev.level in LEVEL_COLOR else "info")
        if ev.body:
            self.log.insert("end", f"  {ev.body}\n", "info")
        else:
            self.log.insert("end", "\n", "info")
        # 只保留最近 400 行，避免长时间运行后越来越慢
        try:
            if int(self.log.index("end-1c").split(".")[0]) > 400:
                self.log.delete("1.0", "100.0")
        except (tk.TclError, ValueError):
            pass
        self.log.see("end")
        self.log.configure(state="disabled")

    def _tick_clock(self) -> None:
        self.clock_label.configure(text=time.strftime("%Y-%m-%d %H:%M:%S"))
        self.root.after(1000, self._tick_clock)

    # ---------------- 对外动作 ----------------
    def open_settings(self) -> None:
        SettingsDialog(self)

    def on_config_saved(self) -> None:
        self._set_status("设置已保存")
        self._last_summary = {}
        if self.cfg.behavior.get("auto_connect") and self.cfg.has_printer():
            self.connect()

    def show_window(self) -> None:
        try:
            self.root.deiconify()
            self.root.lift()
            # 先强制置顶再取消，避免窗口只是恢复了却压在其他最大化窗口后面
            self.root.attributes("-topmost", True)
            self.root.after(1500, self._drop_topmost)
            try:
                self.root.focus_force()
            except tk.TclError:
                pass
        except tk.TclError:
            pass

    def _drop_topmost(self) -> None:
        try:
            if self.root.winfo_exists():
                self.root.attributes("-topmost", False)
        except tk.TclError:
            pass

    def test_notification(self) -> None:
        ev = Event("finish", SUCCESS, "测试通知：打印完成 🎉",
                   "「测试模型.3mf」打印完成，可以取件了。看到这条说明通知正常。",
                   sound="finish")
        self._handle_event(ev)

    def demo(self) -> None:
        """快速演示四种提醒（不接打印机也能看效果）。"""
        from .state import INFO

        steps = [
            (1.5, Event("start", INFO, "开始打印", "「Benchy 小船.3mf」开始打印")),
            (4.5, Event("finish", SUCCESS, "打印完成 🎉",
                        "「Benchy 小船.3mf」打印完成。可以取件了",
                        sound="finish", detail={"file": "Benchy"})),
            (9.0, Event("pause", WARNING, "打印已暂停：耗材用完了",
                        "装上新的料卷（或让 AMS 换到有料的槽位），然后点继续（已打印 62%）",
                        need_action=True, sound="attention")),
            (14.5, Event("fail", ERROR, "打印机故障：AMS",
                         "HMS 0700_2000_0002_0001。检查耗材是否卡住、料管是否插紧、AMS 是否识别到料卷",
                         need_action=True, sound="error")),
        ]
        for delay, ev in steps:
            self.root.after(int(delay * 1000), lambda e=ev: self._handle_event(e))

    def _on_close(self, force: bool = False) -> None:
        # 默认：点 X 只是缩到任务栏，进程继续在后台盯着打印机
        if not force and not self.cfg.behavior.get("exit_on_close", False):
            try:
                self.root.iconify()
            except tk.TclError:
                pass
            self._set_status("已缩到任务栏，仍在后台监控。要彻底退出请点右下角「退出程序」")
            LOG.info("窗口已最小化，进程继续后台监控")
            return
        try:
            self.cfg.set("window", "geometry", self.root.geometry(), save=False)
            self.cfg.save()
        except Exception:
            pass
        self.disconnect()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self) -> None:
        self.root.mainloop()
