"""机型识别。

拓竹的 MQTT `info.get_version` 会返回一组模块信息，其中带 `project_name`
的那一项就是机型代号（例如 N1 对应 A1 mini）。代号到中文/英文名的映射
来自 Bambu Studio 自带的机型定义文件（%APPDATA%\\BambuStudio\\printers\\*.json）。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

LOG = logging.getLogger(__name__)

# 机型代号 -> 显示名（取自 Bambu Studio printers/*.json 的 display_name）
MODEL_NAMES: dict[str, str] = {
    "BL-P001": "X1 Carbon",
    "BL-P002": "X1",
    "C11": "P1P",
    "C12": "P1S",
    "C13": "X1E",
    "N1": "A1 mini",
    "N2S": "A1",
    "N7": "P2S",
    "O1C": "H2C",
    "O1C2": "H2C",
    "O1D": "H2D",
    "O1E": "H2D Pro",
    "O1S": "H2S",
}

# 设置里可选的手动机型（按常见程度排）
CHOICES = [
    "A1 mini",
    "A1",
    "P1S",
    "P1P",
    "P2S",
    "X1 Carbon",
    "X1",
    "X1E",
    "H2D",
    "H2D Pro",
    "H2C",
    "H2S",
]

# 没有腔体温度传感器的机型（固件会固定上报一个占位值）
NO_CHAMBER_SENSOR = {"A1 mini", "A1", "P1P", "P1S"}


def display_name(model_id: str | None) -> str:
    if not model_id:
        return ""
    key = str(model_id).strip().upper()
    if key in MODEL_NAMES:
        return MODEL_NAMES[key]
    # 已经是显示名就直接用
    if model_id in MODEL_NAMES.values():
        return model_id
    return ""


def _scan_bambu_studio_models() -> dict[str, str]:
    """从本机 Bambu Studio 的机型定义里补全映射（新机型不至于认不出）。"""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return {}
    d = Path(appdata) / "BambuStudio" / "printers"
    if not d.is_dir():
        return {}
    found: dict[str, str] = {}
    try:
        for f in d.glob("*.json"):
            if f.name == "filaments_blacklist.json":
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                data = json.loads(text)
            except Exception:
                continue
            name = ""
            for v in data.values() if isinstance(data, dict) else []:
                if isinstance(v, dict) and v.get("display_name"):
                    name = str(v["display_name"])
                    break
            if not name:
                continue
            if name.lower().startswith("bambu lab "):
                name = name[10:]
            found[f.stem.upper()] = name
    except Exception as e:
        LOG.debug("扫描 Bambu Studio 机型定义失败: %s", e)
    return found


def all_models() -> dict[str, str]:
    merged = dict(MODEL_NAMES)
    merged.update({k: v for k, v in _scan_bambu_studio_models().items() if k not in merged})
    return merged


def from_get_version(info: dict) -> str:
    """从 info.get_version 的响应里推断机型，失败返回空串。"""
    if not isinstance(info, dict):
        return ""
    modules = info.get("module")
    if not isinstance(modules, list):
        return ""
    # 1) 优先看 project_name（就是机型代号）
    for m in modules:
        if not isinstance(m, dict):
            continue
        pn = str(m.get("project_name") or "").strip()
        if pn:
            name = display_name(pn)
            if name:
                return name
    # 2) 退一步看 product_name（云端绑定/新固件里可能有）
    for key in ("product_name", "printer_type", "machine_name", "model"):
        val = info.get(key)
        if isinstance(val, str) and val.strip():
            name = display_name(val)
            if name:
                return name
            if val.lower().startswith("bambu lab "):
                return val[10:]
    return ""


def normalize(name: str | None) -> str:
    """把手动填的值规范化成显示名。"""
    if not name:
        return ""
    n = str(name).strip()
    if not n or n.lower() in ("auto", "自动", "自动识别", "auto detect", "autodetect"):
        return ""
    if n in MODEL_NAMES.values() or n in CHOICES:
        return n
    return display_name(n) or n


def has_chamber_sensor(model: str) -> bool:
    if not model:
        return True  # 未知机型时按有传感器处理，避免误隐藏
    return model not in NO_CHAMBER_SENSOR
