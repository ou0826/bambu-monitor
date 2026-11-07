"""打印机状态合并与事件判定。

P1 系列只上报「发生变化的字段」，所以必须做增量合并；X1 系列每次上报全量。
合并后再与上一次快照比对，得出可通知的事件。
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field

from .i18n import t, tf

# 事件级别
SUCCESS = "success"
ERROR = "error"
WARNING = "warning"
INFO = "info"

# 用户主动取消打印时打印机会报这个 print_error
CANCEL_PRINT_ERROR = 50348044

# gcode_state -> 中文
GCODE_STATE_ZH = {
    "IDLE": "空闲",
    "PREPARE": "准备中",
    "RUNNING": "打印中",
    "PAUSE": "已暂停",
    "FINISH": "已完成",
    "FAILED": "失败",
    "SLICING": "切片中",
    "OFFLINE": "离线",
    "UNKNOWN": "未知",
}

# stg_cur 阶段（对应 BambuStudio 的当前阶段枚举）
STAGE_ZH = {
    0: "打印中",
    1: "自动调平",
    2: "热床预热",
    3: "振动补偿",
    4: "换料中",
    5: "M400 暂停",
    6: "断料暂停",
    7: "加热喷嘴",
    8: "挤出校准",
    9: "扫描热床",
    10: "检查首层",
    11: "识别打印板",
    12: "激光雷达校准",
    13: "回零",
    14: "清理喷嘴",
    15: "检查挤出机温度",
    16: "用户暂停",
    17: "前门/盖板检测",
    18: "激光雷达校准",
    19: "挤出流量校准",
    20: "喷嘴温度异常",
    21: "热床温度异常",
    22: "退料中",
    23: "丢步暂停",
    24: "进料中",
    25: "电机噪声校准",
    26: "AMS 连接丢失",
    27: "热端风扇异常",
    28: "腔温控制异常",
    29: "腔体降温",
    30: "G-code 暂停",
    31: "电机演示",
    32: "喷嘴裹料",
    33: "切刀异常",
    34: "首层异常",
    35: "喷嘴堵塞",
    36: "绝对精度检查",
    37: "绝对精度校准",
    38: "绝对精度检查",
    39: "喷嘴偏置校准",
    40: "高温热床调平",
    41: "快拆检测",
    42: "门盖检测",
    43: "激光校准",
    44: "平台检查",
    45: "相机位置检查",
    46: "相机校准",
    47: "热床调平 1/2",
    48: "热床调平 2/2",
    49: "腔体加热",
    50: "热床冷却",
    51: "打印校准线",
    52: "材料检查",
    53: "相机校准",
    54: "等待热床温度",
    55: "材料位置检查",
    56: "切刀偏置校准",
    57: "表面测量",
    58: "热预处理",
    59: "刀架回零",
    60: "相机偏置校准",
    61: "刀架位置校准",
    62: "热端交换测试",
    63: "等待腔温平衡",
    64: "准备热端",
    65: "裹料检测校准",
    66: "腔体净化",
    67: "旋转附件测量",
    68: "移动到废料槽",
    69: "喷嘴降温",
    70: "移动到热床中心",
    71: "圆弧拟合",
    72: "热端类型检测",
    73: "打印板对齐检测",
    74: "热床异物检测",
    75: "热床背面异物检测",
    76: "打印前预挤出",
    77: "准备 AMS",
    -1: "空闲",
    255: "空闲",
}

# 会让打印「停下来等你」的阶段，附处理建议
PAUSE_ADVICE = {
    6: ("耗材用完了", "装上新的料卷（或让 AMS 换到有料的槽位），然后点继续"),
    4: ("需要换料", "按屏幕提示装好新耗材，然后点继续"),
    22: ("正在退料", "等退料结束后按提示装料"),
    24: ("正在进料", "确认料管通畅，等待进料完成"),
    17: ("前门/盖板检测触发", "检查前门与上盖是否关闭到位"),
    20: ("喷嘴温度异常", "检查喷嘴加热器与热敏电阻，重试或联系售后"),
    21: ("热床温度异常", "检查热床排线与温度传感器"),
    23: ("运动丢步", "清理导轨异物后继续；反复出现需检查皮带张紧"),
    26: ("AMS 连接丢失", "检查 AMS 与打印机的连接线、重新插拔"),
    27: ("热端散热风扇异常", "检查风扇是否被异物卡住"),
    28: ("腔体温度控制异常", "检查腔体加热/风扇"),
    30: ("G-code 主动暂停", "确认打印件状态后点继续"),
    32: ("喷嘴被耗材包裹", "清理喷嘴外的溢料后继续"),
    33: ("切刀异常", "检查切刀机构是否有料屑卡住"),
    34: ("首层检测异常", "检查打印板是否干净、贴平"),
    35: ("喷嘴堵塞", "清理/更换喷嘴后继续"),
    5: ("G-code 触发暂停", "确认后点继续"),
    16: ("你手动暂停了打印", "需要时点继续"),
}

# HMS attr 的最高字节是模块编号（HMS 码形如 0700_2000_0002_0001，前两位即模块）
HMS_MODULES = {
    0x03: "运动控制",
    0x05: "主板",
    0x07: "AMS",
    0x08: "工具头",
    0x0C: "视觉模块",
}
HMS_ADVICE = {
    "主板": "多为整机通信/供电类提示，可重启打印机后观察",
    "视觉模块": "检查摄像头/激光雷达处是否有遮挡或脏污",
    "AMS": "检查耗材是否卡住、料管是否插紧、AMS 是否识别到料卷",
    "工具头": "检查喷嘴、热端、切刀、风扇等部件",
    "运动控制": "检查导轨、皮带与是否有异物阻挡",
}

# AMS 主状态
AMS_MAIN_ZH = {
    0x00: "空闲",
    0x01: "换料中",
    0x02: "识别 RFID",
    0x03: "已装料",
    0x04: "校准中",
    0x07: "冷拔",
    0x10: "自检",
    0x20: "调试",
}
AMS_STEP_ZH = {
    0x02: "加热喷嘴",
    0x03: "切断耗材",
    0x04: "回抽旧料",
    0x05: "送入新料",
    0x06: "送入新料",
    0x07: "冲刷旧料",
    0x08: "检测位置",
    0x0B: "检测位置",
}

# 变更检测关注的一级字段
WATCH_KEYS = (
    "gcode_state",
    "print_error",
    "stg_cur",
    "ams_status",
    "mc_percent",
    "mc_remaining_time",
    "subtask_name",
    "layer_num",
    "total_layer_num",
)


@dataclass
class Event:
    kind: str                 # start/finish/fail/pause/resume/cancel/filament/hms/runout/offline/online
    level: str = INFO
    title: str = ""
    body: str = ""
    need_action: bool = False
    sound: str = ""
    ts: float = field(default_factory=time.time)
    detail: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# 增量合并
# --------------------------------------------------------------------------
def deep_merge(dst: dict, src: dict) -> dict:
    """把打印机上报的增量合并进已有状态。

    规则：
      * dict 递归合并
      * 元素带 "id" 的 list（AMS 单元、料盘）按 id 合并
      * 其他 list（hms 等）整体替换
    """
    for k, v in src.items():
        if isinstance(v, dict):
            cur = dst.get(k)
            if not isinstance(cur, dict):
                cur = {}
                dst[k] = cur
            deep_merge(cur, v)
        elif isinstance(v, list):
            cur = dst.get(k)
            if (
                isinstance(cur, list)
                and v
                and isinstance(v[0], dict)
                and "id" in v[0]
            ):
                merged: dict[str, dict] = {}
                order: list[str] = []
                for item in cur:
                    if isinstance(item, dict) and "id" in item:
                        key = str(item["id"])
                        merged[key] = item
                        order.append(key)
                for item in v:
                    if not isinstance(item, dict):
                        continue
                    key = str(item.get("id"))
                    if key in merged:
                        deep_merge(merged[key], item)
                    else:
                        merged[key] = copy.deepcopy(item)
                        order.append(key)
                dst[k] = [merged[i] for i in order]
            else:
                dst[k] = copy.deepcopy(v)
        else:
            dst[k] = v
    return dst


def _remaining_text(minutes) -> str:
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        return ""
    if m <= 0:
        return ""
    if m >= 60:
        if m % 60:
            return tf("约 {h} 小时 {mm} 分", h=m // 60, mm=m % 60)
        return tf("约 {h} 小时", h=m // 60)
    return tf("约 {m} 分钟", m=m)


def hms_code_text(item: dict) -> str:
    """HMS（健康管理系统）错误 -> 形如 0700_2000_0002_0001 的字符串。"""
    try:
        attr = int(item.get("attr", 0))
        code = int(item.get("code", 0))
    except (TypeError, ValueError):
        return "未知告警"
    a = f"{attr & 0xFFFFFFFF:08X}"
    c = f"{code & 0xFFFFFFFF:08X}"
    return f"{a[0:4]}_{a[4:8]}_{c[0:4]}_{c[4:8]}"


def hms_module(item: dict) -> str:
    try:
        attr = int(item.get("attr", 0))
    except (TypeError, ValueError):
        return "未知模块"
    return HMS_MODULES.get((attr >> 24) & 0xFF, "未知模块")


def hms_severity(item: dict) -> int:
    """严重度提示：1/2 致命或严重，3 一般，4 提示；0 表示未知（按告警处理）。

    不同固件对这个字段的排布并不完全一致，所以这里只用来「降级」，
    不会把未知的报错当成小问题忽略掉。
    """
    try:
        attr = int(item.get("attr", 0))
    except (TypeError, ValueError):
        return 0
    return (attr >> 8) & 0x0F


class Watcher:
    """吃打印机上报的 JSON，吐出需要通知的事件。"""

    def __init__(self) -> None:
        self.state: dict = {"print": {}}
        self._prev: dict = {}
        self._hms_seen: set = set()
        self._last_ams_status: int | None = None
        self._last_finish_key: str | None = None
        self.online = False

    # ---------- 辅助 ----------
    @property
    def print(self) -> dict:
        p = self.state.get("print")
        return p if isinstance(p, dict) else {}

    def snapshot(self) -> dict:
        p = self.print
        snap = {k: p.get(k) for k in WATCH_KEYS}
        snap["hms"] = copy.deepcopy(p.get("hms") or [])
        return snap

    def reset(self) -> None:
        self.state = {"print": {}}
        self._prev = {}
        self._hms_seen = set()
        self._last_ams_status = None
        self.online = False

    def new_job(self) -> None:
        """开始新任务时清掉任务级去重标记。"""
        self._hms_seen = set()
        self._last_ams_status = None
        self._last_finish_key = None

    # ---------- 派生信息（给 UI 用） ----------
    def summary(self) -> dict:
        p = self.print
        gs = str(p.get("gcode_state", "")).upper()
        stg = p.get("stg_cur")
        ams_status = p.get("ams_status")
        ams_main = ams_sub = None
        if isinstance(ams_status, int):
            ams_main = (ams_status >> 8) & 0xFF
            ams_sub = ams_status & 0xFF
        hms = p.get("hms") or []
        stage_text = t(STAGE_ZH.get(stg, f"阶段 {stg}")) if isinstance(stg, int) else ""
        if gs == "RUNNING" and stage_text in ("空闲",):
            stage_text = "打印中"
        return {
            "online": self.online,
            "gcode_state": gs,
            "state_text": t(GCODE_STATE_ZH.get(gs, gs or "未知")),
            "stage_text": stage_text,
            "percent": p.get("mc_percent"),
            "remaining": p.get("mc_remaining_time"),
            "remaining_text": _remaining_text(p.get("mc_remaining_time")),
            "layer": p.get("layer_num"),
            "total_layer": p.get("total_layer_num"),
            "file": p.get("subtask_name") or "",
            "gcode_file": p.get("gcode_file") or "",
            "nozzle": p.get("nozzle_temper"),
            "nozzle_target": p.get("nozzle_target_temper"),
            "bed": p.get("bed_temper"),
            "bed_target": p.get("bed_target_temper"),
            "chamber": p.get("chamber_temper"),
            "wifi": p.get("wifi_signal"),
            "speed": p.get("spd_lvl"),
            "print_error": p.get("print_error") or 0,
            "hms": hms,
            "ams": (p.get("ams") or {}).get("ams") or [],
            "vt_tray": p.get("vt_tray") or {},
            "ams_main": ams_main,
            "ams_sub": ams_sub,
            "ams_text": AmsText(ams_main, ams_sub),
        }

    # ---------- 主入口 ----------
    def feed(self, payload: dict) -> list[Event]:
        events: list[Event] = []
        if not isinstance(payload, dict):
            return events
        incoming = payload.get("print")
        if not isinstance(incoming, dict):
            return events

        prev = self.snapshot()
        had_state = bool(self.print.get("gcode_state"))

        if not had_state:
            # 第一帧：只记录历史告警，不把「已经完成」的旧任务当新事件；
            # 但「已经暂停」的打印确实需要人处理，要提醒。
            deep_merge(self.state, payload)
            p = self.print
            gs = str(p.get("gcode_state", "")).upper()
            if gs == "PAUSE":
                self._announce_state(events, gs, "", p)
            self._hms_seen = {(i.get("attr"), i.get("code")) for i in (p.get("hms") or [])}
            if isinstance(p.get("ams_status"), int):
                self._last_ams_status = p["ams_status"]
            return events

        deep_merge(self.state, payload)
        p = self.print

        gs = str(p.get("gcode_state", "")).upper()
        prev_gs = str(prev.get("gcode_state", "")).upper()
        if gs and gs != prev_gs:
            self._announce_state(events, gs, prev_gs, p)

        # ---- print_error ----
        try:
            err = int(p.get("print_error") or 0)
            prev_err = int(prev.get("print_error") or 0)
        except (TypeError, ValueError):
            err = prev_err = 0
        if err and err != prev_err:
            if err == CANCEL_PRINT_ERROR:
                events.append(
                    Event(
                        "cancel",
                        INFO,
                        t("打印已取消"),
                        tf("「{name}」已被取消", name=self._job_name(p)),
                        sound="attention",
                    )
                )
            else:
                events.append(
                    Event(
                        "fail",
                        ERROR,
                        t("打印异常停止"),
                        tf("打印机上报错误码 0x{code:X}（{code}），请在打印机屏幕上确认原因", code=err),
                        need_action=True,
                        sound="error",
                        detail={"print_error": err},
                    )
                )

        # ---- HMS 告警 ----
        if "hms" in incoming:
            current = {(i.get("attr"), i.get("code")) for i in (p.get("hms") or [])}
            fresh = [i for i in (p.get("hms") or []) if (i.get("attr"), i.get("code")) not in self._hms_seen]
            self._hms_seen = current
            if fresh:
                ev = self._hms_event(fresh)
                if ev:
                    events.append(ev)

        # ---- AMS 换料 ----
        ams_status = p.get("ams_status")
        if isinstance(ams_status, int):
            main = (ams_status >> 8) & 0xFF
            sub = ams_status & 0xFF
            if main == 0x01 and ams_status != self._last_ams_status:
                step = t(AMS_STEP_ZH.get(sub, ""))
                body = t("AMS 正在自动换料") + (tf("：{step}", step=step) if step else "")
                events.append(
                    Event("filament", INFO, "正在换料", body, sound="attention")
                )
            self._last_ams_status = ams_status

        # ---- 暂停：给出具体原因 ----
        # _announce_state 已产生 pause 事件，这里补充 stg_cur 变化场景
        if gs == "PAUSE" and prev_gs == "PAUSE":
            stg = p.get("stg_cur")
            if isinstance(stg, int) and stg != prev.get("stg_cur") and stg in PAUSE_ADVICE:
                reason, advice = PAUSE_ADVICE[stg]
                events.append(
                    Event(
                        "pause",
                        WARNING,
                        tf("暂停原因变化：{reason}", reason=reason),
                        advice,
                        need_action=True,
                        sound="attention",
                        detail={"stage": stg},
                    )
                )

        self._prev = prev
        return events

    # ---------- 内部 ----------
    @staticmethod
    def _job_name(p: dict) -> str:
        return (p.get("subtask_name") or p.get("gcode_file") or "当前任务").strip()

    def _announce_state(self, events: list[Event], gs: str, prev_gs: str, p: dict) -> None:
        name = self._job_name(p)
        pct = p.get("mc_percent")
        remain = _remaining_text(p.get("mc_remaining_time"))

        if gs == "FINISH":
            key = f"{p.get('task_id')}:{p.get('subtask_id')}:{name}"
            if key != self._last_finish_key:
                self._last_finish_key = key
                body = tf("「{name}」打印完成", name=name)
                if remain:
                    body += tf("，剩余时间 {remain}", remain=remain)
                events.append(
                    Event(
                        "finish",
                        SUCCESS,
                        t("打印完成 🎉"),
                        body + t("。可以取件了"),
                        sound="finish",
                        detail={"file": name},
                    )
                )
        elif gs == "FAILED":
            events.append(
                Event(
                    "fail",
                    ERROR,
                    t("打印失败"),
                    tf("「{name}」打印失败，请在打印机屏幕或 Bambu Studio 查看原因", name=name),
                    need_action=True,
                    sound="error",
                )
            )
        elif gs == "PAUSE":
            stg = p.get("stg_cur")
            reason = advice = ""
            if isinstance(stg, int) and stg in PAUSE_ADVICE:
                reason, advice = PAUSE_ADVICE[stg]
            hms = p.get("hms") or []
            if not reason and hms:
                item = hms[0]
                reason = tf("{module}提示", module=t(hms_module(item)))
                advice = t(HMS_ADVICE.get(hms_module(item), "请在打印机屏幕上查看提示"))
            title = tf("打印已暂停：{reason}", reason=reason) if reason else t("打印已暂停")
            body = advice or t("请在打印机或 Bambu Studio 中确认后继续")
            if pct not in (None, ""):
                body += tf("（已打印 {pct}%）", pct=pct)
            events.append(
                Event(
                    "pause",
                    WARNING,
                    title,
                    body,
                    need_action=True,
                    sound="attention",
                    detail={"stage": stg},
                )
            )
        elif gs == "RUNNING" and prev_gs in ("PAUSE",):
            events.append(
                Event("resume", INFO, t("打印已恢复"), tf("「{name}」继续打印中", name=name), sound="")
            )
        elif gs == "RUNNING" and prev_gs in ("IDLE", "FINISH", "FAILED", "PREPARE", ""):
            self.new_job()
            events.append(
                Event(
                    "start",
                    INFO,
                    t("开始打印"),
                    tf("「{name}」开始打印", name=name),
                    sound="",
                    detail={"file": name},
                )
            )

    def _hms_event(self, fresh: list[dict]) -> Event | None:
        first = fresh[0]
        module = hms_module(first)
        sev = hms_severity(first)
        code = hms_code_text(first)
        more = "" if len(fresh) == 1 else tf(" 等 {n} 项", n=len(fresh))
        # 严重度：1 致命 / 2 严重 / 3 一般 / 4 提示
        if sev in (1, 2):
            level, title_tmpl, act = ERROR, "打印机故障：{module}", True
        elif sev == 3:
            level, title_tmpl, act = WARNING, "打印机告警：{module}", True
        else:
            level, title_tmpl, act = INFO, "打印机提示：{module}", False
        advice = t(HMS_ADVICE.get(module, "请在打印机屏幕上查看提示"))
        return Event(
            "hms",
            level,
            tf(title_tmpl, module=t(module)),
            tf("HMS {code}{more}。{advice}", code=code, more=more, advice=advice),
            need_action=act,
            sound="error" if level == ERROR else "attention",
            detail={"codes": [hms_code_text(i) for i in fresh], "module": module, "severity": sev},
        )


def AmsText(main, sub) -> str:
    if main is None:
        return ""
    if main == 0x01:
        step = t(AMS_STEP_ZH.get(sub, ""))
        return t("换料中") + (f"·{step}" if step else "")
    return t(AMS_MAIN_ZH.get(main, "未知"))
