"""MQTT 客户端：连接打印机本地 8883 端口，订阅状态、下发控制指令。"""
from __future__ import annotations

import json
import logging
import ssl
import threading
import time

import paho.mqtt.client as mqtt

LOG = logging.getLogger(__name__)

MQTT_PORT = 8883
MQTT_USER = "bblp"  # 固定的本地账号，密码是打印机「访问码」


def make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE      # 打印机用自签证书
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except ssl.SSLError:
        pass
    return ctx


class PrinterClient:
    """一个实例对应一台打印机。回调都在后台线程里执行。"""

    def __init__(
        self,
        host: str,
        serial: str,
        access_code: str,
        on_report,
        on_connected=None,
        on_disconnected=None,
        on_status=None,
        pushall_interval: int = 90,
        on_info=None,
        username: str | None = None,
        password: str | None = None,
        port: int = MQTT_PORT,
        cloud: bool = False,
    ):
        self.host = host
        self.serial = serial
        self.access_code = access_code
        self.on_report = on_report
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected
        self.on_status = on_status
        self.on_info = on_info
        self.pushall_interval = max(20, int(pushall_interval or 90))
        # 云模式：不是 bblp/访问码，而是 u_<uid>/accessToken
        self.username = username or MQTT_USER
        self.password = password if password is not None else access_code
        self.port = int(port or MQTT_PORT)
        self.cloud = bool(cloud)

        self._seq = 0
        self._seq_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._watchdog: threading.Thread | None = None
        self._connected = threading.Event()
        self._last_rx = 0.0
        self._client: mqtt.Client | None = None

    # ---------- 生命周期 ----------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="bambu-mqtt", daemon=True)
        self._thread.start()
        self._watchdog = threading.Thread(target=self._keepalive, name="bambu-keepalive", daemon=True)
        self._watchdog.start()

    def stop(self) -> None:
        self._stop.set()
        self._connected.clear()
        c = self._client
        if c is not None:
            try:
                c.disconnect()
            except Exception:
                pass
            try:
                c.loop_stop()
            except Exception:
                pass
        self._client = None

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    # ---------- 内部 ----------
    def _status(self, text: str) -> None:
        LOG.info(text)
        if self.on_status:
            try:
                self.on_status(text)
            except Exception:
                LOG.debug("on_status 回调异常", exc_info=True)

    def _run(self) -> None:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"bambumon-{self.serial[-6:] if self.serial else 'x'}",
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )
        client.username_pw_set(self.username, self.password)
        if self.cloud:
            # 云端证书是正规 CA 签发的，正常校验
            client.tls_set_context(ssl.create_default_context())
        else:
            client.tls_set_context(make_ssl_context())
        client.reconnect_delay_set(min_delay=2, max_delay=30)
        client.on_connect = self._on_connect
        client.on_connect_fail = self._on_connect_fail
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        self._client = client

        self._status(f"正在连接 {self.host}:{self.port} ...")
        try:
            client.connect_async(self.host, self.port, keepalive=60)
            client.loop_forever(retry_first_connection=True)
        except Exception as e:
            LOG.warning("MQTT 线程退出: %s", e)
        finally:
            self._connected.clear()
            try:
                client.loop_stop()
            except Exception:
                pass

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "value", reason_code) != 0:
            self._status(f"连接失败：{reason_code}（多半是访问码不对）")
            return
        self._connected.set()
        topic = f"device/{self.serial}/report"
        client.subscribe(topic, qos=0)
        self._status(f"已连接 {self.host}")
        self.request_pushall()
        # 顺便问一下机型（info.get_version 的响应里有 project_name）
        self.get_version()
        if self.on_connected:
            try:
                self.on_connected()
            except Exception:
                LOG.debug("on_connected 回调异常", exc_info=True)

    def _on_connect_fail(self, client, userdata):
        # 连不上时别每 2 秒刷屏，60 秒报一次
        now = time.time()
        if now - getattr(self, "_last_fail_report", 0) < 60:
            return
        self._last_fail_report = now
        self._status(f"连接失败 {self.host}:{self.port}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self._connected.clear()
        self._status("与打印机的连接已断开")
        if self.on_disconnected:
            try:
                self.on_disconnected()
            except Exception:
                LOG.debug("on_disconnected 回调异常", exc_info=True)

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage):
        self._last_rx = time.time()
        try:
            data = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except Exception:
            return
        if not isinstance(data, dict):
            return
        if isinstance(data.get("print"), dict):
            try:
                self.on_report(data)
            except Exception:
                LOG.debug("处理上报异常", exc_info=True)
            return
        info = data.get("info")
        if isinstance(info, dict) and self.on_info:
            try:
                self.on_info(info)
            except Exception:
                LOG.debug("处理 info 异常", exc_info=True)

    def _keepalive(self) -> None:
        """P1 系列只发增量，定期拉一次全量，防止状态漂移。"""
        while not self._stop.wait(1.0):
            if not self._connected.is_set():
                continue
            idle = time.time() - self._last_rx
            if idle > self.pushall_interval:
                self.request_pushall()

    def _next_seq(self) -> str:
        with self._seq_lock:
            self._seq = (self._seq + 1) % 10000
            return str(self._seq)

    def _publish(self, payload: dict, qos: int = 1) -> bool:
        c = self._client
        if c is None or not self._connected.is_set():
            return False
        try:
            c.publish(f"device/{self.serial}/request", json.dumps(payload), qos=qos)
            return True
        except Exception as e:
            LOG.warning("下发指令失败: %s", e)
            return False

    # ---------- 指令 ----------
    def request_pushall(self) -> bool:
        return self._publish(
            {"pushing": {"sequence_id": self._next_seq(), "command": "pushall", "version": 1, "push_target": 1}},
            qos=0,
        )

    def get_version(self) -> bool:
        return self._publish({"info": {"sequence_id": self._next_seq(), "command": "get_version"}})

    def pause(self) -> bool:
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": "pause", "param": ""}}, qos=1)

    def resume(self) -> bool:
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": "resume", "param": ""}}, qos=1)

    def stop_print(self) -> bool:
        return self._publish({"print": {"sequence_id": self._next_seq(), "command": "stop", "param": ""}}, qos=1)

    def set_chamber_light(self, on: bool) -> bool:
        return self._publish(
            {
                "system": {
                    "sequence_id": self._next_seq(),
                    "command": "ledctrl",
                    "led_node": "chamber_light",
                    "led_mode": "on" if on else "off",
                    "led_on_time": 500,
                    "led_off_time": 500,
                    "loop_times": 0,
                    "interval_time": 0,
                }
            }
        )


def probe(host: str, serial: str, access_code: str, timeout: float = 8.0) -> dict:
    """测试连接：返回第一条状态报文，失败抛异常。"""
    got: dict = {}
    done = threading.Event()
    err: list[str] = []

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "value", reason_code) != 0:
            err.append(f"认证失败：{reason_code}")
            done.set()
            return
        client.subscribe(f"device/{serial}/report", qos=0)
        client.publish(
            f"device/{serial}/request",
            json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}),
            qos=0,
        )

    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8", errors="replace"))
        except Exception:
            return
        if isinstance(data.get("print"), dict):
            got.update(data)
            done.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bambumon-probe", protocol=mqtt.MQTTv311)
    client.username_pw_set(MQTT_USER, access_code)
    client.tls_set_context(make_ssl_context())
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(host, MQTT_PORT, 30)
    except Exception as e:
        raise RuntimeError(f"无法连接 {host}:{MQTT_PORT}（{e}）") from e
    client.loop_start()
    try:
        done.wait(timeout)
    finally:
        client.loop_stop()
        try:
            client.disconnect()
        except Exception:
            pass
    if err:
        raise RuntimeError(err[0])
    if not got:
        raise RuntimeError("已连上但没有收到状态数据，请确认序列号是否正确")
    return got
