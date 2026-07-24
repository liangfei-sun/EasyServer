"""
EasyServer Nginx API
Nginx 配置管理接口
"""
from fastapi import APIRouter, HTTPException
from ..core.config_manager import ConfigManager
from ..core.module_loader import ModuleLoader
from ..core.nginx_generator import NginxGenerator
import os

router = APIRouter(prefix="/api/nginx", tags=["nginx"])

PROJECT_ROOT = os.environ.get("EASYSERVER_ROOT", "/app")


@router.post("/generate")
async def generate_nginx_config():
    """根据当前配置重新生成 Nginx 配置"""
    cm = ConfigManager(PROJECT_ROOT)
    ml = ModuleLoader(PROJECT_ROOT)
    ng = NginxGenerator(PROJECT_ROOT)

    config = cm.load_config()
    installed_ids = cm.get_installed_modules()

    installed_modules = []
    for mid in installed_ids:
        metadata = ml.get_module_by_id(mid)
        if metadata:
            installed_modules.append(metadata)

    try:
        ng.generate_all(config, installed_modules)
        return {"success": True, "message": "Nginx 配置已生成"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload")
async def reload_nginx():
    """重载 Nginx"""
    ng = NginxGenerator(PROJECT_ROOT)
    success = ng.reload_nginx()
    if success:
        return {"success": True, "message": "Nginx 已重载"}
    else:
        raise HTTPException(status_code=500, detail="Nginx 重载失败")


@router.get("/config/sites")
async def get_sites_config():
    """获取当前 sites.conf 内容"""
    sites_file = os.path.join(PROJECT_ROOT, "modules", "nginx", "conf.d", "sites.conf")
    if os.path.exists(sites_file):
        with open(sites_file, "r") as f:
            return {"content": f.read()}
    return {"content": ""}


@router.get("/config/default")
async def get_default_config():
    """获取当前 default.conf 内容"""
    default_file = os.path.join(PROJECT_ROOT, "modules", "nginx", "conf.d", "default.conf")
    if os.path.exists(default_file):
        with open(default_file, "r") as f:
            return {"content": f.read()}
    return {"content": ""}
