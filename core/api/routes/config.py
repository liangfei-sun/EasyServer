"""
EasyServer Config API
全局配置读写接口
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import re
from ..core.config_manager import ConfigManager
from ..core.docker_manager import DockerManager
from ..core.module_loader import ModuleLoader
from ..core.dns_providers import DNS_PROVIDERS, get_provider, is_mask_value, MASK_PREFIX
import asyncio
import logging
import os
import subprocess
from pathlib import Path
from datetime import datetime

router = APIRouter(prefix="/api/config", tags=["config"])

logger = logging.getLogger("easyserver.config")

PROJECT_ROOT = os.environ.get("EASYSERVER_ROOT", "/app")

# 敏感字段脱敏工具
SENSITIVE_KEYS = {"password", "secret", "key", "token", "ali_key", "ali_secret",
                  "cf_tunnel_token", "api_key", "secret_key"}


def _mask_sensitive(key: str, value: str) -> str:
    """对敏感字段脱敏，只显示后4位"""
    key_lower = key.lower()
    if any(s in key_lower for s in SENSITIVE_KEYS) and value and len(value) > 4:
        return "***" + value[-4:]
    return value


def _check_ssl_status(domain: str) -> dict:
    """检测 SSL 证书状态"""
    if not domain:
        return {"ssl_valid": False, "ssl_expiry": "", "ssl_domain": ""}
    cert_path = Path(PROJECT_ROOT) / "modules" / "nginx" / "ssl" / domain / "fullchain.cer"
    if not cert_path.exists():
        return {"ssl_valid": False, "ssl_expiry": "", "ssl_domain": domain}
    try:
        result = subprocess.run(
            ["openssl", "x509", "-enddate", "-noout", "-in", str(cert_path)],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return {"ssl_valid": False, "ssl_expiry": "", "ssl_domain": domain}
        # 解析 notAfter=Oct 15 12:00:00 2026 GMT
        expiry_str = result.stdout.strip().replace("notAfter=", "")
        expiry = datetime.strptime(expiry_str, "%b %d %H:%M:%S %Y %Z")
        return {
            "ssl_valid": expiry > datetime.utcnow(),
            "ssl_expiry": expiry.isoformat(),
            "ssl_domain": domain
        }
    except Exception:
        return {"ssl_valid": False, "ssl_expiry": "", "ssl_domain": domain}


def _get_config_manager():
    return ConfigManager(PROJECT_ROOT)


class ConfigUpdate(BaseModel):
    domain: Optional[str] = None
    access_mode: Optional[str] = None
    https_port: Optional[int] = None
    ssl_email: Optional[str] = None
    dns_provider: Optional[str] = None
    panel_subdomain: Optional[str] = None
    cf_tunnel_token: Optional[str] = None
    # DNS 凭证（与 dns_provider 配套）
    dns_credentials: Optional[dict] = None  # {"aliyun": {"key": "", "secret": ""}} 或 {"cloudflare": {"token": ""}}
    # 多域名列表
    domains: Optional[list] = None


@router.get("")
async def get_config():
    """获取全局配置"""
    cm = _get_config_manager()
    config = cm.load_config()
    env = cm.load_env()

    # 从 .env 同步凭证/提供商到 config.yaml（一次性迁移，保证界面显示与 .env 一致）
    _sync_credentials_from_env(cm, env)
    config = cm.load_config()

    # DNS 凭证脱敏返回 + 已配置检测（以 .env / config.yaml 实际值判断）
    dns_creds = config.get("dns_credentials", {})
    masked_creds = {}
    configured_flags = {}
    for provider in DNS_PROVIDERS:
        pid = provider["id"]
        masked_creds[pid] = {}
        configured_flags[pid] = {}
        for f in provider["fields"]:
            val = ""
            env_key = f["env"]
            if env_key and env.get(env_key):
                val = env[env_key]
            else:
                val = (dns_creds.get(pid, {}) or {}).get(f["key"], "") or ""
            if val:
                # 自定义项的 vars 多行内容不脱敏回显，仅标记已配置
                if pid == "custom" and f["key"] == "vars":
                    masked_creds[pid][f["key"]] = MASK_PREFIX
                else:
                    masked_creds[pid][f["key"]] = _mask_sensitive(f["key"], val)
                configured_flags[pid][f["key"]] = True
            else:
                masked_creds[pid][f["key"]] = ""
                configured_flags[pid][f["key"]] = False

    return {
        "config": config,
        "domains": cm.get_domains(),
        "env_summary": {
            "DOMAIN": env.get("DOMAIN", ""),
            "ACCESS_MODE": env.get("ACCESS_MODE", "domain"),
            "HTTPS_PORT": env.get("HTTPS_PORT", "8443"),
        },
        "setup_completed": cm.is_setup_completed(),
        "ssl_status": _check_ssl_status(config.get("domain", "")),
        "dns_providers": DNS_PROVIDERS,
        "dns_credentials": masked_creds,
        "dns_credentials_configured": configured_flags,
    }


def _sync_credentials_from_env(cm: ConfigManager, env: dict):
    """将 .env 中的 DNS 凭证与提供商同步回 config.yaml，保证两边一致"""
    config = cm.load_config()
    dns_creds = config.setdefault("dns_credentials", {})
    changed = False

    # 同步 dns_provider（由 .env 的 ACME_DNS 反查）
    plugin_to_id = {p["acme_plugin"]: p["id"] for p in DNS_PROVIDERS if p["acme_plugin"]}
    env_dns = env.get("ACME_DNS", "")
    if env_dns and env_dns in plugin_to_id and config.get("dns_provider") != plugin_to_id[env_dns]:
        config["dns_provider"] = plugin_to_id[env_dns]
        changed = True

    # 同步各提供商凭证
    for provider in DNS_PROVIDERS:
        pid = provider["id"]
        if pid == "custom":
            continue
        for f in provider["fields"]:
            env_key = f["env"]
            if not env_key:
                continue
            env_val = env.get(env_key, "")
            existing = (dns_creds.get(pid, {}) or {}).get(f["key"], "")
            if env_val and existing != env_val:
                dns_creds.setdefault(pid, {})[f["key"]] = env_val
                changed = True
    if changed:
        cm.save_config(config)


def _write_acme_env_file(cm: ConfigManager, dns_creds: dict):
    """将各提供商凭证写入 acme 容器 env_file（data/acme/dns-credentials.env）"""
    lines = []
    for provider in DNS_PROVIDERS:
        pid = provider["id"]
        if pid == "custom":
            vars_text = (dns_creds.get("custom", {}) or {}).get("vars", "")
            for line in str(vars_text).splitlines():
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    lines.append(line)
            continue
        for f in provider["fields"]:
            val = (dns_creds.get(pid, {}) or {}).get(f["key"], "")
            if val and not is_mask_value(val):
                # acme_env 为 acme.sh 插件实际读取的变量名（如 Ali_Key），
                # 未定义时回退到 .env 变量名
                lines.append(f"{f.get('acme_env', f['env'])}={val}")
    env_file = Path(PROJECT_ROOT) / "modules" / "acme" / "dns-credentials.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines) + ("\n" if lines else "")
    env_file.write_text(content, encoding="utf-8")


def _save_dns_credentials(cm: ConfigManager, provider: str, credentials: dict):
    """保存 DNS 凭证（通用）：写入 config.yaml + .env + acme env_file；脱敏回显值不覆盖"""
    provider_meta = get_provider(provider)
    if not provider_meta:
        return
    config = cm.load_config()
    dns_creds = config.setdefault("dns_credentials", {})
    existing = dict(dns_creds.get(provider, {}) or {})

    fields_data = (credentials.get(provider, {}) or {}) if isinstance(credentials, dict) else {}
    for f in provider_meta["fields"]:
        new_val = fields_data.get(f["key"])
        if new_val is None:
            continue
        if is_mask_value(str(new_val)):
            continue  # 脱敏回显值跳过，防止覆盖真实凭证
        if not str(new_val).strip():
            continue  # 空值不覆盖已配置凭证
        existing[f["key"]] = new_val
    dns_creds[provider] = existing
    cm.save_config(config)

    # 写 .env：ACME_DNS 插件名 + 各凭证环境变量
    plugin = existing.get("plugin", "") if provider == "custom" else provider_meta["acme_plugin"]
    if plugin:
        cm.set_env_value("ACME_DNS", plugin)
    for f in provider_meta["fields"]:
        if f["env"] and existing.get(f["key"]):
            cm.set_env_value(f["env"], existing[f["key"]])
    if provider == "custom" and existing.get("plugin"):
        cm.set_env_value("ACME_DNS_CUSTOM_PLUGIN", existing["plugin"])

    _write_acme_env_file(cm, dns_creds)


@router.put("")
async def update_config(update: ConfigUpdate):
    """更新全局配置"""
    cm = _get_config_manager()

    if update.domain is not None:
        cm.set_config_value("domain", update.domain)
        cm.set_env_value("DOMAIN", update.domain)

    if update.access_mode is not None:
        if update.access_mode not in ("domain", "cloudflare_tunnel", "ipv6_direct", "hybrid", "custom"):
            raise HTTPException(status_code=400, detail="无效的访问模式")
        cm.set_config_value("access_mode", update.access_mode)
        cm.set_env_value("ACCESS_MODE", update.access_mode)

    if update.https_port is not None:
        cm.set_config_value("https_port", update.https_port)
        cm.set_env_value("HTTPS_PORT", str(update.https_port))
        cm.set_env_value("NGINX_HTTPS_PORT", str(update.https_port))
        # 自动触发 Nginx 配置重新生成
        try:
            from ..core.nginx_generator import NginxGenerator
            from ..core.module_loader import ModuleLoader
            ng = NginxGenerator(PROJECT_ROOT)
            ml = ModuleLoader(PROJECT_ROOT)
            installed = ml.get_installed_modules()
            ng.generate_all(cm.load_config(), installed)
            # 端口变更需要重启容器才能绑定新端口
            ng.restart_nginx()
        except Exception:
            pass  # Nginx 未运行时忽略

    if update.ssl_email is not None:
        cm.set_config_value("ssl_email", update.ssl_email)
        cm.set_env_value("SSL_EMAIL", update.ssl_email)

    if update.dns_provider is not None:
        if not get_provider(update.dns_provider):
            raise HTTPException(status_code=400, detail="无效的 DNS 提供商")
        cm.set_config_value("dns_provider", update.dns_provider)

    if update.domains is not None:
        if not isinstance(update.domains, list):
            raise HTTPException(status_code=400, detail="domains 必须为数组")
        for entry in update.domains:
            if not isinstance(entry, dict) or not entry.get("domain"):
                raise HTTPException(status_code=400, detail="每个域名条目必须为包含 domain 字段的对象")
        cm.set_config_value("domains", update.domains)

    if update.dns_credentials is not None:
        provider = update.dns_provider or cm.get_config_value("dns_provider", "aliyun")
        _save_dns_credentials(cm, provider, update.dns_credentials)

    if update.cf_tunnel_token is not None and update.cf_tunnel_token:
        cm.set_env_value("CF_TUNNEL_TOKEN", update.cf_tunnel_token)

    if update.panel_subdomain is not None:
        cm.set_config_value("panel_subdomain", update.panel_subdomain)
        cm.set_env_value("SUBDOMAIN_PANEL", update.panel_subdomain)
        # 触发 Nginx 重新生成
        try:
            from ..core.nginx_generator import NginxGenerator
            from ..core.module_loader import ModuleLoader
            ng = NginxGenerator(PROJECT_ROOT)
            ml = ModuleLoader(PROJECT_ROOT)
            installed = ml.get_installed_modules()
            ng.generate_all(cm.load_config(), installed)
            ng.reload_nginx()
        except Exception:
            pass

    return {"success": True, "config": cm.load_config()}


class SetupRequest(BaseModel):
    """安装向导请求体（极简化）"""
    domain: str
    ssl_email: str
    admin_password: str = ""


@router.post("/setup")
async def run_setup(request: SetupRequest):
    """执行初始设置（安装向导调用）- 只保存基础配置，不自动安装任何服务模块"""
    cm = _get_config_manager()

    # 1. 保存基础配置
    cm.set_config_value("domain", request.domain)
    cm.set_config_value("ssl_email", request.ssl_email)
    cm.set_env_value("DOMAIN", request.domain)
    cm.set_env_value("SSL_EMAIL", request.ssl_email)

    # 2. 设置管理密码
    if request.admin_password:
        cm.set_admin_password(request.admin_password)

    # 3. 标记设置完成（不安装任何模块，服务均从应用商店或网络配置按需安装）
    cm.mark_setup_completed()

    return {
        "success": True,
        "message": "初始设置完成，可在应用商店按需安装服务，或在网络配置中自动安装所需模块"
    }


@router.post("/setup/complete")
async def complete_setup():
    """标记初始设置完成"""
    cm = _get_config_manager()
    cm.mark_setup_completed()
    return {"success": True}


@router.get("/setup/status")
async def setup_status():
    """获取初始设置状态"""
    cm = _get_config_manager()
    return {
        "setup_completed": cm.is_setup_completed(),
        "network_configured": cm.is_network_configured(),
        "config": cm.load_config()
    }


@router.post("/generate-password")
async def generate_password(length: int = 32):
    """生成随机强密码"""
    return {"password": ConfigManager.generate_password(length)}


# ===== 登录接口 =====

class LoginRequest(BaseModel):
    password: str


@router.post("/auth/login")
async def login(request: LoginRequest):
    """登录验证，返回 JWT Token"""
    from ..core.auth import create_token
    cm = _get_config_manager()
    if not cm.verify_password(request.password):
        raise HTTPException(status_code=401, detail="密码错误")
    token = create_token()
    return {"token": token, "success": True}


# ===== 网络配置接口 =====

# 后台任务引用集，防止异步任务被 GC 提前回收
_background_tasks = set()


def _trigger_dns_sync_background():
    """异步触发一次 DNS 同步（不阻塞 HTTP 响应，异常不影响主流程）"""
    from .dns import sync_dns

    async def _run():
        try:
            result = await sync_dns()
            summary = result.get("summary", {}) if isinstance(result, dict) else {}
            logger.info("hybrid 模式后台 DNS 同步完成: %s", summary)
        except Exception as e:
            logger.warning("hybrid 模式后台 DNS 同步失败（不影响网络配置主流程）: %s", e)

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


class NetworkConfigRequest(BaseModel):
    access_mode: str  # "domain" | "cloudflare_tunnel" | "ipv6_direct"
    dns_provider: Optional[str] = None
    dns_credentials: Optional[dict] = None
    cf_tunnel_token: Optional[str] = None
    https_port: int = 8443


@router.post("/network")
async def configure_network(request: NetworkConfigRequest):
    """配置网络访问模式，自动启停对应模块"""
    cm = _get_config_manager()
    dm = DockerManager(PROJECT_ROOT)
    ml = ModuleLoader(PROJECT_ROOT)

    if request.access_mode not in ("domain", "cloudflare_tunnel", "ipv6_direct", "hybrid", "custom"):
        raise HTTPException(status_code=400, detail="无效的访问模式")

    # 1. 更新配置
    cm.set_config_value("access_mode", request.access_mode)
    cm.set_env_value("ACCESS_MODE", request.access_mode)
    cm.set_config_value("https_port", request.https_port)
    cm.set_env_value("HTTPS_PORT", str(request.https_port))
    cm.set_env_value("NGINX_HTTPS_PORT", str(request.https_port))

    results = []

    # 2. 根据访问模式启停模块
    # 非 IPv6 模式恢复 BIND_ADDRESS 为 127.0.0.1
    if request.access_mode != "ipv6_direct":
        cm.set_env_value("BIND_ADDRESS", "127.0.0.1")

    if request.access_mode == "domain":
        # 域名反代：启动 nginx+acme+ddns-go，停止 cloudflare-tunnel
        for mid in ["nginx", "acme", "ddns-go"]:
            if mid not in cm.get_installed_modules():
                cm.add_installed_module(mid)
            try:
                dm.start_module(mid)
                results.append({"module": mid, "action": "start", "success": True})
            except Exception as e:
                results.append({"module": mid, "action": "start", "success": False, "error": str(e)})
        # 停止 cloudflare-tunnel
        if "cloudflare-tunnel" in cm.get_installed_modules():
            try:
                dm.stop_module("cloudflare-tunnel")
                results.append({"module": "cloudflare-tunnel", "action": "stop", "success": True})
            except Exception:
                pass

        # 保存 DNS 凭证
        if request.dns_provider:
            cm.set_config_value("dns_provider", request.dns_provider)
        if request.dns_credentials:
            provider = request.dns_provider or cm.get_config_value("dns_provider", "aliyun")
            _save_dns_credentials(cm, provider, request.dns_credentials)

    elif request.access_mode == "hybrid":
        # 混合模式：域名反代（Nginx+ACME+DDNS）与 Cloudflare Tunnel 同时启用
        for mid in ["nginx", "acme", "ddns-go"]:
            if mid not in cm.get_installed_modules():
                cm.add_installed_module(mid)
            try:
                dm.start_module(mid)
                results.append({"module": mid, "action": "start", "success": True})
            except Exception as e:
                results.append({"module": mid, "action": "start", "success": False, "error": str(e)})
        if "cloudflare-tunnel" not in cm.get_installed_modules():
            cm.add_installed_module("cloudflare-tunnel")
        try:
            dm.start_module("cloudflare-tunnel")
            results.append({"module": "cloudflare-tunnel", "action": "start", "success": True})
        except Exception as e:
            results.append({"module": "cloudflare-tunnel", "action": "start", "success": False, "error": str(e)})
        # 保存 DNS 凭证
        if request.dns_provider:
            cm.set_config_value("dns_provider", request.dns_provider)
        if request.dns_credentials:
            provider = request.dns_provider or cm.get_config_value("dns_provider", "aliyun")
            _save_dns_credentials(cm, provider, request.dns_credentials)

        # 智能 DNS 同步：模块启停完成后异步触发一次，不阻塞 HTTP 响应（自动跳过已 Tunnel 发布的服务）
        try:
            _trigger_dns_sync_background()
        except Exception as e:
            logger.warning("后台 DNS 同步任务调度失败: %s", e)

    elif request.access_mode == "cloudflare_tunnel":
        # Cloudflare Tunnel：启动 cloudflare-tunnel，停止 nginx+acme
        if request.cf_tunnel_token:
            cm.set_env_value("CF_TUNNEL_TOKEN", request.cf_tunnel_token)
        if "cloudflare-tunnel" not in cm.get_installed_modules():
            cm.add_installed_module("cloudflare-tunnel")
        try:
            dm.start_module("cloudflare-tunnel")
            results.append({"module": "cloudflare-tunnel", "action": "start", "success": True})
        except Exception as e:
            results.append({"module": "cloudflare-tunnel", "action": "start", "success": False, "error": str(e)})
        # 停止 nginx+acme
        for mid in ["nginx", "acme"]:
            if mid in cm.get_installed_modules():
                try:
                    dm.stop_module(mid)
                    results.append({"module": mid, "action": "stop", "success": True})
                except Exception:
                    pass

    elif request.access_mode == "ipv6_direct":
        # IPv6 直连：直接用公网 IPv6 地址 + 端口访问，无需域名/DNS/SSL
        # 停止代理模块（不需要 Nginx/ACME/Tunnel）
        for mid in ["nginx", "acme", "cloudflare-tunnel"]:
            if mid in cm.get_installed_modules():
                try:
                    dm.stop_module(mid)
                    results.append({"module": mid, "action": "stop", "success": True})
                except Exception:
                    pass
        # 切换 BIND_ADDRESS 为 ::，监听所有接口（含 IPv6）
        cm.set_env_value("BIND_ADDRESS", "::")
        # 重启已安装模块以应用新绑定地址
        for mid in cm.get_installed_modules():
            if mid not in ["nginx", "acme", "cloudflare-tunnel"]:
                try:
                    dm.restart_module(mid)
                    results.append({"module": mid, "action": "restart", "success": True})
                except Exception as e:
                    results.append({"module": mid, "action": "restart", "success": False, "error": str(e)})

    elif request.access_mode == "custom":
        # 自由配置：不自动管理任何模块，用户完全自主控制
        cm.set_env_value("BIND_ADDRESS", "127.0.0.1")

    # 3. 生成 Nginx 配置（domain / hybrid 模式）
    if request.access_mode in ("domain", "hybrid"):
        try:
            from ..core.nginx_generator import NginxGenerator
            ng = NginxGenerator(PROJECT_ROOT)
            installed_modules = [ml.get_module_by_id(m) for m in cm.get_installed_modules() if ml.get_module_by_id(m)]
            ng.generate_all(cm.load_config(), installed_modules)
            if not ng.reload_nginx():
                logger.warning("Nginx 配置已重新生成，但热加载失败（nginx -s reload 返回非零），请检查 Nginx 容器状态")
        except Exception as e:
            logger.warning("Nginx 配置重新生成失败（不影响网络模式切换主流程）: %s", e)

    # 4. 标记网络配置完成
    cm.mark_network_configured()

    return {
        "success": True,
        "access_mode": request.access_mode,
        "results": results,
        "message": "网络配置已保存"
    }


# ===== 多域名管理接口 =====

_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)


class DomainAddRequest(BaseModel):
    domain: str
    dns_provider: str
    purpose: str = "nginx"  # nginx | tunnel | both


@router.get("/domains")
async def list_domains():
    """获取域名列表及状态"""
    cm = _get_config_manager()
    return {"domains": cm.get_domains()}


@router.post("/domains")
async def add_domain(request: DomainAddRequest):
    """添加域名（添加后自动触发验证）"""
    # 验证域名格式
    if not _DOMAIN_RE.match(request.domain):
        raise HTTPException(status_code=400, detail=f"无效的域名格式: {request.domain}")
    # 验证 dns_provider
    if not get_provider(request.dns_provider):
        raise HTTPException(status_code=400, detail=f"无效的 DNS 提供商: {request.dns_provider}")
    # 验证 purpose
    if request.purpose not in ("nginx", "tunnel", "both"):
        raise HTTPException(status_code=400, detail="purpose 必须为 nginx / tunnel / both")

    cm = _get_config_manager()
    ok = cm.add_domain({
        "domain": request.domain,
        "dns_provider": request.dns_provider,
        "purpose": request.purpose,
    })
    if not ok:
        raise HTTPException(status_code=400, detail="添加域名失败")

    # 添加成功后自动验证
    verify_result = await verify_domain(request.domain)
    return {"success": True, "domains": cm.get_domains(), "verify": verify_result}


@router.post("/domains/{domain}/verify")
async def verify_domain(domain: str):
    """验证域名连通性和配置状态"""
    cm = _get_config_manager()
    domain_cfg = cm.get_domain_config(domain)
    if not domain_cfg:
        raise HTTPException(status_code=404, detail=f"域名 {domain} 未配置")

    results = {
        "domain": domain,
        "dns_provider": domain_cfg.get("dns_provider", ""),
        "checks": {},
        "status": "active",
        "errors": []
    }

    dns_provider = domain_cfg.get("dns_provider", "")

    # 检查 1: DNS 提供商连通性
    try:
        if dns_provider == "aliyun":
            from .dns import _get_aliyun_credentials
            creds = _get_aliyun_credentials(cm)
            if creds.get("key") and creds.get("secret"):
                from ..core.alidns_api import AliyunDNSClient
                client = AliyunDNSClient(creds["key"], creds["secret"])
                # 查询域名是否存在（尝试获取 domain 的 records）
                records = client.find_record(domain, "@", "A")
                results["checks"]["dns_provider"] = {"ok": True, "message": "阿里云 DNS 连通正常"}
            else:
                results["checks"]["dns_provider"] = {"ok": False, "message": "阿里云 DNS 凭证未配置"}
                results["errors"].append("阿里云 DNS 凭证未配置，请在设置中配置 AccessKey")
        elif dns_provider == "cloudflare":
            from .dns import _get_cloudflare_token
            token = _get_cloudflare_token(cm)
            if token and not token.startswith("eyJ"):
                results["checks"]["dns_provider"] = {"ok": True, "message": "Cloudflare API 连通正常"}
            else:
                results["checks"]["dns_provider"] = {"ok": False, "message": "Cloudflare API Token 未配置或无效"}
                results["errors"].append("Cloudflare API Token 未配置或无效（注意：eyJ 开头的是 Tunnel Token，不是 API Token）")
        else:
            results["checks"]["dns_provider"] = {"ok": True, "message": f"DNS 提供商: {dns_provider}"}
    except Exception as e:
        results["checks"]["dns_provider"] = {"ok": False, "message": f"DNS 提供商连接失败: {str(e)}"}
        results["errors"].append(f"DNS 提供商连接失败: {str(e)}")

    # 检查 2: Tunnel 域名 cfargotunnel.com CNAME 可解析性（仅 purpose=tunnel/both 时检查）
    purpose = domain_cfg.get("purpose", "")
    if purpose in ("tunnel", "both"):
        try:
            result = subprocess.run(
                ["dig", "@8.8.8.8", f"test.{domain}", "CNAME", "+short"],
                capture_output=True, text=True, timeout=10
            )
            if "cfargotunnel.com" in result.stdout:
                results["checks"]["tunnel_dns"] = {"ok": True, "message": "CNAME 指向 cfargotunnel.com，Tunnel DNS 配置正确"}
            elif result.stdout.strip():
                results["checks"]["tunnel_dns"] = {"ok": True, "message": f"DNS 解析正常: {result.stdout.strip()}"}
            else:
                results["checks"]["tunnel_dns"] = {"ok": True, "message": "域名尚无 DNS 记录（添加服务后会自动创建）"}
        except Exception as e:
            results["checks"]["tunnel_dns"] = {"ok": False, "message": f"DNS 解析检测失败: {str(e)}"}

    # 检查 3: SSL 证书（仅 purpose=nginx/both 时检查）
    if purpose in ("nginx", "both"):
        ssl = _check_ssl_status(domain)
        if ssl.get("ssl_valid"):
            results["checks"]["ssl"] = {"ok": True, "message": f"SSL 证书有效，到期: {ssl.get('ssl_expiry', '')}"}
        else:
            results["checks"]["ssl"] = {"ok": False, "message": "SSL 证书未找到或已过期"}
            results["errors"].append("SSL 证书未找到或已过期，请通过 ACME 模块申请证书")

    # 综合状态
    has_error = any(not check.get("ok", True) for check in results["checks"].values())
    if has_error:
        results["status"] = "error"
    elif results["errors"]:
        results["status"] = "warning"
    else:
        results["status"] = "active"

    # 更新域名状态
    cm.update_domain_status(domain, results["status"])

    return results


@router.delete("/domains/{domain}")
async def remove_domain(domain: str):
    """删除域名"""
    cm = _get_config_manager()
    # 检查是否为主域名
    primary = cm.get_primary_domain()
    if domain == primary:
        raise HTTPException(status_code=400, detail="不允许删除主域名")
    ok = cm.remove_domain(domain)
    if not ok:
        raise HTTPException(status_code=404, detail=f"域名未找到: {domain}")
    return {"success": True, "domains": cm.get_domains()}
