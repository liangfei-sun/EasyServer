"""
EasyServer Config API
全局配置读写接口
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from ..core.config_manager import ConfigManager
import os

router = APIRouter(prefix="/api/config", tags=["config"])

PROJECT_ROOT = os.environ.get("EASYSERVER_ROOT", "/app")


def _get_config_manager():
    return ConfigManager(PROJECT_ROOT)


class ConfigUpdate(BaseModel):
    domain: Optional[str] = None
    access_mode: Optional[str] = None
    https_port: Optional[int] = None
    ssl_email: Optional[str] = None
    dns_provider: Optional[str] = None


@router.get("")
async def get_config():
    """获取全局配置"""
    cm = _get_config_manager()
    config = cm.load_config()
    env = cm.load_env()

    return {
        "config": config,
        "env_summary": {
            "DOMAIN": env.get("DOMAIN", ""),
            "ACCESS_MODE": env.get("ACCESS_MODE", "domain"),
            "HTTPS_PORT": env.get("HTTPS_PORT", "8443"),
        },
        "setup_completed": cm.is_setup_completed()
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

    if update.ssl_email is not None:
        cm.set_config_value("ssl_email", update.ssl_email)
        cm.set_env_value("SSL_EMAIL", update.ssl_email)

    if update.dns_provider is not None:
        cm.set_config_value("dns_provider", update.dns_provider)

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
