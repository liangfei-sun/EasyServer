"""
EasyServer DNS Sync API
自动同步 DNS 解析记录：根据公网 IP 类型（IPv4/IPv6）为所有服务子域名创建 A / AAAA 记录
支持提供商：阿里云（alidns）、Cloudflare
"""

from fastapi import APIRouter, HTTPException, Query
from ..core.config_manager import ConfigManager
from ..core.module_loader import ModuleLoader
from ..core.alidns_api import AliyunDNSClient, AliyunDNSAPIError
from ..core.cloudflare_api import CloudflareClient, CloudflareAPIError
from ..core.ip_utils import get_public_ips
from typing import Optional
import logging
import os

router = APIRouter(prefix="/api/dns", tags=["dns"])

logger = logging.getLogger("easyserver.dns")

PROJECT_ROOT = os.environ.get("EASYSERVER_ROOT", "/app")

# 域名反代 A/AAAA 记录统一关闭 Cloudflare 代理（DNS only，直连服务器 IP）
PROXIED = False


def _get_config_manager():
    return ConfigManager(PROJECT_ROOT)


def _get_module_loader():
    return ModuleLoader(PROJECT_ROOT)


def _get_aliyun_credentials(cm: ConfigManager) -> dict:
    """获取阿里云 DNS 凭证（config.yaml -> .env 兜底）"""
    cfg = cm.load_config()
    creds = (cfg.get("dns_credentials", {}) or {}).get("aliyun", {}) or {}
    env = cm.load_env()
    key = creds.get("key", "") or env.get("ACME_ALI_KEY", "")
    secret = creds.get("secret", "") or env.get("ACME_ALI_SECRET", "")
    return {"key": key, "secret": secret}


def _get_cloudflare_token(cm: ConfigManager) -> str:
    """获取 Cloudflare API Token（隧道配置 -> DNS 提供商凭证 -> .env 三级降级）
    注意：eyJ 开头的是 Tunnel Token（cloudflared 运行时凭证），不是 API Token，必须跳过
    """
    cfg = cm.load_config()
    env = cm.load_env()

    def _valid(token: str) -> bool:
        # 排除 JWT 格式的 Tunnel Token；API Token 以 cfut_ 或 40 位十六进制开头
        return bool(token) and not token.startswith("eyJ")

    # 1. 隧道配置中的 API Token（已在 verify/setup 时验证过）
    tunnel_cfg = cfg.get("cloudflare_tunnel", {}) or {}
    token = tunnel_cfg.get("api_token", "")
    if _valid(token):
        return token
    # 2. DNS 提供商凭证
    creds = (cfg.get("dns_credentials", {}) or {}).get("cloudflare", {}) or {}
    token = creds.get("token", "")
    if _valid(token):
        return token
    # 3. .env 兜底
    token = env.get("ACME_CF_TOKEN", "")
    if _valid(token):
        return token
    # 4. 最后尝试 CF_API_TOKEN
    return env.get("CF_API_TOKEN", "")


def _get_tunnel_published_subdomains(cm: ConfigManager, domain: Optional[str] = None) -> set:
    """提取已通过 Cloudflare Tunnel 发布的子域名集合（cloudflare_tunnel.routes 为路由唯一数据源）。
    domain 指定时只提取该域名下的子域名。
    """
    cfg = cm.load_config()
    target_domain = domain or cm.get_primary_domain()
    tunnel_cfg = cfg.get("cloudflare_tunnel", {}) or {}
    routes = tunnel_cfg.get("routes", []) or []
    suffix = f".{target_domain}" if target_domain else ""
    subs = set()
    for r in routes:
        hostname = (r.get("hostname") or "").strip()
        if not hostname:
            continue
        if suffix and hostname.endswith(suffix):
            subs.add(hostname[: -len(suffix)])
        elif not suffix:
            subs.add(hostname)
    return subs


def _get_target_subdomains(cm: ConfigManager, ml: ModuleLoader, exclude_tunnel_published: bool = False, domain: Optional[str] = None) -> list:
    """收集需要解析的子域名列表（已安装模块的 access.subdomain + 管理面板）
    exclude_tunnel_published=True 时排除已通过 Tunnel 发布的子域名（避免覆盖其 CNAME 记录）
    domain 指定时只收集该域名下的子域名。
    """
    excluded = _get_tunnel_published_subdomains(cm, domain=domain) if exclude_tunnel_published else set()
    subdomains = []
    installed_ids = cm.get_installed_modules()
    for mid in installed_ids:
        metadata = ml.get_module_by_id(mid)
        if not metadata:
            continue
        access = metadata.get("access", {})
        if not access or access.get("is_proxy"):
            continue
        sub = access.get("subdomain", "")
        if sub and sub not in excluded:
            subdomains.append({"subdomain": sub, "module": mid})
    # 管理面板
    panel_sub = cm.get_config_value("panel_subdomain", "panel") or "panel"
    if panel_sub not in excluded:
        subdomains.append({"subdomain": panel_sub, "module": "panel"})
    # 去重（保留 module 名）
    seen = set()
    result = []
    for item in subdomains:
        if item["subdomain"] not in seen:
            seen.add(item["subdomain"])
            result.append(item)
    return result


def _build_targets(ips: dict) -> list:
    """根据公网 IP 构造同步目标 [(Type, Value)]"""
    targets = []
    if ips.get("ipv4"):
        targets.append(("A", ips["ipv4"]))
    if ips.get("ipv6"):
        targets.append(("AAAA", ips["ipv6"]))
    return targets


@router.get("/status")
async def dns_status(domain: Optional[str] = Query(None, description="指定域名，未指定时返回主域名状态")):
    """查询 DNS 同步状态：提供商、凭证、公网 IP、各子域名记录现状"""
    cm = _get_config_manager()
    ml = _get_module_loader()
    cfg = cm.load_config()

    target_domain = domain or cm.get_primary_domain()
    domain_cfg = cm.get_domain_config(target_domain) if domain else {}
    provider = domain_cfg.get("dns_provider") or cfg.get("dns_provider", "aliyun")
    ips = get_public_ips()

    # 凭证状态
    creds_configured = False
    if provider == "aliyun":
        aliyun = _get_aliyun_credentials(cm)
        creds_configured = bool(aliyun["key"] and aliyun["secret"])
    elif provider == "cloudflare":
        creds_configured = bool(_get_cloudflare_token(cm))

    # 查询各子域名现有记录
    records_status = []
    if creds_configured and target_domain:
        try:
            if provider == "aliyun":
                aliyun = _get_aliyun_credentials(cm)
                client = AliyunDNSClient(aliyun["key"], aliyun["secret"])
                for item in _get_target_subdomains(cm, ml, domain=target_domain):
                    existing = []
                    for rec in client.describe_records(target_domain, rr=item["subdomain"]):
                        existing.append({
                            "type": rec.get("Type"),
                            "value": rec.get("Value"),
                            "record_id": rec.get("RecordId"),
                        })
                    records_status.append({
                        "subdomain": item["subdomain"],
                        "module": item["module"],
                        "records": existing,
                    })
            elif provider == "cloudflare":
                client = CloudflareClient(_get_cloudflare_token(cm))
                zone = client.get_zone(target_domain)
                if not zone:
                    records_status.append({"error": "域名未托管到 Cloudflare 或 Token 无 Zone 权限"})
                else:
                    zone_id = zone["id"]
                    for item in _get_target_subdomains(cm, ml, domain=target_domain):
                        hostname = f"{item['subdomain']}.{target_domain}"
                        existing = []
                        for rec in client.list_dns_records(zone_id, hostname):
                            existing.append({
                                "type": rec.get("type"),
                                "value": rec.get("content"),
                                "record_id": rec.get("id"),
                                "proxied": rec.get("proxied"),
                            })
                        records_status.append({
                            "subdomain": item["subdomain"],
                            "module": item["module"],
                            "records": existing,
                        })
        except (AliyunDNSAPIError, CloudflareAPIError) as e:
            records_status.append({"error": str(e)})

    return {
        "provider": provider,
        "domain": target_domain,
        "credentials_configured": creds_configured,
        "public_ipv4": ips["ipv4"],
        "public_ipv6": ips["ipv6"],
        "record_types": ips["record_types"],
        "records": records_status,
    }


@router.post("/sync")
async def sync_dns(domain: Optional[str] = Query(None, description="指定域名，未指定时同步主域名")):
    """自动同步 DNS 记录：为所有子域名创建/更新 A / AAAA 记录（幂等）。
    domain 指定时只同步该域名的子域名记录；未指定时同步主域名（向后兼容）。
    """
    cm = _get_config_manager()
    ml = _get_module_loader()
    cfg = cm.load_config()

    target_domain = domain or cm.get_primary_domain()
    if not target_domain:
        raise HTTPException(status_code=400, detail="请先配置域名")

    # 获取该域名的 DNS 提供商配置
    domain_cfg = cm.get_domain_config(target_domain) if domain else {}
    provider = domain_cfg.get("dns_provider") or cfg.get("dns_provider", "aliyun")

    if provider not in ("aliyun", "cloudflare"):
        raise HTTPException(status_code=400, detail="当前 DNS 提供商暂不支持自动同步，请先在网络配置中切换到阿里云或 Cloudflare")

    # 凭证检查
    if provider == "aliyun":
        creds = _get_aliyun_credentials(cm)
        if not (creds["key"] and creds["secret"]):
            raise HTTPException(status_code=400, detail="未配置阿里云 DNS 凭证，请在网络配置中填写 AccessKey")
    else:
        token = _get_cloudflare_token(cm)
        if not token:
            raise HTTPException(status_code=400, detail="未配置 Cloudflare API Token，请在网络配置中填写")

    # 探测公网 IP
    ips = get_public_ips()
    if not (ips["ipv4"] or ips["ipv6"]):
        raise HTTPException(status_code=400, detail="无法检测到服务器公网 IP，请检查网络连接")

    targets = _build_targets(ips)
    results = []

    # hybrid 模式下，跳过已 Tunnel 发布的服务，避免覆盖其 CNAME 记录
    # （domain 模式不在此排除：遗留 CNAME 冲突由下方同名 CNAME 冲突保护兜底，以 skipped 形式可见）
    access_mode = cfg.get("access_mode", "domain")
    tunnel_cfg = cfg.get("cloudflare_tunnel", {}) or {}
    tunnel_routes = tunnel_cfg.get("routes", []) or []
    exclude_tunnel = (
        access_mode == "hybrid"
        and bool(tunnel_cfg.get("tunnel_id"))
        and bool(tunnel_routes)
    )
    subdomains = _get_target_subdomains(cm, ml, exclude_tunnel_published=exclude_tunnel, domain=target_domain)

    if provider == "aliyun":
        client = AliyunDNSClient(creds["key"], creds["secret"])
        for item in subdomains:
            rr = item["subdomain"]
            # 冲突保护（与 Cloudflare provider 对齐）：存在同名 CNAME（Tunnel 发布）时跳过 A/AAAA 同步
            try:
                cname_conflict = client.find_record(target_domain, rr, "CNAME")
            except AliyunDNSAPIError:
                cname_conflict = None
            if cname_conflict:
                logger.info("DNS 同步跳过 %s.%s：存在同名 CNAME 记录（Tunnel 发布），避免冲突", rr, target_domain)
                for rec_type, value in targets:
                    results.append({
                        "subdomain": rr,
                        "type": rec_type,
                        "value": value,
                        "action": "skipped",
                        "success": True,
                        "reason": f"存在同名 CNAME 记录（{cname_conflict.get('Value')}），已跳过",
                    })
                continue
            for rec_type, value in targets:
                status = {"subdomain": rr, "type": rec_type, "value": value}
                try:
                    existing = client.find_record(target_domain, rr, rec_type)
                    if not existing:
                        client.add_record(target_domain, rr, rec_type, value)
                        status["action"] = "created"
                    elif existing.get("Value") == value:
                        status["action"] = "unchanged"
                    else:
                        client.update_record(existing["RecordId"], rr, rec_type, value)
                        status["action"] = "updated"
                        status["old_value"] = existing.get("Value")
                    status["success"] = True
                except AliyunDNSAPIError as e:
                    status["success"] = False
                    status["error"] = str(e)
                results.append(status)
    else:
        client = CloudflareClient(token)
        try:
            zone = client.get_zone(target_domain)
        except CloudflareAPIError as e:
            raise HTTPException(status_code=400, detail=f"Cloudflare Zone 查询失败: {e}")
        if not zone:
            raise HTTPException(status_code=400, detail="域名未托管到 Cloudflare，请先在 Cloudflare 添加站点并修改 NS 记录")
        zone_id = zone["id"]

        for item in subdomains:
            hostname = f"{item['subdomain']}.{target_domain}"
            for rec_type, value in targets:
                status = {"subdomain": item["subdomain"], "type": rec_type, "value": value}
                try:
                    records = client.list_dns_records(zone_id, hostname)
                    existing = next(
                        (r for r in records if r.get("type") == rec_type),
                        None,
                    )
                    if not existing:
                        # 检查同名冲突记录（如 Tunnel 发布的 CNAME），防止误覆盖
                        conflict = next((r for r in records if r.get("type") != rec_type), None)
                        if conflict:
                            status["success"] = False
                            status["error"] = (
                                f"存在冲突的 {conflict.get('type')} 记录（{conflict.get('content')}），"
                                "请先在「服务发布」中取消发布或手动删除该记录后再同步"
                            )
                            results.append(status)
                            continue
                        client.create_dns_record(zone_id, hostname, value, proxied=PROXIED, record_type=rec_type)
                        status["action"] = "created"
                    elif existing.get("content") == value:
                        status["action"] = "unchanged"
                    else:
                        client.update_dns_record(zone_id, existing["id"], hostname, value, proxied=PROXIED, record_type=rec_type)
                        status["action"] = "updated"
                        status["old_value"] = existing.get("content")
                    status["success"] = True
                except CloudflareAPIError as e:
                    status["success"] = False
                    status["error"] = str(e)
                results.append(status)

    created = len([r for r in results if r.get("action") == "created"])
    updated = len([r for r in results if r.get("action") == "updated"])
    unchanged = len([r for r in results if r.get("action") == "unchanged"])
    skipped = len([r for r in results if r.get("action") == "skipped"])
    failed = len([r for r in results if not r.get("success")])

    return {
        "success": True,
        "provider": provider,
        "domain": target_domain,
        "public_ipv4": ips["ipv4"],
        "public_ipv6": ips["ipv6"],
        "summary": {"created": created, "updated": updated, "unchanged": unchanged, "skipped": skipped, "failed": failed},
        "results": results,
    }
