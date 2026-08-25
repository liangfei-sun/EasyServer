"""
EasyServer 网络配置 API
网络访问模式切换、模块启停
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

from ..core.deps import get_config_manager, get_docker_manager
from ..core.background_tasks import trigger_dns_sync_background
from ..core.nginx_utils import async_regenerate_nginx_config
from .config import _save_dns_credentials

router = APIRouter(prefix="/api/config", tags=["config"])

logger = logging.getLogger("easyserver.network")


class NetworkConfigRequest(BaseModel):
    access_mode: str  # "domain" | "cloudflare_tunnel" | "ipv6_direct"
    dns_provider: Optional[str] = None
    dns_credentials: Optional[dict] = None
    cf_tunnel_token: Optional[str] = None
    https_port: int = 8443


@router.post("/network")
async def configure_network(request: NetworkConfigRequest):
    """配置网络访问模式，自动启停对应模块"""
    cm = get_config_manager()
    dm = get_docker_manager()

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

        # 智能 DNS 同步：模块启停完成后异步触发一次，不阻塞 HTTP 响应
        try:
            trigger_dns_sync_background()
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
        # IPv6 直连：停止代理模块，切换 BIND_ADDRESS 为 ::
        for mid in ["nginx", "acme", "cloudflare-tunnel"]:
            if mid in cm.get_installed_modules():
                try:
                    dm.stop_module(mid)
                    results.append({"module": mid, "action": "stop", "success": True})
                except Exception:
                    pass
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
        cm.set_env_value("BIND_ADDRESS", "127.0.0.1")

    # 3. 生成 Nginx 配置（domain / hybrid 模式）
    nginx_warning = None
    if request.access_mode in ("domain", "hybrid"):
        nginx_ok = await async_regenerate_nginx_config(cm)
        if not nginx_ok:
            nginx_warning = "Nginx 配置已生成但热加载失败，请检查 Nginx 容器状态"
            logger.warning("Nginx 热加载失败，access_mode=%s", request.access_mode)

    # 4. 标记网络配置完成
    cm.mark_network_configured()

    resp = {
        "success": True,
        "access_mode": request.access_mode,
        "results": results,
        "message": "网络配置已保存"
    }
    if nginx_warning:
        resp["warning"] = nginx_warning
    return resp
