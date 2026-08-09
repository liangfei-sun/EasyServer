"""
EasyServer Aliyun DNS API Client
使用标准库 urllib + HMAC-SHA1 签名封装阿里云 DNS API（无需额外依赖）
支持：记录查询、添加、更新、删除（A / AAAA / CNAME 等类型）
文档参考：https://help.aliyun.com/zh/dns/api-dns-2015-01-09-overview
"""

import base64
import hashlib
import hmac
import json
import uuid
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

API_ENDPOINT = "https://alidns.aliyuncs.com/"
API_VERSION = "2015-01-09"


class AliyunDNSAPIError(Exception):
    """阿里云 DNS API 调用失败"""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


def _percent_encode(value: str) -> str:
    """阿里云 RPC 签名要求的特殊 URL 编码"""
    return urllib.parse.quote(str(value), safe="~")


def _sign(secret: str, params: dict) -> str:
    """HMAC-SHA1 签名（阿里云 RPC 规范）"""
    sorted_params = sorted(params.items())
    canonical = "&".join(f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted_params)
    string_to_sign = f"GET&%2F&{_percent_encode(canonical)}"
    key = (secret + "&").encode("utf-8")
    digest = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


class AliyunDNSClient:
    def __init__(self, access_key_id: str, access_key_secret: str, timeout: int = 15):
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.timeout = timeout

    def _request(self, action: str, params: dict = None) -> dict:
        """发起签名请求"""
        query = {
            "AccessKeyId": self.access_key_id,
            "Action": action,
            "Format": "JSON",
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": str(uuid.uuid4()),
            "SignatureVersion": "1.0",
            "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "Version": API_VERSION,
        }
        if params:
            query.update(params)
        query["Signature"] = _sign(self.access_key_secret, query)

        url = API_ENDPOINT + "?" + urllib.parse.urlencode(query)
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8") if e.fp else ""
        except urllib.error.URLError as e:
            raise AliyunDNSAPIError(f"无法连接阿里云 DNS API: {e.reason}")

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise AliyunDNSAPIError("阿里云 DNS API 返回了无效响应")

        code = data.get("Code", "")
        if code and code != "200":
            raise AliyunDNSAPIError(data.get("Message", code), code)
        return data

    # ===== 记录管理 =====

    def describe_records(self, domain: str, rr: str = "", type: str = "") -> list:
        """查询域名解析记录列表（可按 RR 和类型过滤）"""
        params = {"DomainName": domain, "PageSize": 500}
        if rr:
            params["RRKeyWord"] = rr
        if type:
            params["TypeKeyWord"] = type
        data = self._request("DescribeDomainRecords", params)
        return data.get("DomainRecords", {}).get("Record", []) or []

    def find_record(self, domain: str, rr: str, type: str) -> dict:
        """查找指定 RR + 类型的记录（无则返回 None）"""
        for rec in self.describe_records(domain, rr=rr, type=type):
            if rec.get("RR") == rr and rec.get("Type") == type:
                return rec
        return None

    def add_record(self, domain: str, rr: str, type: str, value: str, ttl: int = 600) -> dict:
        """添加解析记录（RR 为子域名前缀，@ 表示主域名）"""
        return self._request("AddDomainRecord", {
            "DomainName": domain,
            "RR": rr,
            "Type": type,
            "Value": value,
            "TTL": ttl,
        })

    def update_record(self, record_id: str, rr: str, type: str, value: str, ttl: int = 600) -> dict:
        """更新解析记录"""
        return self._request("UpdateDomainRecord", {
            "RecordId": record_id,
            "RR": rr,
            "Type": type,
            "Value": value,
            "TTL": ttl,
        })

    def delete_record(self, record_id: str) -> dict:
        """删除解析记录"""
        return self._request("DeleteDomainRecord", {"RecordId": record_id})
