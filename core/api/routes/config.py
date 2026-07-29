"""
EasyServer Config API
全局配置读写接口
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from ..core.config_manager import ConfigManager
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


@router.get("")
async def get_config():
    """获取全局配置"""
    cm = _get_config_manager()
    config = cm.load_config()
    env = cm.load_env()

    # NOTE: env_summary 当前只返回 DOMAIN、ACCESS_MODE、HTTPS_PORT 三个非敏感字段，
    # 如果未来扩展返回更多字段，需使用 _mask_sensitive() 对敏感字段进行脱敏。
    return {
        "config": config,
        "env_summary": {
            "DOMAIN": env.get("DOMAIN", ""),
            "ACCESS_MODE": env.get("ACCESS_MODE", "domain"),
            "HTTPS_PORT": env.get("HTTPS_PORT", "8443"),
        },
        "setup_completed": cm.is_setup_completed(),
        "ssl_status": _check_ssl_status(config.get("domain", ""))
    }


@router.put("")
async def update_config(update: ConfigUpdate):
    """更新全局配置"""
    cm = _get_config_manager()

    if update.domain is not None:
        cm.set_config_value("domain", update.domain)
        cm.set_env_value("DOMAIN", update.domain)

    if update.access_mode is not None:
        if update.access_mode not in ("domain", "ipv6_direct", "hybrid"):
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
            ng.reload_nginx()
        except Exception:
            pass  # Nginx 未运行时忽略

    if update.ssl_email is not None:
        cm.set_config_value("ssl_email", update.ssl_email)
        cm.set_env_value("SSL_EMAIL", update.ssl_email)

    if update.dns_provider is not None:
        cm.set_config_value("dns_provider", update.dns_provider)

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
        "config": cm.load_config()
    }


@router.post("/generate-password")
async def generate_password(length: int = 32):
    """生成随机强密码"""
    return {"password": ConfigManager.generate_password(length)}
