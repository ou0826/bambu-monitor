"""状态判定单元测试（不依赖打印机）。

运行: python tests/test_watcher.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _s in (sys.stdout, sys.stderr):
    try:
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(errors="replace")
    except Exception:
        pass

from bambu_monitor.state import (  # noqa: E402
    CANCEL_PRINT_ERROR,
    ERROR,
    SUCCESS,
    WARNING,
    Watcher,
)


def frame(**kw) -> dict:
    return {"print": kw}


def check(name: str, cond: bool, extra: str = "") -> bool:
    print(("  ok   " if cond else "  FAIL ") + name + (f"  <- {extra}" if extra and not cond else ""))
    return cond


def test_finish() -> bool:
    print("打印完成")
    w = Watcher()
    w.feed(frame(gcode_state="RUNNING", mc_percent=80, subtask_name="测试.3mf", task_id="1"))
    evs = w.feed(frame(gcode_state="FINISH", mc_percent=100))
    ok = check("产生 1 个完成事件", len(evs) == 1 and evs[0].kind == "finish", str(evs))
    ok &= check("级别为 success", evs and evs[0].level == SUCCESS)
    ok &= check("带文件名的正文", evs and "测试.3mf" in evs[0].body, evs[0].body if evs else "")
    # 重复上报 FINISH 不应重复通知
    evs2 = w.feed(frame(gcode_state="FINISH"))
    ok &= check("重复 FINISH 不重复通知", len(evs2) == 0, str(evs2))
    return ok


def test_pause_runout() -> bool:
    print("暂停：断料（stg_cur=6）")
    w = Watcher()
    w.feed(frame(gcode_state="RUNNING", mc_percent=55, subtask_name="A.3mf"))
    evs = w.feed(frame(gcode_state="PAUSE", stg_cur=6))
    ok = check("产生暂停事件", len(evs) == 1 and evs[0].kind == "pause", str(evs))
    ok &= check("需要人工处理", evs and evs[0].need_action)
    ok &= check("提示耗材用完", evs and "耗材" in evs[0].title, evs[0].title if evs else "")
    ok &= check("级别 warning", evs and evs[0].level == WARNING)
    return ok


def test_pause_user() -> bool:
    print("暂停：用户手动（stg_cur=16）")
    w = Watcher()
    w.feed(frame(gcode_state="RUNNING"))
    evs = w.feed(frame(gcode_state="PAUSE", stg_cur=16))
    return check("提示为用户暂停", evs and "暂停" in evs[0].title, evs[0].title if evs else "")


def test_hms() -> bool:
    print("HMS 告警")
    w = Watcher()
    w.feed(frame(gcode_state="RUNNING", hms=[]))
    # attr=0x07002000 -> 模块 AMS，severity=(attr>>8)&0xF=0x20&0xF=0 ?
    evs = w.feed(frame(hms=[{"attr": 0x07002000, "code": 0x00020001}]))
    ok = check("产生告警事件", len(evs) == 1 and evs[0].kind == "hms", str(evs))
    ok &= check("带 HMS 编码", evs and "0700_2000_0002_0001" in evs[0].body,
                evs[0].body if evs else "")
    ok &= check("识别 AMS 模块", evs and "AMS" in evs[0].title, evs[0].title if evs else "")
    # 同一条告警重复上报不重复通知
    evs2 = w.feed(frame(hms=[{"attr": 0x07002000, "code": 0x00020001}]))
    ok &= check("重复告警不重复通知", len(evs2) == 0, str(evs2))
    # 告警消失后再出现，应重新通知
    w.feed(frame(hms=[]))
    evs3 = w.feed(frame(hms=[{"attr": 0x07002000, "code": 0x00020001}]))
    ok &= check("告警恢复后再次出现会重新通知", len(evs3) == 1, str(evs3))
    return ok


def test_cancel() -> bool:
    print("用户取消打印")
    w = Watcher()
    w.feed(frame(gcode_state="RUNNING", print_error=0))
    evs = w.feed(frame(gcode_state="IDLE", print_error=CANCEL_PRINT_ERROR))
    ok = check("识别为取消而非故障", any(e.kind == "cancel" for e in evs), str(evs))
    ok &= check("不标记需要处理", all(not e.need_action for e in evs))
    return ok


def test_failed() -> bool:
    print("打印失败")
    w = Watcher()
    w.feed(frame(gcode_state="RUNNING", subtask_name="B.3mf"))
    evs = w.feed(frame(gcode_state="FAILED"))
    ok = check("产生失败事件", any(e.kind == "fail" and e.level == ERROR for e in evs), str(evs))
    ok &= check("需要人工处理", any(e.need_action for e in evs))
    return ok


def test_print_error_code() -> bool:
    print("非零 print_error")
    w = Watcher()
    w.feed(frame(gcode_state="RUNNING", print_error=0))
    evs = w.feed(frame(print_error=83902468))
    ok = check("产生异常事件", any(e.kind == "fail" for e in evs), str(evs))
    ok &= check("带错误码", any("0x" in e.body for e in evs), str([e.body for e in evs]))
    return ok


def test_ams_filament() -> bool:
    print("AMS 自动换料")
    w = Watcher()
    w.feed(frame(gcode_state="RUNNING", ams_status=0x0300))
    evs = w.feed(frame(ams_status=0x0105))  # 主状态 1=换料中，子步骤 5=送入新料
    ok = check("产生换料事件", any(e.kind == "filament" for e in evs), str(evs))
    ok &= check("带子步骤提示", any("送入新料" in e.body for e in evs), str([e.body for e in evs]))
    evs2 = w.feed(frame(ams_status=0x0105))
    ok &= check("同一换料步骤不重复通知", len(evs2) == 0, str(evs2))
    return ok


def test_delta_merge() -> bool:
    print("P1 增量合并")
    w = Watcher()
    w.feed(frame(gcode_state="RUNNING", mc_percent=10, ams={
        "ams": [{"id": "0", "humidity": "3", "tray": [
            {"id": "0", "tray_type": "PLA", "remain": 90},
            {"id": "1", "tray_type": "PETG", "remain": 50},
        ]}]
    }))
    # 只上报了变化的一个字段
    w.feed(frame(mc_percent=42))
    s = w.summary()
    ok = check("进度已更新", s["percent"] == 42, str(s["percent"]))
    ok &= check("状态未丢", s["gcode_state"] == "RUNNING", str(s["gcode_state"]))
    ok &= check("AMS 未被清空", len(s["ams"]) == 1 and len(s["ams"][0]["tray"]) == 2, str(s["ams"]))
    # AMS 局部更新（只报第 2 个料盘）
    w.feed(frame(ams={"ams": [{"id": "0", "tray": [{"id": "1", "remain": 12}]}]}))
    s = w.summary()
    trays = {t["id"]: t for t in s["ams"][0]["tray"]}
    ok &= check("料盘 0 保留", trays["0"]["tray_type"] == "PLA", str(trays))
    ok &= check("料盘 1 已更新", trays["1"]["remain"] == 12, str(trays["1"]))
    ok &= check("料盘 1 类型保留", trays["1"]["tray_type"] == "PETG", str(trays["1"]))
    return ok


def test_start_and_reconnect() -> bool:
    print("首帧与重连")
    w = Watcher()
    # 首帧就是 FINISH（程序刚打开，任务早就完成）-> 不应打扰
    evs = w.feed(frame(gcode_state="FINISH", subtask_name="旧.3mf"))
    ok = check("首帧 FINISH 不通知", len(evs) == 0, str(evs))
    # 首帧就是 PAUSE -> 需要提醒
    w2 = Watcher()
    evs2 = w2.feed(frame(gcode_state="PAUSE", stg_cur=6))
    ok &= check("首帧 PAUSE 提醒", len(evs2) == 1 and evs2[0].kind == "pause", str(evs2))
    # 断开重连后状态相同，不应重复
    w3 = Watcher()
    w3.feed(frame(gcode_state="RUNNING", mc_percent=50, subtask_name="C.3mf"))
    w3.reset()
    evs3 = w3.feed(frame(gcode_state="RUNNING", mc_percent=50, subtask_name="C.3mf"))
    ok &= check("重连后不重复报开始", len(evs3) == 0, str(evs3))
    return ok


def main() -> int:
    tests = [
        test_finish, test_pause_runout, test_pause_user, test_hms, test_cancel,
        test_failed, test_print_error_code, test_ams_filament, test_delta_merge,
        test_start_and_reconnect,
    ]
    results = []
    for t in tests:
        try:
            results.append(bool(t()))
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e}")
            results.append(False)
        print()
    passed = sum(results)
    print(f"通过 {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
