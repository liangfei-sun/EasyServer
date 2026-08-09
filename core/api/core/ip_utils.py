"""
EasyServer Public IP Utilities
公网 IP 检测工具：探测服务器公网 IPv4 / IPv6 地址
使用多个公开接口兜底，全部失败时返回空
"""

import urllib.request

# IPv4 探测接口（按顺序尝试）
IPV4_PROVIDERS = [
    "https://api.ipify.org",
    "https://ipv4.icanhazip.com",
    "https://4.ipw.cn",
]

# IPv6 探测接口（按顺序尝试）
IPV6_PROVIDERS = [
    "https://api6.ipify.org",
    "https://ipv6.icanhazip.com",
    "https://6.ipw.cn",
]


def _fetch(url: str, timeout: int = 8) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "EasyServer/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8").strip()


def get_public_ipv4() -> str:
    """获取公网 IPv4 地址（失败返回空字符串）"""
    for url in IPV4_PROVIDERS:
        try:
            ip = _fetch(url)
            if ip:
                return ip
        except Exception:
            continue
    return ""


def get_public_ipv6() -> str:
    """获取公网 IPv6 地址（失败返回空字符串，表示服务器无公网 IPv6）"""
    for url in IPV6_PROVIDERS:
        try:
            ip = _fetch(url)
            if ip:
                return ip
        except Exception:
            continue
    return ""


def get_public_ips() -> dict:
    """同时探测 IPv4 与 IPv6，返回检测结果"""
    ipv4 = get_public_ipv4()
    ipv6 = get_public_ipv6()
    return {
        "ipv4": ipv4,
        "ipv6": ipv6,
        # 推荐的记录类型：有 IPv6 则同时创建 AAAA，否则只创建 A
        "record_types": (["AAAA", "A"] if ipv6 else ["A"]) if ipv4 or ipv6 else [],
    }
