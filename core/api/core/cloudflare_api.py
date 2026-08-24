"""
EasyServer Cloudflare API Client
使用标准库 urllib 封装 Cloudflare API（无需额外依赖）
支持：Token 验证、隧道创建/配置、路由(ingress)管理、DNS 记录管理
"""

import json
import urllib.request
import urllib.error

API_BASE = "https://api.cloudflare.com/client/v4"


class CloudflareAPIError(Exception):
    """Cloudflare API 调用失败"""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class CloudflareClient:
    def __init__(self, api_token: str):
        self.api_token = api_token
        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, body: dict = None, timeout: int = 20) -> dict:
        url = f"{API_BASE}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8") if e.fp else ""
            status = e.code
            try:
                err = json.loads(raw)
                errors = [er.get("message", "") for er in err.get("errors", [])]
                raise CloudflareAPIError("; ".join(errors) or f"HTTP {status}", status)
            except (json.JSONDecodeError, AttributeError):
                raise CloudflareAPIError(f"HTTP {status}: {raw[:200]}", status)
        except urllib.error.URLError as e:
            raise CloudflareAPIError(f"无法连接 Cloudflare API: {e.reason}")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise CloudflareAPIError("Cloudflare API 返回了无效响应")
        if not data.get("success", False):
            errors = [er.get("message", "") for er in data.get("errors", [])]
            raise CloudflareAPIError("; ".join(errors) or "未知错误")
        return data.get("result")

    # ===== Token / 账户 / 域名 =====

    def verify_token(self) -> dict:
        """验证 API Token 是否有效"""
        return self._request("GET", "/user/tokens/verify")

    def list_accounts(self) -> list:
        """获取 API Token 可访问的账户列表"""
        result = self._request("GET", "/accounts?per_page=50")
        return result if isinstance(result, list) else []

    def get_zone(self, domain: str) -> dict:
        """按域名查找 Zone（域名必须托管在 Cloudflare 且 Token 有 Zone 权限）"""
        import urllib.parse
        result = self._request("GET", f"/zones?name={urllib.parse.quote(domain)}")
        if isinstance(result, list) and result:
            return result[0]
        return None

    # ===== 隧道管理 =====

    def list_tunnels(self, account_id: str) -> list:
        result = self._request("GET", f"/accounts/{account_id}/cfd_tunnel?is_deleted=false")
        return result if isinstance(result, list) else []

    def create_tunnel(self, account_id: str, name: str) -> dict:
        """创建隧道，返回结果含 id / name / token（运行时凭证）"""
        return self._request(
            "POST",
            f"/accounts/{account_id}/cfd_tunnel",
            {"name": name, "config_src": "cloudflare"},
        )

    def get_tunnel_token(self, account_id: str, tunnel_id: str) -> str:
        """获取隧道的运行时 Token"""
        result = self._request("GET", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token")
        # Cloudflare API 直接返回 token 字符串，而非包含 token 字段的对象
        return result if isinstance(result, str) else (result or {}).get("token", "")

    def get_tunnel_connections(self, account_id: str, tunnel_id: str) -> list:
        """获取隧道连接列表（非空表示已连接）"""
        result = self._request("GET", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/connections")
        return result if isinstance(result, list) else []

    def get_tunnel_config(self, account_id: str, tunnel_id: str) -> dict:
        """获取隧道 ingress 配置（新隧道可能返回 null，统一兜底为空 dict）"""
        result = self._request("GET", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations")
        return result if isinstance(result, dict) else {}

    def update_tunnel_config(self, account_id: str, tunnel_id: str, ingress: list) -> dict:
        """更新隧道 ingress 路由配置（最后一条必须是 catch-all）"""
        return self._request(
            "PUT",
            f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
            {"config": {"ingress": ingress}},
        )

    def delete_tunnel(self, account_id: str, tunnel_id: str) -> dict:
        """删除隧道（cascade=true 同时删除 DNS 记录）"""
        return self._request("DELETE", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}?cascade=true")

    # ===== DNS 记录管理 =====

    def create_dns_record(self, zone_id: str, name: str, content: str, proxied: bool = True, record_type: str = "CNAME") -> dict:
        """创建 DNS 记录（name 为完整域名，content 为目标值，type 支持 A/AAAA/CNAME）
        域名反代场景：A/AAAA 记录需 proxied=False（DNS only，直连服务器 IP）
        """
        return self._request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            {"type": record_type, "name": name, "content": content, "proxied": proxied, "ttl": 600},
        )

    def list_dns_records(self, zone_id: str, name: str = "") -> list:
        """查询 DNS 记录（可按完整名称过滤）"""
        import urllib.parse
        suffix = f"&name={urllib.parse.quote(name)}" if name else ""
        result = self._request("GET", f"/zones/{zone_id}/dns_records?per_page=100{suffix}")
        return result if isinstance(result, list) else []

    def update_dns_record(self, zone_id: str, record_id: str, name: str, content: str, proxied: bool = False, record_type: str = "A", ttl: int = 600) -> dict:
        """更新 DNS 记录内容"""
        return self._request(
            "PUT",
            f"/zones/{zone_id}/dns_records/{record_id}",
            {"type": record_type, "name": name, "content": content, "proxied": proxied, "ttl": ttl},
        )

    def delete_dns_record(self, zone_id: str, record_id: str) -> dict:
        return self._request("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")
