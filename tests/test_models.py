"""机型识别测试。"""
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

from bambu_monitor import models  # noqa: E402


def check(name, cond, extra=""):
    print(("  ok   " if cond else "  FAIL ") + name + (f"  <- {extra}" if extra and not cond else ""))
    return cond


def main() -> int:
    ok = True
    print("代号 -> 名称")
    ok &= check("N1 = A1 mini", models.display_name("N1") == "A1 mini", models.display_name("N1"))
    ok &= check("C12 = P1S", models.display_name("C12") == "P1S")
    ok &= check("C11 = P1P", models.display_name("C11") == "P1P")
    ok &= check("N2S = A1", models.display_name("N2S") == "A1")
    ok &= check("BL-P001 = X1 Carbon", models.display_name("BL-P001") == "X1 Carbon")
    ok &= check("未知代号返回空", models.display_name("ZZZ") == "")

    print("\n从 get_version 解析（A1 mini 的真实结构）")
    info = {
        "command": "get_version",
        "sequence_id": "0",
        "module": [
            {"name": "ota", "sw_ver": "01.04.00.00", "hw_ver": "", "sn": ""},
            {"name": "esp32", "sw_ver": "00.00.00.00", "hw_ver": "AP05", "sn": "", "project_name": "N1"},
            {"name": "mc", "sw_ver": "00.00.00.00", "hw_ver": "MC07", "sn": ""},
        ],
    }
    ok &= check("解析出 A1 mini", models.from_get_version(info) == "A1 mini",
                models.from_get_version(info))
    ok &= check("空数据不报错", models.from_get_version({}) == "")
    ok &= check("脏数据不报错", models.from_get_version({"module": "x"}) == "")

    print("\n腔体温度传感器")
    ok &= check("A1 mini 无腔温", not models.has_chamber_sensor("A1 mini"))
    ok &= check("X1 Carbon 有腔温", models.has_chamber_sensor("X1 Carbon"))
    ok &= check("未知机型按有传感器处理", models.has_chamber_sensor(""))

    print("\n手动机型规范化")
    ok &= check("自动识别 -> 空", models.normalize("自动识别") == "")
    ok &= check("a1 mini -> A1 mini", models.normalize("A1 mini") == "A1 mini")
    ok &= check("代号 N1 -> A1 mini", models.normalize("N1") == "A1 mini")

    print(f"\nBambu Studio 机型库扫描: {len(models.all_models())} 个")
    print("通过" if ok else "有失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
