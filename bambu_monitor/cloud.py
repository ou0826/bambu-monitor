"""拓竹云端账号：登录、取设备列表、云 MQTT 连接参数。

只依赖标准库（urllib），不引入新依赖。

流程（与 Bambu Studio 一致）：
  1. POST /v1/user-service/user/login  {account, password}  -> accessToken
     或 {account, code}（邮箱/短信验证码）
  2. accessToken 是 JWT，里面 "username" 形如 u_<uid>
  3. GET /v1/iot-service/api/user/bind（Bearer token）-> 设备列表
  4. 云 MQTT：cn.mqtt.bambulab.com / us.mqtt.bambulab.com:8883
     用户名 u_<uid>，密码 accessToken
"""
from __future__ import annotations

import base64
import json
import logging
import ssl
import urllib.error
import urllib.request

LOG = logging.getLogger(__name__)

API = "https://api.bambulab.com"          # 国际区
API_CN = "https://api.bambulab.cn"        # 中国区（中国大陆账号必须用这个）
API_SMS = "https://bambulab.cn/api"       # 短信接口，被 WAF 拦，程序无法用
UA = "bambu_network_agent/01.09.05.01"

MQTT_HOST_CN = "cn.mqtt.bambulab.com"
MQTT_HOST_US = "us.mqtt.bambulab.com"
MQTT_PORT = 8883


class CloudError(Exception):
    """登录/接口错误（消息可直接展示给用户）。"""

    def __init__(self, msg: str, code=None):
        super().__init__(msg)
        self.code = code


# 服务器原文 -> 中文提示
_ERR_ZH = {
    "Incorrect account or password.": "账号或密码不正确",
    "Incorrect code": "验证码不正确",
    "Code does not exist or has expired; please request a new verification code.":
        "验证码不存在或已过期，请重新发送",
    "The server cannot or will not process the request due to something that is perceived "
    "to be a client error.": "服务器无法处理这个请求",
}


def _zh(msg: str) -> str:
    msg = str(msg or "").strip()
    if msg in _ERR_ZH:
        return _ERR_ZH[msg]
    for k, v in _ERR_ZH.items():
        if msg.startswith(k[:40]):
            return v
    return msg


class NeedCode(CloudError):
    """该账号需要邮箱或短信验证码。"""


class NeedTfa(CloudError):
    """该账号开了二次验证（需要用 Bambu Studio 完成一次，或改用验证码登录）。"""


def jwt_username(token: str) -> str:
    """从 accessToken（JWT）里取 username，形如 u_1234567890。"""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8", "ignore"))
        name = data.get("username") or ""
        if name.startswith("u_"):
            return name
        uid = data.get("uid")
        return f"u_{uid}" if uid else ""
    except Exception:
        return ""


def jwt_uid(token: str) -> str:
    name = jwt_username(token)
    return name[2:] if name.startswith("u_") else ""


class BambuCloud:
    def __init__(self, token: str = "", region: str = "China"):
        self.region = region or "China"
        self.token = token or ""
        self._base = ""      # 登录成功后记住用哪个区的接口
        self._uid = ""       # 云端 MQTT 用户名是 u_<uid>，需要单独查一次

    # ---------- 内部 ----------
    @property
    def mqtt_host(self) -> str:
        return MQTT_HOST_CN if self.region == "China" else MQTT_HOST_US

    @property
    def bases(self) -> list[str]:
        """先试本区的接口，再试另一个区（账号可能在另一区注册）。"""
        return [API_CN, API] if self.region == "China" else [API, API_CN]

    @property
    def base(self) -> str:
        return self._base or self.bases[0]

    def _request(self, url: str, payload: dict | None = None, auth: bool = False) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
        req.add_header("User-Agent", UA)
        req.add_header("Content-Type", "application/json")
        if auth and self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=25, context=ssl.create_default_context()) as r:
                body = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                data_obj = json.loads(body)
            except Exception:
                raise CloudError(f"服务器返回 {e.code}：{body[:120]}") from None
            msg = data_obj.get("error") or data_obj.get("message") or f"HTTP {e.code}"
            raise CloudError(_zh(msg), code=data_obj.get("code")) from None
        except urllib.error.URLError as e:
            raise CloudError(f"连不上拓竹服务器（{e.reason}），请检查本机能否上网") from None
        except TimeoutError:
            raise CloudError("连接拓竹服务器超时，请检查网络") from None
        try:
            return json.loads(body or "{}")
        except Exception:
            raise CloudError(f"服务器返回了无法识别的内容：{body[:120]}") from None

    # ---------- 登录 ----------
    def _login_once(self, base: str, payload: dict) -> str:
        data = self._request(f"{base}/v1/user-service/user/login", payload)
        token = data.get("accessToken") or ""
        if token:
            self.token = token
            self._base = base
            LOG.info("登录成功（接口 %s）", base)
            return token
        login_type = data.get("loginType")
        if login_type == "verifyCode":
            raise NeedCode("这个账号需要用验证码登录，请点“发送验证码”")
        if login_type == "tfa":
            raise NeedTfa("这个账号开了二次验证，请改用验证码登录方式")
        raise CloudError(f"登录失败：{data}")

    def _login_with_fallback(self, payload: dict) -> str:
        last: CloudError | None = None
        for base in self.bases:
            try:
                return self._login_once(base, payload)
            except CloudError as e:
                last = e
                # code 1 = 这个区里没有这个账号，换另一个区再试
                if getattr(e, "code", None) == 1:
                    LOG.info("区域 %s 里没有该账号，换区重试", base)
                    continue
                raise
        raise last or CloudError("登录失败")

    def login_password(self, account: str, password: str) -> str:
        return self._login_with_fallback(
            {"account": account, "password": password, "apiError": ""}
        )

    def send_code(self, account: str) -> None:
        """发登录验证码。

        · 邮箱 -> /v1/user-service/user/sendemail/code
        · 手机 -> /v1/user-service/user/sendsmscode（必须用 api 域名；网站域名 bambulab.cn/api
          被阿里云 WAF 拦着，纯程序调用会拿到 403 验证页）
        """
        is_email = "@" in account
        last: CloudError | None = None
        for base in self.bases:
            try:
                if is_email:
                    self._request(
                        f"{base}/v1/user-service/user/sendemail/code",
                        {"email": account, "type": "codeLogin"},
                    )
                else:
                    self._request(
                        f"{base}/v1/user-service/user/sendsmscode",
                        {"phone": account, "type": "codeLogin"},
                    )
                self._base = base
                LOG.info("验证码已发送（%s，接口 %s）", "邮箱" if is_email else "短信", base)
                return
            except CloudError as e:
                last = e
                continue
        raise last or CloudError("发送验证码失败")

    def login_code(self, account: str, code: str) -> str:
        return self._login_with_fallback({"account": account, "code": code})

    # ---------- 账号信息 ----------
    def fetch_uid(self) -> str:
        """取账号的数字 uid（云 MQTT 的用户名要用 u_<uid>）。

        accessToken 有两种形态：JWT（能直接解出 username）和不透明串（本例就是这种）。
        后者必须再查一次 preference 接口拿 uid。实测该接口在 api.bambulab.cn 可用。
        """
        if self._uid:
            return self._uid
        try:
            data = self._request(f"{self.base}/v1/design-user-service/my/preference", auth=True)
            uid = data.get("uid")
            self._uid = str(uid) if uid is not None else ""
        except Exception as e:
            LOG.warning("取 uid 失败: %s", e)
            self._uid = ""
        return self._uid

    @property
    def mqtt_username(self) -> str:
        """云 MQTT 登录名：u_<uid>。"""
        name = jwt_username(self.token)
        if name:
            return name
        uid = self._uid or self.fetch_uid()
        return f"u_{uid}" if uid else ""

    @property
    def username(self) -> str:
        return self.mqtt_username

    @property
    def uid(self) -> str:
        return self._uid or jwt_uid(self.token)

    def devices(self) -> list[dict]:
        """账号下已绑定的设备。"""
        if not self.token:
            raise CloudError("还没登录")
        data = self._request(f"{self.base}/v1/iot-service/api/user/bind", auth=True)
        devs = data.get("devices")
        if not isinstance(devs, list):
            raise CloudError(f"取设备列表失败：{data}")
        out = []
        for d in devs:
            if not isinstance(d, dict):
                continue
            out.append(
                {
                    "dev_id": d.get("dev_id") or "",
                    "name": d.get("name") or "",
                    "model_id": d.get("dev_model_name") or "",
                    "model": d.get("dev_product_name") or "",
                    "access_code": d.get("dev_access_code") or "",
                    "online": bool(d.get("online")),
                    "task_status": d.get("print_status") or "",
                }
            )
        return out


def cloud_mqtt_ssl() -> ssl.SSLContext:
    """云端是正规证书，正常校验。"""
    return ssl.create_default_context()
