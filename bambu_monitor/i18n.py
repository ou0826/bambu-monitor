"""界面中英双语。

思路：界面上绝大多数字符串都是写死的构造参数（`tk.Label(text="设置")`），
所以这里做两件事：

1. `t(s)` / `tf(tpl, **kw)`：按"中文原文"查表翻译，查不到就原样返回；
2. `install_tk_patches()`：给 tkinter 的 Label / Button / Checkbutton / Toplevel
   等控件打补丁，创建和 configure 时自动把 text / title 过一遍 `t()`。

这样不用把 400 多处调用点逐个改掉，也不会漏掉运行时更新的文本。

语言由 config 里的 `app.language` 决定，启动时调用 `set_language()`。
"""
from __future__ import annotations

import logging

LOG = logging.getLogger(__name__)

LANG = "zh"


def set_language(lang: str | None) -> None:
    global LANG
    name = str(lang or "zh").strip().lower()
    LANG = "en" if name.startswith("en") else "zh"


def is_en() -> bool:
    return LANG == "en"


def t(text):
    """查表翻译；不是英文字符串、或表里没有，就原样返回。"""
    if LANG != "en" or not isinstance(text, str):
        return text
    return EN.get(text, text)


def tf(template: str, **kwargs):
    """带占位符的模板翻译：tf("已连接 {host}", host="1.2.3.4")。"""
    s = t(template)
    if not kwargs:
        return s
    try:
        return s.format(**kwargs)
    except Exception:
        return s


# --------------------------------------------------------------------------
# 中文原文 -> English
# --------------------------------------------------------------------------
EN: dict[str, str] = {
    # ---------- 顶栏 / 状态栏 ----------
    "拓竹打印监控": "BambuMonitor",
    "设置": "Settings",
    "连接": "Connect",
    "断开": "Disconnect",
    "退出": "Quit",
    "就绪": "Ready",
    "English": "中文",
    "未配置打印机": "No printer configured",
    "未配置打印机，请点「设置」": "No printer configured — open Settings",
    "局域网": "LAN",
    "云端": "Cloud",
    "在线": "Online",
    "离线": "Offline",
    "未连接": "Not connected",
    # ---------- 卡片标题 ----------
    "打印状态": "Print status",
    "温度": "Temperatures",
    "AMS 料盘": "AMS trays",
    "事件记录": "Event log",
    # ---------- 指标 ----------
    "进度": "Progress",
    "层数": "Layers",
    "剩余时间": "Time left",
    "已用": "Elapsed",
    "喷嘴": "Nozzle",
    "热床": "Bed",
    "腔体": "Chamber",
    # ---------- 打印状态 ----------
    "空闲": "Idle",
    "准备中": "Preparing",
    "打印中": "Printing",
    "已暂停": "Paused",
    "已完成": "Finished",
    "失败": "Failed",
    "切片中": "Slicing",
    "未知": "Unknown",
    "当前任务": "current job",
    # ---------- 按钮 ----------
    "暂停": "Pause",
    "继续": "Resume",
    "停止打印": "Stop print",
    "测试通知": "Test alert",
    "保存": "Save",
    "取消": "Cancel",
    "登录": "Log in",
    "登录 / 更换账号": "Log in / switch account",
    "发送验证码": "Send code",
    "发送短信验证码": "Send SMS code",
    "发送邮件验证码": "Send e-mail code",
    "显示": "Show",
    "自动搜索打印机": "Auto-discover",
    "从 Bambu Studio 导入访问码": "Import access code",
    "测试连接": "Test connection",
    "试听/测试通知": "Preview / test alert",
    # ---------- 设置：连接 ----------
    "打印机连接": "Printer connection",
    "IP 地址": "IP address",
    "序列号": "Serial",
    "访问码": "Access code",
    "机型": "Model",
    "自动识别": "Auto-detect",
    "跨网络（云端）": "Cross-network (Cloud)",
    "通过拓竹云连接（打印机不在同一网络时用）":
        "Relay through Bambu Cloud (when the printer is on another network)",
    # ---------- 设置：通知 ----------
    "提醒方式": "How to alert",
    "系统通知": "Windows toast",
    "置顶弹窗": "Topmost popup",
    "提示音": "Sound",
    "需要处理时重复提醒": "Repeat when action is needed",
    "弹窗停留(秒)": "Popup seconds",
    # ---------- 设置：触发事件 ----------
    "触发事件": "Events",
    "开始打印": "Print started",
    "打印完成": "Print finished",
    "打印失败": "Print failed",
    "打印暂停": "Print paused",
    "打印取消": "Print cancelled",
    "换料提醒": "Filament change",
    "故障告警": "Machine alert",
    "连接断开": "Connection lost",
    # ---------- 设置：行为 ----------
    "启动后自动连接打印机": "Connect automatically on start",
    "开机自动启动": "Start with Windows",
    "启动时最小化": "Start minimised",
    "打开 Bambu Studio 时自动显示并连接": "Show and connect when Bambu Studio starts",
    "关闭 Bambu Studio 时最小化": "Minimise when Bambu Studio closes",
    "点关闭按钮时直接退出程序（默认只是缩到任务栏继续监控）":
        "Quit when the window is closed (default: keep running in the tray)",
    "提示：勾了「开机自动启动 + 启动时最小化」，开机后本程序在后台待命，":
        "Tip: with \"Start with Windows\" + \"Start minimised\", the app waits in the background;",
    "你打开 Bambu Studio 它就会自己出来。": "it pops up as soon as you open Bambu Studio.",
    "界面语言": "Language",
    "中文": "中文",
    # ---------- 连接失败 / 网络 ----------
    "连接已断开，正在自动重连…": "Disconnected — reconnecting…",
    "已断开": "Disconnected",
    "连不上打印机": "Cannot reach the printer",
    "请检查电源、WiFi 或打印是否被中断":
        "Check the power, the Wi-Fi, or whether the print was interrupted",
    "打印机失联": "Printer unreachable",
    "正在连接 {host} ...": "Connecting to {host} …",
    "已连接打印机": "Printer connected",
    "已连接": "Connected",
    "连接失败 {host}:{port}": "Connection failed {host}:{port}",
    "认证失败：{reason_code}": "Authentication failed: {reason_code}",
    "连接失败：{reason_code}（多半是访问码不对）":
        "Connection failed: {reason_code} (usually a wrong access code)",
    "与打印机的连接已断开": "Link to the printer was closed",
    "未连接打印机": "Printer not connected",
    "指令已发送": "Command sent",
    "指令发送失败": "Failed to send command",
    "正在扫描局域网（约 5-10 秒）...": "Scanning your LAN (5–10 s)…",
    "没有发现打印机。请确认打印机已开机且与本机在同一局域网（或手动填写 IP）。":
        "No printer found. Make sure it is powered on and on the same network as this PC "
        "(or type the IP manually).",
    "发现 {n} 台，点击选择即可填入。": "Found {n} printer(s) — click one to fill the fields.",
    "正在连接...": "Connecting…",
    "连接成功！当前状态 {state}，进度 {pct}%":
        "Connected. State {state}, progress {pct}%",
    "连接失败：{msg}": "Connection failed: {msg}",
    "请先填写 IP、序列号、访问码。": "Fill in the IP, serial and access code first.",
    "请填写打印机 IP；如果改用云端，勾上“通过拓竹云连接”。":
        "Enter the printer IP — or tick \"Relay through Bambu Cloud\" to use the cloud.",
    "没在 Bambu Studio 配置里找到访问码，请手动输入（打印机屏幕：设置 → 网络）。":
        "No access code found in Bambu Studio — enter it manually "
        "(printer: Settings → Network).",
    "已填入序列号 {serial} 的访问码。": "Filled in the access code for {serial}.",
    "找到 {n} 个访问码，但没有匹配当前序列号的，可先自动搜索。":
        "Found {n} access code(s) but none matches this serial — try auto-discover.",
    "已填入 Bambu Studio 中保存的访问码。": "Imported the access code from Bambu Studio.",
    # ---------- 云端登录 ----------
    "登录拓竹账号（跨网络监控）": "Sign in to Bambu (cross-network monitoring)",
    "打印机和你不在同一个网络？": "Is your printer on a different network?",
    "拓竹账号（邮箱或手机号）": "Bambu account (e-mail or phone)",
    "验证码": "Code",
    "密码": "Password",
    "（手机号登录填这个）": "(for phone accounts)",
    "或密码": "or password",
    "正在登录，请稍候...": "Signing in…",
    "正在发送验证码...": "Sending the code…",
    "验证码已发送，请查看邮箱（几分钟内有效）":
        "Code sent — check your mailbox (valid for a few minutes).",
    "验证码已通过短信发出，请查看手机（1~2 分钟内）":
        "Code sent by SMS — check your phone (within 1–2 minutes).",
    "验证码已发到你的邮箱，请查看邮件（几分钟内有效）":
        "Code sent to your e-mail — check your inbox (valid for a few minutes).",
    "发送失败：{msg}": "Failed to send: {msg}",
    "请先填账号": "Enter your account first",
    "请先填账号（手机号或邮箱）": "Enter your account (phone or e-mail) first",
    "请填密码（手机号账号）或验证码（邮箱账号），再点登录":
        "Enter the password (phone account) or the code (e-mail account), then log in.",
    "账号或密码不正确": "Wrong account or password",
    "验证码不正确": "Wrong code",
    "验证码不存在或已过期，请重新发送":
        "The code does not exist or has expired — request a new one.",
    "短信验证码接口被拓竹网页防护拦截，程序发不了；手机号账号请用密码登录，或改用账号绑定的邮箱。":
        "The SMS endpoint is behind Bambu's web firewall, so this app cannot send SMS. "
        "Use password login, or the e-mail bound to your account.",
    "登录失败：{msg}": "Sign-in failed: {msg}",
    "登录成功：{name}（{model}）": "Signed in: {name} ({model})",
    "登录成功，但取不到设备列表：{exc}":
        "Signed in, but the device list could not be fetched: {exc}",
    "这个账号下没有绑定打印机，请先在 Bambu Studio 或 Bambu Handy 里绑定":
        "No printer is bound to this account — bind one in Bambu Studio or Bambu Handy first.",
    "登录超时：20 秒没有响应。请检查这台电脑能不能上外网，或稍后再试。":
        "Sign-in timed out (20 s). Check that this PC can reach the internet, then retry.",
    "这个账号需要用验证码登录，请点“发送验证码”":
        "This account requires a verification code — click \"Send code\".",
    "这个账号开了二次验证，请改用验证码登录方式":
        "This account has 2FA — use verification-code login instead.",
    "该账号需要邮箱或短信验证码。": "This account needs an e-mail or SMS code.",
    "该账号开了二次验证（需要用 Bambu Studio 完成一次，或改用验证码登录）。":
        "This account has 2FA (complete it once in Bambu Studio, or use a code).",
    "当前已登录，可重新登录以切换账号。": "Already signed in — sign in again to switch accounts.",
    "状态：未登录。点“登录 / 更换账号”，填邮箱 → 发送验证码 → 填入邮件里的 6 位数字。":
        "Status: not signed in. Click \"Log in / switch account\", enter your e-mail, "
        "request a code and paste the 6 digits.",
    "状态：已登录 {acc}{tail}": "Status: signed in as {acc}{tail}",
    "已登录拓竹账号": "Signed in to Bambu",
    "将通过拓竹云监控 {name}": "Monitoring {name} through Bambu Cloud",
    "已登录，正在通过云端连接 {name} ...": "Signed in — connecting to {name} via cloud…",
    "正在通过拓竹云连接 {name} ...": "Connecting to {name} through Bambu Cloud…",
    "云端凭证缺少 uid，请重新登录": "Cloud credentials are missing the uid — sign in again.",
    "云端连接失败（{serial}），可能是登录已过期，请重新登录":
        "Cloud connection failed ({serial}) — the session may have expired, sign in again.",
    "已连接 {target}": "Connected to {target}",
    "（拓竹云）": " (Bambu Cloud)",
    # ---------- 事件（生成规则见 state.py）----------
    "打印完成 🎉": "Print finished 🎉",
    "「{name}」打印完成": "\"{name}\" is finished",
    "。可以取件了": ". Your part is ready.",
    "打印失败": "Print failed",
    "「{name}」打印失败，请在打印机屏幕或 Bambu Studio 查看原因":
        "\"{name}\" failed — check the printer screen or Bambu Studio.",
    "打印已暂停": "Print paused",
    "打印已暂停：{reason}": "Print paused: {reason}",
    "请在打印机或 Bambu Studio 中确认后继续":
        "Confirm on the printer or in Bambu Studio, then resume.",
    "（已打印 {pct}%）": " ({pct}% done)",
    "打印已恢复": "Print resumed",
    "「{name}」继续打印中": "\"{name}\" is printing again",
    "「{name}」开始打印": "\"{name}\" started",
    "打印已取消": "Print cancelled",
    "「{name}」已被取消": "\"{name}\" was cancelled",
    "打印异常停止": "Print stopped abnormally",
    "打印机上报错误码 0x{code:X}（{code}），请在打印机屏幕上确认原因":
        "The printer reported error 0x{code:X} ({code}) — check the printer screen.",
    "打印机故障": "Machine error",
    "打印机告警": "Machine warning",
    "打印机提示": "Machine notice",
    "打印机故障：{module}": "Machine error: {module}",
    "打印机告警：{module}": "Machine warning: {module}",
    "打印机提示：{module}": "Machine notice: {module}",
    "HMS {code}{more}。{advice}": "HMS {code}{more}. {advice}",
    " 等 {n} 项": " and {n} more",
    "正在换料": "Changing filament",
    "AMS 正在自动换料": "AMS is changing filament automatically",
    "：{step}": ": {step}",
    "开始打印": "Print started",
    "Bambu Studio 已关闭": "Bambu Studio closed",
    "Bambu Studio 已退出": "Bambu Studio closed",
    "监控继续在后台盯着打印机": "Still monitoring the printer in the background",
    "检测到 Bambu Studio 已启动": "Bambu Studio started",
    "监控已自动打开并准备连接": "Opened automatically and ready to connect",
    "检测到 Bambu Studio 正在运行": "Bambu Studio is already running",
    "监控已就绪": "Monitor is ready",
    "识别到机型：{model}": "Detected model: {model}",
    # ---------- 暂停原因 ----------
    "耗材用完了": "Out of filament",
    "需要换料": "Filament change required",
    "正在退料": "Unloading filament",
    "正在进料": "Loading filament",
    "前门/盖板检测触发": "Door / cover detected open",
    "喷嘴温度异常": "Nozzle temperature fault",
    "热床温度异常": "Heatbed temperature fault",
    "运动丢步": "Lost steps",
    "AMS 连接丢失": "AMS connection lost",
    "热端散热风扇异常": "Hotend fan fault",
    "腔体温度控制异常": "Chamber temperature control fault",
    "G-code 主动暂停": "Paused by G-code",
    "喷嘴被耗材包裹": "Nozzle covered in filament",
    "切刀异常": "Cutter fault",
    "首层检测异常": "First-layer problem",
    "喷嘴堵塞": "Nozzle clog",
    "你手动暂停了打印": "You paused the print",
    "G-code 触发暂停": "Paused by G-code",
    "装上新的料卷（或让 AMS 换到有料的槽位），然后点继续":
        "Load a new spool (or let AMS switch to a loaded slot), then resume.",
    "按屏幕提示装好新耗材，然后点继续":
        "Load the new filament as prompted on the screen, then resume.",
    "等退料结束后按提示装料": "Wait for unloading to finish, then load as prompted.",
    "确认料管通畅，等待进料完成": "Make sure the PTFE tube is clear and wait for loading.",
    "检查前门与上盖是否关闭到位": "Check that the door and top cover are fully closed.",
    "检查喷嘴加热器与热敏电阻，重试或联系售后":
        "Check the nozzle heater and thermistor, retry or contact support.",
    "检查热床排线与温度传感器": "Check the heatbed cable and temperature sensor.",
    "清理导轨异物后继续；反复出现需检查皮带张紧":
        "Clear debris from the rails, then resume; if it repeats, check belt tension.",
    "检查 AMS 与打印机的连接线、重新插拔": "Re-seat the AMS-to-printer cable.",
    "检查风扇是否被异物卡住": "Check whether the fan is jammed.",
    "检查腔体加热/风扇": "Check the chamber heater and fan.",
    "确认打印件状态后点继续": "Check the part, then resume.",
    "清理喷嘴外的溢料后继续": "Clean the blob off the nozzle, then resume.",
    "检查切刀机构是否有料屑卡住": "Check the cutter mechanism for stuck debris.",
    "检查打印板是否干净、贴平": "Check that the build plate is clean and seated.",
    "清理/更换喷嘴后继续": "Clean or replace the nozzle, then resume.",
    "确认后点继续": "Confirm, then resume.",
    "需要时点继续": "Resume whenever you are ready.",
    "请在打印机屏幕上查看提示": "Check the prompt on the printer screen.",
    # ---------- HMS 模块 ----------
    "主板": "Mainboard",
    "视觉模块": "Vision module",
    "工具头": "Toolhead",
    "运动控制": "Motion control",
    "未知模块": "Unknown module",
    "多为整机通信/供电类提示，可重启打印机后观察":
        "Usually a system communication/power notice — try restarting the printer.",
    "检查摄像头/激光雷达处是否有遮挡或脏污":
        "Check the camera / LiDAR for obstruction or dirt.",
    "检查耗材是否卡住、料管是否插紧、AMS 是否识别到料卷":
        "Check for a filament jam, a loose PTFE tube, and whether AMS sees the spool.",
    "检查喷嘴、热端、切刀、风扇等部件":
        "Check the nozzle, hotend, cutter and fans.",
    "检查导轨、皮带与是否有异物阻挡": "Check the rails, belts and for obstructions.",
    "未知告警": "Unknown alert",
    # ---------- AMS ----------
    "换料中": "Changing filament",
    "识别 RFID": "Reading RFID",
    "已装料": "Loaded",
    "校准中": "Calibrating",
    "冷拔": "Cold pull",
    "自检": "Self-check",
    "调试": "Debug",
    "加热喷嘴": "Heating nozzle",
    "切断耗材": "Cutting filament",
    "回抽旧料": "Retracting old filament",
    "送入新料": "Feeding new filament",
    "冲刷旧料": "Purging old filament",
    "检测位置": "Checking position",
    "空槽": "Empty",
    "余量未知": "Remaining unknown",
    "剩余 {n}%": "{n}% left",
    "槽位 {n} · {material}": "Slot {n} · {material}",
    "没有 AMS（单色打印，或没装 AMS）": "No AMS (single-colour, or AMS not installed)",
    "湿度 {humidity}  ·  温度 {temp}°C": "Humidity {humidity}  ·  {temp}°C",
    # ---------- 阶段（stg_cur）----------
    "自动调平": "Auto bed levelling",
    "热床预热": "Heatbed preheating",
    "振动补偿": "Vibration compensation",
    "M400 暂停": "M400 pause",
    "断料暂停": "Paused - filament runout",
    "加热喷嘴": "Heating nozzle",
    "挤出校准": "Extrusion calibration",
    "扫描热床": "Scanning the bed",
    "检查首层": "Inspecting first layer",
    "识别打印板": "Identifying build plate",
    "激光雷达校准": "LiDAR calibration",
    "回零": "Homing",
    "清理喷嘴": "Cleaning nozzle",
    "检查挤出机温度": "Checking extruder temperature",
    "用户暂停": "Paused by user",
    "前门/盖板检测": "Door / cover check",
    "挤出流量校准": "Flow calibration",
    "退料中": "Unloading filament",
    "丢步暂停": "Paused - lost steps",
    "进料中": "Loading filament",
    "电机噪声校准": "Motor noise calibration",
    "热端风扇异常": "Hotend fan error",
    "腔温控制异常": "Chamber temp control error",
    "腔体降温": "Cooling the chamber",
    "G-code 暂停": "Paused by G-code",
    "电机演示": "Motor demo",
    "喷嘴裹料": "Nozzle blob",
    "切刀异常": "Cutter error",
    "首层异常": "First-layer error",
    "喷嘴堵塞": "Nozzle clog",
    "绝对精度检查": "Absolute accuracy check",
    "绝对精度校准": "Absolute accuracy calibration",
    "喷嘴偏置校准": "Nozzle offset calibration",
    "高温热床调平": "High-temp bed levelling",
    "快拆检测": "Quick-release check",
    "门盖检测": "Door / cover check",
    "激光校准": "Laser calibration",
    "平台检查": "Platform check",
    "相机位置检查": "Camera position check",
    "相机校准": "Camera calibration",
    "热床调平 1/2": "Bed levelling 1/2",
    "热床调平 2/2": "Bed levelling 2/2",
    "腔体加热": "Heating the chamber",
    "热床冷却": "Cooling the heatbed",
    "打印校准线": "Printing calibration lines",
    "材料检查": "Material check",
    "相机校准": "Camera calibration",
    "等待热床温度": "Waiting for heatbed temperature",
    "材料位置检查": "Material position check",
    "切刀偏置校准": "Cutter offset calibration",
    "表面测量": "Surface measurement",
    "热预处理": "Thermal preconditioning",
    "刀架回零": "Homing blade holder",
    "相机偏置校准": "Camera offset calibration",
    "刀架位置校准": "Blade holder calibration",
    "热端交换测试": "Hotend swap test",
    "等待腔温平衡": "Waiting for chamber to equalise",
    "准备热端": "Preparing hotend",
    "裹料检测校准": "Blob detection calibration",
    "腔体净化": "Purifying chamber air",
    "旋转附件测量": "Measuring rotary attachment",
    "移动到废料槽": "Moving to purge chute",
    "喷嘴降温": "Cooling nozzle",
    "移动到热床中心": "Moving to bed centre",
    "圆弧拟合": "Arc fitting",
    "热端类型检测": "Hotend type detection",
    "打印板对齐检测": "Build plate alignment check",
    "热床异物检测": "Heatbed foreign-object check",
    "热床背面异物检测": "Heatbed underside check",
    "打印前预挤出": "Pre-extrusion",
    "准备 AMS": "Preparing AMS",
    "阶段 {n}": "Stage {n}",
    # ---------- 托盘 ----------
    "打开面板": "Open panel",
    "显示主窗口": "Show window",
    "最小化到托盘": "Minimise to tray",
    "退出程序": "Quit",
    "已缩到任务栏，仍在后台监控。要彻底退出请点右下角「退出程序」":
        "Minimised to the tray — still monitoring. Use \"Quit\" in the tray menu to exit.",
    "已缩到托盘，仍在后台监控（右键托盘图标可打开或退出）":
        "Hidden to the tray — still monitoring (right-click the tray icon).",
    "窗口已最小化，进程继续后台监控": "Window hidden, monitor keeps running",
    # ---------- 弹窗 ----------
    "{n} 秒后自动关闭 · 点击打开面板": "Closes in {n}s · click to open the panel",
    # ---------- 停止确认 ----------
    "停止打印": "Stop print",
    "确定要停止当前打印吗？这个操作不可撤销。":
        "Stop the current print? This cannot be undone.",
    # ---------- 单实例 ----------
    "监控程序已经在运行了。\n\n": "BambuMonitor is already running.\n\n",
    "如果没看到窗口，去任务栏点一下「拓竹打印监控」——":
        "If you can't see the window, click the BambuMonitor tray icon —",
    "点叉号只是把它缩到任务栏，进程仍在后台盯着打印机。\n":
        "closing the window only hides it; the process keeps monitoring.\n",
    "想彻底退出：打开窗口后点右下角「退出程序」。":
        "To really quit: open the panel and use the tray menu → Quit.",
    # ---------- 其它 ----------
    "已在浏览器打开英文说明（README.en.md）":
        "Opened the English README in your browser",
    "打不开浏览器，请手动访问 README.en.md":
        "Could not open a browser — please open README.en.md manually",
    "测试通知：打印完成 🎉": "Test alert: print finished 🎉",
    "「测试模型.3mf」打印完成，可以取件了。看到这条说明通知正常。":
        "\"Test model.3mf\" is finished. If you can see this, notifications work.",
    "已发送测试通知，请查看屏幕右下角。": "Test notification sent — check the bottom right.",
    "运行出错": "Runtime error",
    "警告": "Warning",
    # ---------- 运行时模板 ----------
    "已用 {h}:{m:02d}:{s:02d}": "Elapsed {h}:{m:02d}:{s:02d}",
    "约 {m} 分钟": "~{m} min",
    "约 {h} 小时 {mm} 分": "~{h}h {mm}m",
    "约 {h} 小时": "~{h}h",
    "{m} 分钟": "{m} min",
    "剩余 {n}%": "{n}% left",
    "槽位 {n} · {material}": "Slot {n} · {material}",
    "{name}（拓竹云）": "{name} (Bambu Cloud)",
    "拓竹云": "Bambu Cloud",
    "打印机": "Printer",
    "跨网段：打印机 {host} 不在本机网络（本机 {nets}），局域网直连不可达":
        "Cross-network: printer {host} is not on this PC's network ({nets}); direct LAN is impossible.",
    "已经 {secs} 秒连不上 {host}，": "Cannot reach {host} for {secs}s, ",
    "。原因：打印机 {host} 与本机（{nets}）不在同一网络，本程序走局域网直连，跨网络连不上。把打印机连到同一个 WiFi 即可。":
        ". Reason: printer {host} and this PC ({nets}) are on different networks; this app "
        "connects directly over the LAN. Put the printer on the same Wi-Fi.",
    "{module}提示": "{module} notice",
    "暂停原因变化：{reason}": "Pause reason changed: {reason}",
    "，剩余时间 {remain}": ", {remain} left",
    "打印机提示：{module}": "Machine notice: {module}",
    "打印机告警：{module}": "Machine warning: {module}",
    "AMS 正在自动换料": "AMS is changing filament automatically",
    "扫描失败：{msg}": "Scan failed: {msg}",
    "{host}   序列号 {serial}": "{host}   serial {serial}",
    "   （已有访问码）": "   (code on file)",
    "｜设备 {dev}": " | device {dev}",
    "已切换界面语言，需要重启程序生效。现在重启吗？":
        "Interface language changed. Restart now to apply it?",
    "语言已保存，下次启动生效": "Language saved — applies on next start",
    "已缩到托盘，仍在后台监控（右键托盘图标可打开或退出）":
        "Hidden to the tray — still monitoring (right-click the tray icon).",
    "密度": "Density",
}


# --------------------------------------------------------------------------
# tkinter 自动翻译：给控件补丁，创建 / configure 时翻译 text 和 title
# --------------------------------------------------------------------------
_PATCHED = False


def install_tk_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return
    try:
        import tkinter as tk
    except Exception:  # pragma: no cover
        return

    classes = [tk.Label, tk.Button, tk.Checkbutton, tk.Radiobutton, tk.Menubutton]
    for cls in classes:
        orig_init = cls.__init__
        orig_conf = cls.configure

        def make_init(orig):
            def __init__(self, *args, **kwargs):
                if "text" in kwargs:
                    kwargs["text"] = t(kwargs["text"])
                orig(self, *args, **kwargs)

            return __init__

        def make_conf(orig):
            def configure(self, cnf=None, **kwargs):
                if "text" in kwargs:
                    kwargs["text"] = t(kwargs["text"])
                return orig(self, cnf, **kwargs)

            return configure

        cls.__init__ = make_init(orig_init)
        cls.configure = make_conf(orig_conf)
        cls.config = cls.configure

    # 窗口标题（Tk / Toplevel 的 .title()）
    for cls in (tk.Tk, tk.Toplevel):
        orig_title = cls.title

        def make_title(orig):
            def title(self, string=None):
                if string is None:
                    return orig(self)
                return orig(self, t(string))

            return title

        cls.title = make_title(orig_title)

    _PATCHED = True
    LOG.debug("tkinter 翻译补丁已安装")

# --------------------------------------------------------------------------
# 补充条目（后加，避免动上面的主表）
# --------------------------------------------------------------------------
EN.update({
    "（切换后需重启程序生效）": " (restart required)",
    "密度": "Density",
    "打印机故障：{module}": "Machine error: {module}",
    "提示：勾了「开机自动启动 + 启动时最小化」，开机后本程序在后台待命，你打开 Bambu Studio 它就会自己出来。":
        'Tip: with "Start with Windows" + "Start minimised" the app waits in the '
        "background and pops up when you open Bambu Studio.",
})
