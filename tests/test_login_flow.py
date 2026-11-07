"""真实走一遍登录窗口的流程，确认失败时界面不会卡在「正在登录」。

会访问 api.bambulab.com（用错误密码，不会影响账号）。
运行: python tests\test_login_flow.py
"""
from __future__ import annotations

import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _s in (sys.stdout, sys.stderr):
    try:
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(errors="replace")
    except Exception:
        pass

from bambu_monitor import ui as ui_mod  # noqa: E402
from bambu_monitor.config import Config  # noqa: E402


class FakeApp:
    def __init__(self, root):
        self.root = root
        self.cfg = Config()
        self.ui_font = "Microsoft YaHei UI"
        self.logged_in = []

    def _cloud_dialog_closed(self):
        pass

    def on_cloud_logged_in(self):
        self.logged_in.append(True)


def run_case(title: str, account: str, password: str, code: str) -> str:
    root = tk.Tk()
    root.withdraw()
    app = FakeApp(root)
    dlg = ui_mod.CloudLoginDialog(app)
    dlg.account_var.set(account)
    if password:
        dlg.password.insert(0, password)
    if code:
        dlg.code.insert(0, code)
    dlg._login()

    final = ""
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            root.update()
        except tk.TclError:
            break
        tip = dlg.status.cget("text")
        if tip and tip not in ("正在登录，请稍候...", ""):
            final = tip
            break
        time.sleep(0.05)
    try:
        root.destroy()
    except tk.TclError:
        pass
    print(f"[{title}] -> {final or '（超时未更新）'}")
    return final


def main() -> int:
    ok = True
    r1 = run_case("手机号+错密码", "13800138000", "definitely_wrong_pwd", "")
    ok &= bool(r1) and "正在登录" not in r1
    r2 = run_case("手机号+错验证码", "13800138000", "", "000000")
    ok &= bool(r2) and "正在登录" not in r2
    r3 = run_case("手机号不发短信", "13800138000", "", "")
    print("\n通过" if ok else "\n有失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
