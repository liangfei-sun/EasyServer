"""
EasyServer Modules API
模块市场接口：可用模块列表、安装、卸载
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from ..core.module_loader import ModuleLoader
from ..core.config_manager import ConfigManager
from ..core.docker_manager import DockerManager
from ..core.nginx_generator import NginxGenerator
import os

router = APIRouter(prefix="/api/modules", tags=["modules"])

PROJECT_ROOT = os.environ.get("EASYSERVER_ROOT", "/app")


def _get_module_loader():
    return ModuleLoader(PROJECT_ROOT)


def _get_config_manager():
    return ConfigManager(PROJECT_ROOT)


def _get_docker_manager():
    return DockerManager(PROJECT_ROOT)


class InstallRequest(BaseModel):
    module_id: str
    config: dict = {}  # 用户填写的配置值


@router.get("")
async def list_modules():
    """获取所有可用模块（按分类分组）"""
    ml = _get_module_loader()
    cm = _get_config_manager()

    categories = ml.get_categories()
    installed_ids = cm.get_installed_modules()

    result = []
    for category in categories:
        cat_modules = []
        for module_id in category.get("modules", []):
            metadata = ml.get_module_by_id(module_id)
            if metadata:
                metadata["installed"] = module_id in installed_ids
                cat_modules.append(metadata)

        result.append({
            "id": category["id"],
            "name": category.get("name", ""),
            "description": category.get("description", ""),
            "modules": cat_modules
        })

    return {"categories": result}


@router.get("/{module_id}")
async def get_module(module_id: str):
    """获取单个模块详情"""
    ml = _get_module_loader()
    metadata = ml.get_module_by_id(module_id)
    if not metadata:
        raise HTTPException(status_code=404, detail=f"模块 {module_id} 不存在")

    validation = ml.validate_module(module_id)
    metadata["validation"] = validation
    return metadata


@router.post("/install")
async def install_module(request: InstallRequest):
    """安装指定模块"""
    ml = _get_module_loader()
    cm = _get_config_manager()
    dm = _get_docker_manager()

    module_id = request.module_id
    metadata = ml.get_module_by_id(module_id)
    if not metadata:
        raise HTTPException(status_code=404, detail=f"模块 {module_id} 不存在")

    if not metadata.get("has_compose"):
        raise HTTPException(status_code=400, detail="模块缺少 docker-compose.yml")

    # 检查依赖
    depends = metadata.get("depends_on", [])
    installed = cm.get_installed_modules()
    for dep in depends:
        if dep not in installed:
            raise HTTPException(
                status_code=400,
                detail=f"模块 {module_id} 依赖 {dep}，请先安装 {dep}"
            )

    # 写入用户配置到 .env
    for key, value in request.config.items():
        cm.set_env_value(key.upper(), str(value))

    # 标记为已安装
    cm.add_installed_module(module_id)

    # 启动模块（异步，不阻塞事件循环）
    try:
        result = await dm.async_start_module(module_id)
    except Exception as e:
        # 启动失败，回滚安装状态
        cm.remove_installed_module(module_id)
        raise HTTPException(
            status_code=500,
            detail=f"模块启动失败: {str(e)}"
        )

    if not result.get("success"):
        # Docker 命令返回非零，回滚安装状态
        cm.remove_installed_module(module_id)
        raise HTTPException(
            status_code=500,
            detail=f"模块启动失败: {result.get('error', '未知错误')}"
        )

    # 更新 Nginx 配置
    _update_nginx_config(cm, ml)

    return {
        "success": True,
        "module": module_id,
        "result": result
    }


@router.post("/{module_id}/uninstall")
async def uninstall_module(module_id: str):
    """卸载指定模块"""
    cm = _get_config_manager()
    dm = _get_docker_manager()
    ml = _get_module_loader()

    # 停止模块（异步）
    stop_error = None
    try:
        await dm.async_stop_module(module_id)
    except Exception as e:
        stop_error = str(e)  # 记录停止错误，但继续卸载

    # 从已安装列表移除
    cm.remove_installed_module(module_id)

    # 更新 Nginx 配置
    _update_nginx_config(cm, ml)

    result = {"success": True, "module": module_id}
    if stop_error:
        result["warning"] = f"模块已卸载，但停止容器时出错: {stop_error}"
    return result


@router.get("/{module_id}/validate")
async def validate_module(module_id: str):
    """验证模块配置"""
    ml = _get_module_loader()
    return ml.validate_module(module_id)


def _update_nginx_config(cm: ConfigManager, ml: ModuleLoader):
    """更新 Nginx 配置"""
    try:
        config = cm.load_config()
        installed_ids = cm.get_installed_modules()
        installed_modules = []
        for mid in installed_ids:
            metadata = ml.get_module_by_id(mid)
            if metadata:
                installed_modules.append(metadata)

        ng = NginxGenerator(PROJECT_ROOT)
        ng.generate_all(config, installed_modules)
        ng.reload_nginx()
    except Exception:
        pass  # Nginx 更新失败不影响主流程
