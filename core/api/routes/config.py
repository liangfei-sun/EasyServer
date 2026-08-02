"""
EasyServer Config API
全局配置读写接口
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from ..core.config_manager import ConfigManager
from ..core.docker_manager import DockerManager
from ..core.module_loader import ModuleLoader
from ..core.nginx_generator import NginxGenerator
import os
import subprocess
from pathlib import Path
from datetime import datetime

router = APIRouter(prefix="/api/config", tags=["config"])

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
    # DNS 凭证（与 dns_provider 配套）
    dns_credentials: Optional[dict] = None  # {"aliyun": {"key": "", "secret": ""}} 或 {"cloudflare": {"token": ""}}


@router.get("")
async def get_config():
    """获取全局配置"""
    cm = _get_config_manager()
    config = cm.load_config()
    env = cm.load_env()

    # NOTE: env_summary 当前只返回 DOMAIN、ACCESS_MODE、HTTPS_PORT 三个非敏感字段，
    # 如果未来扩展返回更多字段，需使用 _mask_sensitive() 对敏感字段进行脱敏。
    # DNS 凭证脱敏返回
    dns_creds = config.get("dns_credentials", {})
    masked_creds = {}
    for provider, creds in dns_creds.items():
        masked_creds[provider] = {}
        for k, v in creds.items():
            masked_creds[provider][k] = _mask_sensitive(k, v) if v else ""

    return {
        "config": config,
        "env_summary": {
            "DOMAIN": env.get("DOMAIN", ""),
            "ACCESS_MODE": env.get("ACCESS_MODE", "domain"),
            "HTTPS_PORT": env.get("HTTPS_PORT", "8443"),
        },
        "setup_completed": cm.is_setup_completed(),
        "ssl_status": _check_ssl_status(config.get("domain", "")),
        "dns_credentials": masked_creds,
    }


@router.put("")
async def update_config(update: ConfigUpdate):
    """更新全局配置"""
    cm = _get_config_manager()

    if update.domain is not None:
        cm.set_config_value("domain", update.domain)
        cm.set_env_value("DOMAIN", update.domain)

    if update.access_mode is not None:
        if update.access_mode not in ("domain", "cloudflare_tunnel", "ipv6_direct", "hybrid"):
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
        if update.dns_provider not in ("aliyun", "cloudflare"):
            raise HTTPException(status_code=400, detail="无效的 DNS 提供商，支持: aliyun, cloudflare")
        cm.set_config_value("dns_provider", update.dns_provider)
        # 同步写入 .env 供 ACME 模块使用
        acme_dns_map = {"aliyun": "dns_ali", "cloudflare": "dns_cf"}
        cm.set_env_value("ACME_DNS", acme_dns_map.get(update.dns_provider, "dns_ali"))

    if update.dns_credentials is not None:
        provider = update.dns_provider or cm.get_config_value("dns_provider", "aliyun")
        existing = cm.get_config_value("dns_credentials", {})
        if provider == "aliyun" and "aliyun" in update.dns_credentials:
            ali = update.dns_credentials["aliyun"]
            existing["aliyun"] = {
                "key": ali.get("key", existing.get("aliyun", {}).get("key", "")),
                "secret": ali.get("secret", existing.get("aliyun", {}).get("secret", ""))
            }
            # 同步写入 .env
            if ali.get("key"):
                cm.set_env_value("ACME_ALI_KEY", ali["key"])
            if ali.get("secret"):
                cm.set_env_value("ACME_ALI_SECRET", ali["secret"])
        elif provider == "cloudflare" and "cloudflare" in update.dns_credentials:
            cf = update.dns_credentials["cloudflare"]
            existing["cloudflare"] = {
                "token": cf.get("token", existing.get("cloudflare", {}).get("token", ""))
            }
            if cf.get("token"):
                cm.set_env_value("ACME_CF_TOKEN", cf["token"])
        cm.set_config_value("dns_credentials", existing)

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
    """执行初始设置（安装向导调用）- 极简模式，只装核心模块"""
    cm = _get_config_manager()
    dm = DockerManager(PROJECT_ROOT)
    ml = ModuleLoader(PROJECT_ROOT)

    # 1. 保存基础配置
    cm.set_config_value("domain", request.domain)
    cm.set_config_value("ssl_email", request.ssl_email)
    cm.set_env_value("DOMAIN", request.domain)
    cm.set_env_value("SSL_EMAIL", request.ssl_email)

    # 2. 设置管理密码
    if request.admin_password:
        cm.set_admin_password(request.admin_password)

    # 3. 安装核心模块（nginx + acme + ddns-go）
    core_modules = ["nginx", "acme", "ddns-go"]
    install_results = []

    for module_id in core_modules:
        metadata = ml.get_module_by_id(module_id)
        if not metadata:
            install_results.append({"module": module_id, "success": False, "error": "模块不存在"})
            continue
        try:
            cm.add_installed_module(module_id)
            dm.start_module(module_id)
            install_results.append({"module": module_id, "success": True})
        except Exception as e:
            install_results.append({"module": module_id, "success": False, "error": str(e)})

    # 4. 生成 Nginx 配置
    try:
        ng = NginxGenerator(PROJECT_ROOT)
        installed_modules = [ml.get_module_by_id(m) for m in cm.get_installed_modules() if ml.get_module_by_id(m)]
        ng.generate_all(cm.load_config(), installed_modules)
    except Exception:
        pass

    # 5. 标记设置完成（网络未配置）
    cm.mark_setup_completed()

    return {
        "success": True,
        "install_results": install_results,
        "message": "初始设置完成，请在管理面板中配置网络访问"
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

    if request.access_mode not in ("domain", "cloudflare_tunnel", "ipv6_direct", "hybrid"):
        raise HTTPException(status_code=400, detail="无效的访问模式")

    # 1. 更新配置
    cm.set_config_value("access_mode", request.access_mode)
    cm.set_env_value("ACCESS_MODE", request.access_mode)
    cm.set_config_value("https_port", request.https_port)
    cm.set_env_value("HTTPS_PORT", str(request.https_port))
    cm.set_env_value("NGINX_HTTPS_PORT", str(request.https_port))

    results = []

    # 2. 根据访问模式启停模块
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
            acme_dns_map = {"aliyun": "dns_ali", "cloudflare": "dns_cf"}
            cm.set_env_value("ACME_DNS", acme_dns_map.get(request.dns_provider, "dns_ali"))
        if request.dns_credentials:
            provider = request.dns_provider or cm.get_config_value("dns_provider", "aliyun")
            existing = cm.get_config_value("dns_credentials", {})
            if provider == "aliyun" and "aliyun" in request.dns_credentials:
                ali = request.dns_credentials["aliyun"]
                existing["aliyun"] = {"key": ali.get("key", ""), "secret": ali.get("secret", "")}
                if ali.get("key"): cm.set_env_value("ACME_ALI_KEY", ali["key"])
                if ali.get("secret"): cm.set_env_value("ACME_ALI_SECRET", ali["secret"])
            elif provider == "cloudflare" and "cloudflare" in request.dns_credentials:
                cf = request.dns_credentials["cloudflare"]
                existing["cloudflare"] = {"token": cf.get("token", "")}
                if cf.get("token"): cm.set_env_value("ACME_CF_TOKEN", cf["token"])
            cm.set_config_value("dns_credentials", existing)

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
        # IPv6 直连：停止 nginx+acme+cloudflare-tunnel
        for mid in ["nginx", "acme", "cloudflare-tunnel"]:
            if mid in cm.get_installed_modules():
                try:
                    dm.stop_module(mid)
                    results.append({"module": mid, "action": "stop", "success": True})
                except Exception:
                    pass

    # 3. 生成 Nginx 配置（仅 domain 模式）
    if request.access_mode == "domain":
        try:
            ng = NginxGenerator(PROJECT_ROOT)
            installed_modules = [ml.get_module_by_id(m) for m in cm.get_installed_modules() if ml.get_module_by_id(m)]
            ng.generate_all(cm.load_config(), installed_modules)
            ng.reload_nginx()
        except Exception:
            pass

    # 4. 标记网络配置完成
    cm.mark_network_configured()

    return {
        "success": True,
        "access_mode": request.access_mode,
        "results": results,
        "message": "网络配置已保存"
    }
