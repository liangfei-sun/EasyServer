"""
EasyServer Config API
全局配置读写、安装向导、登录认证、SSL 检测、系统诊断
"""
from fastapi import APIRouter, HTTPException, Request, Request
from pydantic import BaseModel
from typing import Optional
import asyncio
import subprocess
import logging
from pathlib import Path
from datetime import datetime

from ..core.config_manager import ConfigManager
from ..core.deps import PROJECT_ROOT, get_config_manager
from ..core.dns_providers import DNS_PROVIDERS, get_provider, is_mask_value, MASK_PREFIX
from ..core.nginx_utils import async_regenerate_nginx_config

router = APIRouter(prefix="/api/config", tags=["config"])

logger = logging.getLogger("easyserver.config")

# ===== 工具函数 =====

SENSITIVE_KEYS = {"password", "secret", "key", "token", "ali_key", "ali_secret",
                  "cf_tunnel_token", "api_key", "secret_key"}

def _mask_sensitive(key: str, value: str) -> str:
    """对敏感字段脱敏，只显示后4位"""
    key_lower = key.lower()
    if any(s in key_lower for s in SENSITIVE_KEYS) and value and len(value) > 4:
        return "***" + value[-4:]
    return value

async def _check_ssl_status(domain: str) -> dict:
    """检测 SSL 证书状态"""
    if not domain:
        return {"ssl_valid": False, "ssl_expiry": "", "ssl_domain": ""}
    cert_path = Path(PROJECT_ROOT) / "modules" / "nginx" / "ssl" / domain / "fullchain.cer"
    if not cert_path.exists():
        return {"ssl_valid": False, "ssl_expiry": "", "ssl_domain": domain}
    try:
        result = await asyncio.to_thread(
            subprocess.run,
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

# ===== Pydantic 模型 =====

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

class SetupRequest(BaseModel):
    """安装向导请求体（极简化）"""
    domain: str
    ssl_email: str
    admin_password: str = ""

class LoginRequest(BaseModel):
    password: str

# ===== DNS 凭证管理 =====

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

# ===== 全局配置接口 =====

@router.get("")
async def get_config():
    """获取全局配置"""
    cm = get_config_manager()
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
        "ssl_status": await _check_ssl_status(config.get("domain", "")),
        "dns_providers": DNS_PROVIDERS,
        "dns_credentials": masked_creds,
        "dns_credentials_configured": configured_flags,
    }

@router.put("")
async def update_config(update: ConfigUpdate):
    """更新全局配置"""
    cm = get_config_manager()

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
        # 自动触发 Nginx 配置重新生成（端口变更需要重启容器）
        await async_regenerate_nginx_config(cm, restart=True)

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
        await async_regenerate_nginx_config(cm)

    return {"success": True, "config": cm.load_config()}

# ===== 安装向导 =====

@router.post("/setup")
async def run_setup(request: SetupRequest):
    """执行初始设置（安装向导调用）- 只保存基础配置，不自动安装任何服务模块"""
    cm = get_config_manager()

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
    cm = get_config_manager()
    cm.mark_setup_completed()
    return {"success": True}

@router.get("/setup/status")
async def setup_status():
    """获取初始设置状态"""
    cm = get_config_manager()
    result = {
        "setup_completed": cm.is_setup_completed(),
        "network_configured": cm.is_network_configured(),
    }
    if not cm.is_setup_completed():
        result["config"] = cm.load_config()
    return result

@router.post("/generate-password")
async def generate_password(length: int = 32):
    """生成随机强密码"""
    return {"password": ConfigManager.generate_password(length)}

# ===== 登录接口 =====

@router.post("/auth/login")
async def login(request: Request, body: LoginRequest):
    """登录验证，返回 JWT Token"""
    from ..core.auth import create_token, check_login_rate_limit, record_login_attempt, reset_login_rate_limit
    client_ip = request.client.host if request.client else "unknown"
    if not check_login_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail="登录尝试过于频繁，请稍后再试")
    record_login_attempt(client_ip)
    cm = get_config_manager()
    if not cm.verify_password(body.password):
        raise HTTPException(status_code=401, detail="密码错误")
    reset_login_rate_limit(client_ip)
    token = create_token()
    return {"token": token, "success": True}

# ===== 系统诊断接口 =====

@router.get("/diagnostics")
async def get_diagnostics():
    """系统诊断：检测域名、端口、SSL、IP 等配置状态，返回问题警告"""
    cm = get_config_manager()
    config = cm.load_config()
    env = cm.load_env()

    domain = env.get("DOMAIN", "") or config.get("domain", "")
    https_port = int(env.get("HTTPS_PORT") or config.get("https_port", 8443))
    access_mode = env.get("ACCESS_MODE") or config.get("access_mode", "domain")

    # 公网 IP 检测
    from ..core.ip_utils import get_public_ipv4, get_public_ipv6
    ipv4 = get_public_ipv4()
    ipv6 = get_public_ipv6()

    # SSL 检测
    ssl = await _check_ssl_status(domain)

    # 收集警告
    warnings = []
    if not domain:
        warnings.append({"field": "domain", "message": "未配置域名"})
    if not ipv4 and not ipv6:
        warnings.append({"field": "public_ip", "message": "未检测到公网 IP 地址"})
    if domain and access_mode in ("domain", "hybrid"):
        if not ssl.get("ssl_valid"):
            warnings.append({"field": "ssl", "message": f"域名 {domain} 的 SSL 证书未配置或已过期"})

    return {
        "domain": domain,
        "public_ipv4": ipv4,
        "public_ipv6": ipv6,
        "https_port": https_port,
        "access_mode": access_mode,
        "ssl_valid": ssl.get("ssl_valid", False),
        "ssl_expiry": ssl.get("ssl_expiry", ""),
        "warnings": warnings,
    }
