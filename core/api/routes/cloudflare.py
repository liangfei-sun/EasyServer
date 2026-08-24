"""
EasyServer Cloudflare Tunnel API
一键接入：验证 Token → 创建隧道 → 启动容器 → 配置路由 → 创建 DNS 记录
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from ..core.config_manager import ConfigManager
from ..core.docker_manager import DockerManager
from ..core.module_loader import ModuleLoader
from ..core.cloudflare_api import CloudflareClient, CloudflareAPIError
from ..core.alidns_api import AliyunDNSClient, AliyunDNSAPIError
from .dns import _get_aliyun_credentials
import asyncio
import logging
import os
import re

router = APIRouter(prefix="/api/cloudflare", tags=["cloudflare"])

logger = logging.getLogger("easyserver.cloudflare")

PROJECT_ROOT = os.environ.get("EASYSERVER_ROOT", "/app")

# 后台任务引用集，防止异步任务被 GC 提前回收
_background_tasks = set()


def _trigger_dns_sync_background():
    """异步触发一次 DNS 同步（不阻塞 HTTP 响应，异常不影响主流程）"""
    from .dns import sync_dns

    async def _run():
        try:
            result = await sync_dns()
            summary = result.get("summary", {}) if isinstance(result, dict) else {}
            logger.info("后台 DNS 同步完成: %s", summary)
        except Exception as e:
            logger.warning("后台 DNS 同步失败（不影响主流程）: %s", e)

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

# 脱敏前缀
MASK_PREFIX = "***"


def _get_config_manager():
    return ConfigManager(PROJECT_ROOT)


def _get_docker_manager():
    return DockerManager(PROJECT_ROOT)


def _get_module_loader():
    return ModuleLoader(PROJECT_ROOT)


def _mask(value: str) -> str:
    return f"{MASK_PREFIX}{value[-4:]}" if value and len(value) > 4 else (MASK_PREFIX if value else "")


def _tunnel_cfg(cm) -> dict:
    return cm.get_config_value("cloudflare_tunnel", {}) or {}


def _save_tunnel_cfg(cm, cfg: dict):
    cm.set_config_value("cloudflare_tunnel", cfg)


def _get_domain(cm) -> str:
    return cm.get_config_value("domain", "") or ""


def _get_dns_provider(cm):
    """获取显式配置的 DNS 提供商；未显式配置时返回 None（由调用方回退旧行为）"""
    return cm.get_config_value("dns_provider", None) or None


def _get_cf_dns_token(cm) -> str:
    """获取 Cloudflare DNS 操作专用 token（dns_credentials.cloudflare.token）。
    缺失时直接抛出 HTTPException，不再静默回退到 tunnel token。
    """
    dns_creds = cm.get_config_value("dns_credentials", {})
    if isinstance(dns_creds, dict):
        cf_creds = dns_creds.get("cloudflare", {})
        if isinstance(cf_creds, dict):
            token = cf_creds.get("token")
            if token:
                return token
    raise HTTPException(
        status_code=400,
        detail="尚未配置 Cloudflare DNS Token，请在设置 → 网络配置中填写 dns_credentials.cloudflare.token 后重试",
    )


def _resolve_domain(cm, domain: Optional[str] = None) -> str:
    """解析目标域名：指定则用指定值，否则返回主域名"""
    if domain:
        # 验证域名已在配置中
        if not cm.get_domain_config(domain):
            raise HTTPException(status_code=400, detail=f"域名 {domain} 未在配置中添加")
        return domain
    return cm.get_primary_domain()


async def _ensure_tunnel_module_running(cm, dm) -> bool:
    """确保 cloudflare-tunnel 模块已安装并运行，未运行时自动安装启动（幂等的 docker compose up -d）
    返回是否本次触发了启动
    """
    module_id = "cloudflare-tunnel"
    status = await dm.async_get_module_status(module_id)
    if status.get("running"):
        return False
    result = await dm.async_start_module(module_id)
    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=f"cloudflare-tunnel 模块启动失败: {result.get('error') or '未知错误'}（请确认 .env 中 CF_TUNNEL_TOKEN 已配置）",
        )
    # 启动成功后才标记为已安装，避免启动失败也被永久标记
    if module_id not in cm.get_installed_modules():
        cm.add_installed_module(module_id)
    return True


class VerifyRequest(BaseModel):
    api_token: str


class SetupRequest(BaseModel):
    api_token: str
    account_id: Optional[str] = None
    tunnel_name: str = "easyserver-tunnel"


class PublishRequest(BaseModel):
    subdomain: str
    port: int
    protocol: str = "http"
    domain: Optional[str] = None  # 目标域名，不传则使用主域名


class UnpublishRequest(BaseModel):
    hostname: str


@router.post("/verify")
async def verify(request: VerifyRequest):
    """验证 API Token 有效性，并检查域名是否已托管到 Cloudflare"""
    cm = _get_config_manager()
    domain = _get_domain(cm)
    client = CloudflareClient(request.api_token.strip())
    try:
        token_info = client.verify_token()
    except CloudflareAPIError as e:
        return {"valid": False, "error": str(e)}

    accounts = []
    try:
        accounts = client.list_accounts()
    except Exception:
        pass  # Token 无账户列表权限时跳过

    zone = None
    zone_error = ""
    if domain:
        try:
            zone = client.get_zone(domain)
        except Exception as e:
            zone_error = str(e)

    # Account ID 获取顺序：账户列表 → Zone 反查（Zone 对象自带 account 字段）
    account_id = accounts[0]["id"] if accounts else ""
    account_name = accounts[0].get("name", "") if accounts else ""
    if not account_id and zone:
        account_id = zone.get("account", {}).get("id", "")
        account_name = zone.get("account", {}).get("name", "")

    # 探测 Tunnel 权限（有 account_id 时尝试获取隧道列表）
    tunnel_permission = "unknown"
    if account_id:
        try:
            client.list_tunnels(account_id)
            tunnel_permission = "ok"
        except CloudflareAPIError:
            tunnel_permission = "missing"

    return {
        "valid": True,
        "token_status": token_info.get("status", "active"),
        "accounts": [{"id": a.get("id"), "name": a.get("name")} for a in accounts],
        "account_id": account_id,
        "account_name": account_name,
        "tunnel_permission": tunnel_permission,
        "domain": domain,
        "zone_found": bool(zone),
        "zone_id": zone.get("id", "") if zone else "",
        "zone_error": zone_error,
    }


@router.post("/setup")
async def setup(request: SetupRequest):
    """一键接入：创建/复用隧道 → 保存凭证 → 启动 cloudflare-tunnel 模块"""
    cm = _get_config_manager()
    dm = _get_docker_manager()
    domain = _get_domain(cm)
    if not domain:
        raise HTTPException(status_code=400, detail="请先在全局设置中配置域名")

    api_token = request.api_token.strip()
    client = CloudflareClient(api_token)

    # 1. 验证 Token
    try:
        client.verify_token()
    except CloudflareAPIError as e:
        raise HTTPException(status_code=400, detail=f"Token 无效: {e}")

    # 2. 获取 Account ID（参数 → 账户列表 → Zone 反查）
    account_id = request.account_id or ""
    if not account_id:
        try:
            accounts = client.list_accounts()
            if accounts:
                account_id = accounts[0]["id"]
        except Exception:
            pass  # 无 Account 权限时尝试从 Zone 反查
    if not account_id:
        try:
            zone = client.get_zone(domain)
            if zone:
                account_id = zone.get("account", {}).get("id", "")
        except Exception:
            pass
    if not account_id:
        raise HTTPException(
            status_code=400,
            detail="无法自动获取账户 ID：请确认 Token 已授予 Account · Read 权限（或 Zone · DNS · Edit 权限）；"
                   "也可在高级选项中手动填写 Account ID（Cloudflare 首页 URL 中可见）",
        )

    # 3. 检查域名托管状态（警告不阻断）
    zone = None
    try:
        zone = client.get_zone(domain)
    except Exception:
        zone = None

    # 4. 查找已有隧道（同名复用）或创建
    tunnel_id = ""
    tunnel_token = ""
    tunnel_name = request.tunnel_name
    try:
        tunnels = client.list_tunnels(account_id)
        for t in tunnels:
            if t.get("name") == tunnel_name:
                tunnel_id = t["id"]
                break
        if not tunnel_id:
            created = client.create_tunnel(account_id, tunnel_name)
            tunnel_id = created["id"]
            tunnel_token = created.get("token", "")
        if not tunnel_token:
            tunnel_token = client.get_tunnel_token(account_id, tunnel_id)
    except CloudflareAPIError as e:
        raise HTTPException(status_code=400, detail=f"隧道操作失败: {e}")

    # 5. 保存配置
    cfg = _tunnel_cfg(cm)
    cfg.update({
        "api_token": api_token,
        "account_id": account_id,
        "tunnel_id": tunnel_id,
        "tunnel_name": tunnel_name,
        "zone_id": zone.get("id", "") if zone else cfg.get("zone_id", ""),
    })
    _save_tunnel_cfg(cm, cfg)
    cm.set_env_value("CF_API_TOKEN", api_token)
    cm.set_env_value("CF_ACCOUNT_ID", account_id)
    cm.set_env_value("CF_TUNNEL_ID", tunnel_id)
    if tunnel_token:
        cm.set_env_value("CF_TUNNEL_TOKEN", tunnel_token)

    # 6. 启动 cloudflare-tunnel 模块
    installed = cm.get_installed_modules()
    results = []
    if "cloudflare-tunnel" not in installed:
        cm.add_installed_module("cloudflare-tunnel")
    try:
        dm.start_module("cloudflare-tunnel")
        results.append({"module": "cloudflare-tunnel", "action": "start", "success": True})
    except Exception as e:
        results.append({"module": "cloudflare-tunnel", "action": "start", "success": False, "error": str(e)})

    return {
        "success": True,
        "account_id": account_id,
        "tunnel_id": tunnel_id,
        "tunnel_name": tunnel_name,
        "zone_found": bool(zone),
        "zone_warning": "" if zone else "域名尚未托管到 Cloudflare，请在 Cloudflare 添加站点并修改 NS 记录",
        "results": results,
    }


@router.get("/status")
async def status():
    """查询隧道配置状态、连接状态、已发布路由与可发布服务"""
    cm = _get_config_manager()
    cfg = _tunnel_cfg(cm)
    domain = _get_domain(cm)
    env = cm.load_env()

    tunnel_id = cfg.get("tunnel_id", "")
    api_token = cfg.get("api_token", "")
    connected = False
    routes = []
    error = ""

    if tunnel_id and api_token:
        client = CloudflareClient(api_token)
        try:
            conns = client.get_tunnel_connections(cfg.get("account_id", ""), tunnel_id)
            connected = len(conns) > 0
            tcfg = client.get_tunnel_config(cfg.get("account_id", ""), tunnel_id) or {}
            ingress = (tcfg.get("config") or {}).get("ingress", []) or []
            routes = [
                {"hostname": i.get("hostname", ""), "service": i.get("service", "")}
                for i in ingress if i.get("hostname")
            ]
        except CloudflareAPIError as e:
            error = str(e)
        except Exception as e:
            error = str(e)

    # 获取所有已配置域名，用于多域名 published 判断
    all_domains = cm.get_domains()
    all_domain_names = [d.get("domain", "") for d in all_domains if d.get("domain")]
    if not all_domain_names and domain:
        all_domain_names = [domain]

    # 构建 tunnel routes 的 hostname 集合（用于快速查找）
    route_hostnames = set(r["hostname"] for r in routes)

    # 可发布服务列表（已安装且配置了子域名/端口）
    services = []
    ml = _get_module_loader()
    installed_ids = cm.get_installed_modules()
    for mid in installed_ids:
        metadata = ml.get_module_by_id(mid)
        if not metadata:
            continue
        access = metadata.get("access", {})
        if not access or access.get("is_proxy"):
            continue
        subdomain = access.get("subdomain", "")
        port = access.get("port", 0)
        if not subdomain or not port:
            continue
        # 从 .env 读取实际端口
        for item in metadata.get("config", []):
            if item.get("type") == "number" and "port" in item.get("key", "").lower():
                env_key = item["key"]
                if env_key in env:
                    try:
                        port = int(env[env_key])
                    except (ValueError, TypeError):
                        pass
                break
        # 构建该服务在所有域名上的 hostname 列表
        all_hostnames = [f"{subdomain}.{d_name}" for d_name in all_domain_names if d_name]
        # 检查该服务的 subdomain 是否在任何域名的 tunnel 路由中
        published = False
        service_hostname = ""
        for candidate in all_hostnames:
            if candidate in route_hostnames:
                published = True
                service_hostname = candidate
                break
        # 如果未发布，默认使用主域名构建展示用 hostname
        if not service_hostname:
            service_hostname = f"{subdomain}.{domain}" if domain else ""
        services.append({
            "module": mid,
            "name": metadata.get("name", mid),
            "subdomain": subdomain,
            "port": port,
            "hostname": service_hostname,
            "all_hostnames": all_hostnames,
            "published": published,
        })

    # 管理面板（非服务模块，不在模块列表中，单独加入）
    panel_subdomain = cm.get_config_value("panel_subdomain", "panel") or "panel"
    panel_all_hostnames = [f"{panel_subdomain}.{d_name}" for d_name in all_domain_names if d_name]
    panel_published = False
    panel_hostname = ""
    for candidate in panel_all_hostnames:
        if candidate in route_hostnames:
            panel_published = True
            panel_hostname = candidate
            break
    if not panel_hostname:
        panel_hostname = f"{panel_subdomain}.{domain}" if domain else ""
    services.append({
        "module": "panel",
        "name": "EasyServer 管理面板",
        "subdomain": panel_subdomain,
        "port": 8900,
        "hostname": panel_hostname,
        "all_hostnames": panel_all_hostnames,
        "published": panel_published,
    })

    # 为每条路由标记所属域名（按域名长度降序匹配，最长优先）
    sorted_domains = sorted(set(d.get("domain", "") for d in all_domains if d.get("domain")), key=len, reverse=True)

    # 收集所有服务的 subdomain 集合（用于判断路由是否被服务使用）
    service_subdomains = set(s["subdomain"] for s in services if s.get("subdomain"))

    enriched_routes = []
    # 记录每个域名下是否有已发布的路由
    domain_has_published = set()
    for r in routes:
        rh = r.get("hostname", "")
        route_domain = ""
        for d in sorted_domains:
            if rh == d or rh.endswith("." + d):
                route_domain = d
                break
        # 判断该路由 hostname 是否匹配某个已发布服务的 subdomain
        route_published = False
        for sub in service_subdomains:
            if rh.startswith(sub + "."):
                route_published = True
                break
        if route_published and route_domain:
            domain_has_published.add(route_domain)
        enriched_routes.append({
            "hostname": rh,
            "service": r.get("service", ""),
            "domain": route_domain,
            "published": route_published,
        })

    # 多域名信息（all_domains 已在上方获取）
    domains_info = [
        {
            "domain": d.get("domain", ""),
            "dns_provider": d.get("dns_provider", ""),
            "purpose": d.get("purpose", ""),
            "status": d.get("status", ""),
            "published": d.get("domain", "") in domain_has_published,
        }
        for d in all_domains
    ]

    return {
        "configured": bool(tunnel_id),
        "account_id": cfg.get("account_id", ""),
        "tunnel_id": tunnel_id,
        "tunnel_name": cfg.get("tunnel_name", ""),
        "api_token_masked": _mask(api_token),
        "domain": domain,
        "domains": domains_info,
        "connected": connected,
        "error": error,
        "routes": enriched_routes,
        "services": services,
    }


@router.post("/publish")
async def publish(request: PublishRequest):
    """发布服务：添加 ingress 路由 + 创建 DNS CNAME 记录"""
    cm = _get_config_manager()
    cfg = _tunnel_cfg(cm)
    target_domain = _resolve_domain(cm, request.domain)
    domain_cfg = cm.get_domain_config(target_domain)
    tunnel_id = cfg.get("tunnel_id", "")
    api_token = cfg.get("api_token", "")
    account_id = cfg.get("account_id", "")
    zone_id = cfg.get("zone_id", "")

    if not tunnel_id or not api_token:
        raise HTTPException(status_code=400, detail="尚未完成 Cloudflare Tunnel 接入，请先一键接入")
    if not target_domain:
        raise HTTPException(status_code=400, detail="请先配置域名")

    subdomain = request.subdomain.strip().lower()
    if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", subdomain):
        raise HTTPException(status_code=400, detail="子域名格式不正确（仅支持字母、数字、连字符）")
    if not (1 <= request.port <= 65535):
        raise HTTPException(status_code=400, detail="端口号必须在 1-65535 之间")

    hostname = f"{subdomain}.{target_domain}"
    service = f"{request.protocol}://localhost:{request.port}"
    client = CloudflareClient(api_token)
    # 优先使用目标域名配置的 dns_provider，否则回退全局配置
    dns_provider = domain_cfg.get("dns_provider") or _get_dns_provider(cm)

    # 未显式配置 dns_provider 时回退旧行为：有 zone_id 走 Cloudflare zone 分支，否则提示先完成网络配置
    if not dns_provider:
        if zone_id:
            dns_provider = "cloudflare"
        else:
            raise HTTPException(
                status_code=400,
                detail="尚未配置 DNS 提供商且未获取到 Zone ID，请先在网络配置中完成 DNS 提供商配置后重试",
            )

    # 0a. DNS 凭证预检查（避免 ingress 更新后才发现凭证缺失）
    aliyun_creds = None
    cf_dns_token = None
    if dns_provider == "aliyun":
        aliyun_creds = _get_aliyun_credentials(cm)
        if not (aliyun_creds["key"] and aliyun_creds["secret"]):
            raise HTTPException(
                status_code=400,
                detail="当前 DNS 提供商为阿里云，但尚未配置阿里云 AccessKey。请在设置 → 网络配置中填写阿里云 AccessKey 后重试",
            )
    elif dns_provider == "cloudflare":
        cf_dns_token = _get_cf_dns_token(cm)

    # 0b. 确保 cloudflare-tunnel 模块已安装并运行（幂等 docker compose up -d）
    module_started = False
    try:
        module_started = await _ensure_tunnel_module_running(cm, _get_docker_manager())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cloudflare-tunnel 模块状态检查/启动异常: {e}")

    # 1. 更新 ingress 配置
    try:
        tcfg = client.get_tunnel_config(account_id, tunnel_id) or {}
        ingress = (tcfg.get("config") or {}).get("ingress", []) or []
        ingress = [i for i in ingress if i.get("hostname") != hostname]
        ingress.insert(0, {"hostname": hostname, "service": service})
        if ingress and ingress[-1].get("hostname"):
            ingress.append({"service": "http_status:404"})
        if not ingress:
            ingress = [{"hostname": hostname, "service": service}, {"service": "http_status:404"}]
        client.update_tunnel_config(account_id, tunnel_id, ingress)
    except CloudflareAPIError as e:
        raise HTTPException(status_code=400, detail=f"更新路由失败: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新路由异常: {e}")

    # 2. 创建 DNS CNAME 记录（已存在则跳过，按 dns_provider 分流）
    dns_created = False
    dns_action = "existing"
    dns_warning = ""
    dns_error = ""
    content = f"{tunnel_id}.cfargotunnel.com"
    if dns_provider == "aliyun":
        try:
            ali_client = AliyunDNSClient(aliyun_creds["key"], aliyun_creds["secret"])
            existing = ali_client.find_record(target_domain, subdomain, "CNAME")
            if not existing:
                # 阿里云 DNS 强制 CNAME 与同名 A/AAAA 互斥，创建前先清理域名反代遗留的 A/AAAA 记录
                cleanup_failed = []
                for legacy_type in ("A", "AAAA"):
                    try:
                        legacy = ali_client.find_record(target_domain, subdomain, legacy_type)
                        if legacy:
                            ali_client.delete_record(legacy["RecordId"])
                            logger.info(
                                "已清理同名 %s 记录 (RecordId=%s, Value=%s) 以便创建 CNAME",
                                legacy_type, legacy.get("RecordId", "?"), legacy.get("Value", "?"),
                            )
                    except AliyunDNSAPIError as e:
                        logger.error(
                            "清理同名 %s 记录失败 (RecordId=%s, Value=%s): %s",
                            legacy_type, legacy.get("RecordId", "?"), legacy.get("Value", "?"), e,
                        )
                        cleanup_failed.append(legacy_type)
                if cleanup_failed:
                    dns_error = (
                        f"删除旧 DNS 记录失败（{', '.join(cleanup_failed)}），"
                        f"请手动在阿里云控制台删除 {subdomain}.{target_domain} 的 A/AAAA 记录后重试"
                    )
                    logger.error("DNS 清理失败，跳过 CNAME 创建: %s", dns_error)
                else:
                    ali_client.add_record(target_domain, subdomain, "CNAME", content)
                    dns_created = True
                    dns_action = "created"
            elif existing.get("Value") != content:
                # 同名 CNAME 指向其他目标，更新为隧道地址（记录旧值告警，避免静默覆盖）
                old_value = existing.get("Value", "")
                ali_client.update_record(existing["RecordId"], subdomain, "CNAME", content)
                dns_action = "updated"
                dns_warning = f"已覆盖原有 CNAME 记录（原值: {old_value} → {content}），如非预期请检查该子域名是否被其他服务占用"
        except AliyunDNSAPIError as e:
            dns_warning = f"阿里云 DNS 记录创建失败: {e}（可稍后手动添加 CNAME {hostname} → {content}）"
    elif zone_id:
        # Cloudflare DNS 操作使用 DNS token（预检查已在 0a 阶段完成，此处兜底获取）
        try:
            # 多域名时每个域名可能有不同的 zone_id
            target_zone_id = zone_id
            if domain_cfg.get("dns_provider") == "cloudflare" and domain_cfg.get("zone_id"):
                target_zone_id = domain_cfg["zone_id"]
            dns_client = CloudflareClient(cf_dns_token)
            records = dns_client.list_dns_records(target_zone_id, hostname)
            if not records:
                dns_client.create_dns_record(target_zone_id, subdomain, content, proxied=True)
                dns_created = True
                dns_action = "created"
        except CloudflareAPIError as e:
            dns_warning = f"DNS 记录创建失败: {e}（可稍后手动添加 CNAME {hostname} → {tunnel_id}.cfargotunnel.com）"
    else:
        dns_warning = "未获取到 Zone ID，请手动添加 DNS 记录"

    # 3. 更新本地配置
    routes = cfg.get("routes", [])
    routes = [r for r in routes if r.get("hostname") != hostname]
    routes.append({"hostname": hostname, "service": service})
    cfg["routes"] = routes
    _save_tunnel_cfg(cm, cfg)

    return {
        "success": True,
        "hostname": hostname,
        "domain": target_domain,
        "service": service,
        "dns_created": dns_created,
        "dns_action": dns_action,
        "dns_warning": dns_warning,
        "dns_error": dns_error,
        "module_auto_started": module_started,
        "message": f"已发布 {hostname} → {service}",
    }


@router.post("/unpublish")
async def unpublish(request: UnpublishRequest):
    """取消发布：移除 ingress 路由 + 删除 DNS 记录"""
    cm = _get_config_manager()
    cfg = _tunnel_cfg(cm)
    hostname = request.hostname.strip().lower()
    tunnel_id = cfg.get("tunnel_id", "")
    api_token = cfg.get("api_token", "")
    account_id = cfg.get("account_id", "")
    zone_id = cfg.get("zone_id", "")

    # 从 hostname 提取域名（如 sub.lfblog.top → lfblog.top）
    # 优先匹配已知域名列表，回退使用全局 domain
    target_domain = ""
    known_domains = sorted([d.get("domain", "") for d in cm.get_domains() if d.get("domain")], key=len, reverse=True)
    for d in known_domains:
        if hostname.endswith("." + d):
            target_domain = d
            break
    if not target_domain:
        target_domain = _get_domain(cm)

    domain_cfg = cm.get_domain_config(target_domain) if target_domain else {}

    if not tunnel_id or not api_token:
        raise HTTPException(status_code=400, detail="尚未完成 Cloudflare Tunnel 接入")

    # 解析 dns_provider（与 publish 保持一致的逻辑）
    dns_provider = domain_cfg.get("dns_provider") or _get_dns_provider(cm)
    if not dns_provider:
        if zone_id:
            dns_provider = "cloudflare"
        else:
            dns_provider = None

    # DNS 凭证预检查（避免 ingress 更新后才发现凭证缺失）
    aliyun_creds = None
    cf_dns_token = None
    warnings_list = []
    if dns_provider == "aliyun":
        aliyun_creds = _get_aliyun_credentials(cm)
        if not (aliyun_creds["key"] and aliyun_creds["secret"]):
            warnings_list.append("阿里云 AccessKey 未配置，DNS 记录未自动删除（请先完成网络配置或手动删除）")
    elif dns_provider == "cloudflare":
        try:
            cf_dns_token = _get_cf_dns_token(cm)
        except HTTPException:
            warnings_list.append("Cloudflare DNS Token 未配置，DNS 记录未自动删除（请先完成网络配置或手动删除）")

    client = CloudflareClient(api_token)

    # 1. 更新 ingress
    try:
        tcfg = client.get_tunnel_config(account_id, tunnel_id) or {}
        ingress = [(i if isinstance(i, dict) else {}) for i in ((tcfg.get("config") or {}).get("ingress", []) or [])]
        ingress = [i for i in ingress if i.get("hostname") != hostname]
        if not ingress:
            ingress = [{"service": "http_status:404"}]
        client.update_tunnel_config(account_id, tunnel_id, ingress)
    except CloudflareAPIError as e:
        raise HTTPException(status_code=400, detail=f"移除路由失败: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"移除路由异常: {e}")

    # 2. 删除 DNS 记录（按 dns_provider 分流，记录不存在时宽容处理）
    if dns_provider == "aliyun":
        if aliyun_creds and aliyun_creds["key"] and aliyun_creds["secret"]:
            try:
                # 从 hostname 还原 RR 前缀（sub.domain → sub）
                rr = hostname[: -(len(target_domain) + 1)] if target_domain and hostname.endswith("." + target_domain) else hostname
                ali_client = AliyunDNSClient(aliyun_creds["key"], aliyun_creds["secret"])
                rec = ali_client.find_record(target_domain, rr, "CNAME")
                if rec:
                    ali_client.delete_record(rec["RecordId"])
            except AliyunDNSAPIError as e:
                warnings_list.append(f"阿里云 DNS 记录删除失败: {e}")
    elif zone_id:
        if not cf_dns_token:
            warnings_list.append("Cloudflare DNS Token 未配置，DNS 记录未自动删除（请先完成网络配置或手动删除）")
        else:
            try:
                # 多域名时每个域名可能有不同的 zone_id
                target_zone_id = zone_id
                if domain_cfg.get("dns_provider") == "cloudflare" and domain_cfg.get("zone_id"):
                    target_zone_id = domain_cfg["zone_id"]
                dns_client = CloudflareClient(cf_dns_token)
                for rec in dns_client.list_dns_records(target_zone_id, hostname):
                    dns_client.delete_dns_record(target_zone_id, rec["id"])
            except CloudflareAPIError as e:
                warnings_list.append(f"DNS 记录删除失败: {e}")
    else:
        warnings_list.append("未配置 DNS 提供商且未获取到 Zone ID，DNS 记录未自动删除（请先完成网络配置或手动删除）")

    # 3. 更新本地配置
    routes = [r for r in cfg.get("routes", []) if r.get("hostname") != hostname]
    cfg["routes"] = routes
    _save_tunnel_cfg(cm, cfg)

    # 4. 异步触发一次 DNS 同步，重建域名反代解析记录（删除 CNAME 后子域名无任何记录）
    try:
        _trigger_dns_sync_background()
    except Exception as e:
        logger.warning("后台 DNS 同步任务调度失败: %s", e)

    return {"success": True, "hostname": hostname, "domain": target_domain, "warnings": warnings_list}
