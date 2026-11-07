"""打印机发现：扫 8883 端口 + 读证书取序列号 + 导入 Bambu Studio 里的访问码。

拓竹打印机在本地网络开放 MQTT over TLS（8883，用户名 bblp，密码=访问码），
其自签证书的 CN 就是机器序列号，因此可以「先找机器、再配密码」。
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import ssl
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LOG = logging.getLogger(__name__)

MQTT_PORT = 8883


# --------------------------------------------------------------------------
# 本机网段
# --------------------------------------------------------------------------
def _adapters_via_ctypes() -> list[tuple[str, int]]:
    """用 GetAdaptersAddresses 拿到本机所有 IPv4 + 掩码位数（含多网卡）。

    失败时返回空列表，由调用方回退到 /24 猜测。
    """
    import ctypes
    from ctypes import wintypes

    class SOCKET_ADDRESS(ctypes.Structure):
        _fields_ = [("lpSockaddr", ctypes.c_void_p), ("iSockaddrLength", ctypes.c_int)]

    class UNICAST(ctypes.Structure):
        pass

    UNICAST._fields_ = [
        ("Length", wintypes.ULONG),
        ("Flags", wintypes.ULONG),
        ("Next", ctypes.POINTER(UNICAST)),
        ("Address", SOCKET_ADDRESS),
        ("PrefixOrigin", ctypes.c_int),
        ("SuffixOrigin", ctypes.c_int),
        ("DadState", ctypes.c_int),
        ("ValidLifetime", wintypes.ULONG),
        ("PreferredLifetime", wintypes.ULONG),
        ("LeaseLifetime", wintypes.ULONG),
        ("OnLinkPrefixLength", ctypes.c_ubyte),
    ]

    class ADAPTER(ctypes.Structure):
        pass

    ADAPTER._fields_ = [
        ("Length", wintypes.ULONG),
        ("IfIndex", wintypes.ULONG),
        ("Next", ctypes.POINTER(ADAPTER)),
        ("AdapterName", ctypes.c_char_p),
        ("FirstUnicastAddress", ctypes.POINTER(UNICAST)),
        ("FirstAnycastAddress", ctypes.c_void_p),
        ("FirstMulticastAddress", ctypes.c_void_p),
        ("FirstDnsServerAddress", ctypes.c_void_p),
        ("DnsSuffix", ctypes.c_wchar_p),
        ("Description", ctypes.c_wchar_p),
        ("FriendlyName", ctypes.c_wchar_p),
        ("PhysicalAddress", ctypes.c_ubyte * 8),
        ("PhysicalAddressLength", wintypes.ULONG),
        ("Flags", wintypes.ULONG),
        ("Mtu", wintypes.ULONG),
        ("IfType", wintypes.ULONG),
        ("OperStatus", ctypes.c_int),
    ]

    out: list[tuple[str, int]] = []
    try:
        iphlpapi = ctypes.WinDLL("iphlpapi.dll")
    except OSError:
        return out

    flags = 0x0002 | 0x0004 | 0x0008  # SKIP_ANYCAST | SKIP_MULTICAST | SKIP_DNS_SERVER
    size = ctypes.c_ulong(16 * 1024)
    for _ in range(3):
        buf = ctypes.create_string_buffer(size.value)
        rc = iphlpapi.GetAdaptersAddresses(
            0, flags, None, buf, ctypes.byref(size)  # AF_UNSPEC
        )
        if rc == 111:  # ERROR_BUFFER_OVERFLOW
            continue
        if rc != 0:
            return out
        node = ctypes.cast(buf, ctypes.POINTER(ADAPTER))
        while node:
            a = node.contents
            if a.OperStatus == 1:  # IfOperStatusUp
                u = a.FirstUnicastAddress
                while u:
                    sa = u.contents.Address
                    if sa.lpSockaddr and sa.iSockaddrLength >= 8:
                        raw = ctypes.string_at(sa.lpSockaddr, 8)
                        if raw[0] == 2:  # AF_INET
                            ip = socket.inet_ntoa(raw[4:8])
                            prefix = int(u.contents.OnLinkPrefixLength) or 24
                            if not ip.startswith(("127.", "169.254.", "0.")):
                                out.append((ip, prefix))
                    u = u.contents.Next
            node = a.Next
        break
    return out


def local_ipv4_addresses() -> list[str]:
    ips = [ip for ip, _ in _adapters_via_ctypes()]
    # 兜底：默认路由地址
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 53))
            ips.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.append(ip)
    except OSError:
        pass
    out: list[str] = []
    for ip in ips:
        if ip.startswith(("127.", "169.254.", "0.")) or ip in out:
            continue
        out.append(ip)
    return out


def candidate_subnets(prefix: int = 24) -> list[ipaddress.IPv4Network]:
    nets: list[ipaddress.IPv4Network] = []
    pairs = _adapters_via_ctypes()
    if not pairs:
        pairs = [(ip, prefix) for ip in local_ipv4_addresses()]
    for ip, pfx in pairs:
        try:
            net = ipaddress.ip_network(f"{ip}/{pfx}", strict=False)
        except ValueError:
            continue
        # 太大的网段（/16 及以下）只取本机所在 /24，避免扫 6 万个地址
        if net.num_addresses > 1024:
            net = ipaddress.ip_network(f"{ip}/24", strict=False)
        if net not in nets:
            nets.append(net)
    return nets


# --------------------------------------------------------------------------
# DER 解析（只为了拿证书 CN，避免引入 cryptography 依赖）
# --------------------------------------------------------------------------
def _tlv(data: bytes, i: int = 0):
    tag = data[i]
    i += 1
    length = data[i]
    i += 1
    if length & 0x80:
        n = length & 0x7F
        if n == 0 or n > 4:
            raise ValueError("bad der length")
        length = int.from_bytes(data[i : i + n], "big")
        i += n
    return tag, data[i : i + length], i + length


def _children(value: bytes) -> list[tuple[int, bytes]]:
    out = []
    i = 0
    while i < len(value):
        tag, val, i = _tlv(value, i)
        out.append((tag, val))
    return out


def cert_common_name(der: bytes) -> str | None:
    try:
        _, cert, _ = _tlv(der, 0)
        fields = _children(cert)
        tbs = fields[0][1]
        parts = _children(tbs)
        idx = 0
        if parts and parts[0][0] == 0xA0:  # [0] version
            idx = 1
        subject_idx = idx + 4  # serial, signature, issuer, validity, subject
        if subject_idx >= len(parts):
            return None
        subject = parts[subject_idx][1]
        # subject = SEQUENCE OF SET { SEQUENCE { OID, value } }
        for _tag, rdn_set in _children(subject):
            for _t2, attr in _children(rdn_set):
                items = _children(attr)
                if len(items) < 2:
                    continue
                oid, raw = items[0][1], items[1][1]
                if oid == b"\x55\x04\x03":  # 2.5.4.3 commonName
                    try:
                        return raw.decode("utf-8")
                    except UnicodeDecodeError:
                        return raw.decode("latin-1")
    except Exception as e:  # 解析失败不影响主流程
        LOG.debug("解析证书失败: %s", e)
    return None


def read_serial(host: str, timeout: float = 2.5) -> str | None:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, MQTT_PORT), timeout=timeout) as sock:
            with ctx.wrap_socket(sock) as ss:
                der = ss.getpeercert(binary_form=True)
        return cert_common_name(der) if der else None
    except Exception:
        return None


def port_open(host: str, port: int = MQTT_PORT, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def scan(networks: list[ipaddress.IPv4Network], timeout: float = 0.6, workers: int = 200) -> list[str]:
    hosts: list[str] = []
    for net in networks:
        hosts.extend(str(h) for h in net.hosts())
    found: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for host, ok in zip(hosts, pool.map(lambda h: port_open(h, MQTT_PORT, timeout), hosts)):
            if ok:
                found.append(host)
    return found


def discover(timeout: float = 0.6) -> list[dict]:
    """返回 [{"host":..., "serial":...}]"""
    result: list[dict] = []
    for host in scan(candidate_subnets(), timeout=timeout):
        serial = read_serial(host)
        result.append({"host": host, "serial": serial or ""})
    return result


# --------------------------------------------------------------------------
# Bambu Studio 里已有的访问码
# --------------------------------------------------------------------------
def bambu_studio_conf_path() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    p = Path(appdata) / "BambuStudio" / "BambuStudio.conf"
    return p if p.exists() else None


def import_access_codes() -> dict[str, str]:
    """从 Bambu Studio 配置里读出 序列号 -> 访问码（只读，不改动原文件）。"""
    path = bambu_studio_conf_path()
    if not path:
        return {}
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        # 配置文件末尾会跟一行 "# MD5 checksum ..."，所以只解析第一个 JSON 对象
        data, _end = json.JSONDecoder().raw_decode(raw.lstrip())
    except Exception as e:
        LOG.info("读取 BambuStudio.conf 失败: %s", e)
        return {}
    codes = data.get("access_code")
    if not isinstance(codes, dict):
        return {}
    return {str(k): str(v) for k, v in codes.items() if k and v}


# --------------------------------------------------------------------------
# 网络诊断
# --------------------------------------------------------------------------
def same_subnet(host: str) -> bool | None:
    """打印机 IP 是否和本机在同一个网段。

    返回 True=同网段，False=跨网段（局域网直连肯定不通），None=判断不了。
    """
    try:
        target = ipaddress.ip_address(host)
    except ValueError:
        # 主机名就不好判断了
        return None
    nets = candidate_subnets()
    if not nets:
        return None
    for net in nets:
        if target in net:
            return True
    return False


def local_networks_text() -> str:
    nets = candidate_subnets()
    return "、".join(str(n) for n in nets) if nets else "未知"
