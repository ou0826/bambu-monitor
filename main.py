"""拓竹打印监控 —— 入口。

用法:
    python main.py              # 正常启动
    python main.py --minimized  # 最小化启动（开机自启用）
    python main.py --test-notify  # 只发一条测试通知
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import socket
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from bambu_monitor import __version__
from bambu_monitor import i18n
from bambu_monitor.config import APP_TITLE, Config, log_dir
from bambu_monitor.notify import Notifier
from bambu_monitor.ui import App

LOG = logging.getLogger("bambumon")
_lock_socket: socket.socket | None = None


def setup_logging() -> None:
    # 控制台是 GBK 时，日志里出现 emoji/特殊字符不该让程序崩
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="replace")
        except Exception:
            pass
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    try:
        handler = logging.handlers.RotatingFileHandler(
            log_dir() / "app.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(handler)
    except OSError as e:
        # 日志目录不可写时不能影响主流程
        print(f"警告: 无法写日志文件（{e}）")
    if sys.stderr is not None:
        try:
            console = logging.StreamHandler()
            console.setFormatter(logging.Formatter("%(levelname)-7s %(name)s: %(message)s"))
            root.addHandler(console)
        except Exception:
            pass


def acquire_single_instance() -> bool:
    """用本地端口锁保证只跑一个实例。"""
    global _lock_socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 39777))
        s.listen(1)
        _lock_socket = s
        return True
    except OSError:
        s.close()
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--minimized", action="store_true", help="启动后最小化")
    parser.add_argument("--test-notify", action="store_true", help="发送一条测试通知后退出")
    parser.add_argument("--demo", action="store_true", help="演示四种提醒效果")
    parser.add_argument("--settings", action="store_true", help="启动后直接打开设置窗口")
    parser.add_argument("--cloud-login", action="store_true", help="启动后直接打开云端登录窗口")
    parser.add_argument("--diagnose", action="store_true",
                        help="把进程检测结果写到 %%TEMP%%\\bambumon-diagnose.txt 后退出")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    if args.diagnose:
        import tempfile
        from pathlib import Path

        from bambu_monitor.procwatch import bambu_studio_running, running_process_names

        names = sorted(running_process_names())
        text = (
            f"total={len(names)}\nbambu_studio_running={bambu_studio_running()}\n"
            + "\n".join(names)
        )
        # 优先写到程序所在目录（最可能可写），再退到临时目录
        targets = []
        if getattr(sys, "frozen", False):
            targets.append(Path(sys.executable).resolve().parent / "bambumon-diagnose.txt")
        targets.append(Path(tempfile.gettempdir()) / "bambumon-diagnose.txt")
        for path in targets:
            try:
                path.write_text(text, encoding="utf-8")
                break
            except OSError:
                continue
        return 0

    setup_logging()
    LOG.info("启动 %s v%s", APP_TITLE, __version__)

    cfg = Config()
    i18n.set_language(cfg.get("app", "language", "zh"))
    i18n.install_tk_patches()
    notifier = Notifier(cfg)

    if args.test_notify:
        notifier.notify(
            "测试通知：打印完成 🎉",
            "「测试模型.3mf」打印完成，可以取件了。看到这条说明通知正常。",
            level="success",
            sound="finish",
            footer="拓竹打印监控",
        )
        print("已发送测试通知，请查看屏幕右下角。")
        return 0

    if not acquire_single_instance():
        from tkinter import messagebox, Tk

        root = Tk()
        root.withdraw()
        messagebox.showinfo(
            APP_TITLE,
            "监控程序已经在运行了。\n\n"
            "如果没看到窗口，去任务栏点一下「拓竹打印监控」——"
            "点叉号只是把它缩到任务栏，进程仍在后台盯着打印机。\n"
            "想彻底退出：打开窗口后点右下角「退出程序」。",
        )
        root.destroy()
        return 0

    try:
        app = App(cfg, notifier, start_minimized=args.minimized)
        if args.demo:
            app.demo()
        if args.settings:
            app.root.after(400, app.open_settings)
        if args.cloud_login:
            app._cloud_prompted = True   # 手动打开过了，别再自动弹一次
            app.root.after(600, app.open_cloud_login)
        app.run()
    except Exception:
        LOG.exception("运行出错")
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
