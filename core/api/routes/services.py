"""
EasyServer Services API
服务管理接口：列表、启动、停止、重启、更新、日志
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from ..core.docker_manager import DockerManager
from ..core.module_loader import ModuleLoader
from ..core.config_manager import ConfigManager
import os

router = APIRouter(prefix="/api/services", tags=["services"])

# 项目根目录（容器内为 /app，开发时为环境变量指定）
PROJECT_ROOT = os.environ.get("EASYSERVER_ROOT", "/app")


def _get_docker_manager():
    return DockerManager(PROJECT_ROOT)


def _get_module_loader():
    return ModuleLoader(PROJECT_ROOT)


def _get_config_manager():
    return ConfigManager(PROJECT_ROOT)


class ServiceStatus(BaseModel):
    module: str
    running: bool
    containers: list = []
    error: Optional[str] = None


@router.get("")
async def list_services():
    """获取所有已安装服务的状态"""
    dm = _get_docker_manager()
    try:
        statuses = dm.get_all_status()
        return {"services": statuses}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{module_id}")
async def get_service(module_id: str):
    """获取单个服务的状态"""
    dm = _get_docker_manager()
    ml = _get_module_loader()

    module = ml.get_module_by_id(module_id)
    if not module:
        raise HTTPException(status_code=404, detail=f"模块 {module_id} 不存在")

    try:
        status = dm.get_module_status(module_id)
        status["metadata"] = module
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{module_id}/start")
async def start_service(module_id: str):
    """启动指定服务"""
    dm = _get_docker_manager()
    try:
        result = dm.start_module(module_id)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{module_id}/stop")
async def stop_service(module_id: str):
    """停止指定服务"""
    dm = _get_docker_manager()
    try:
        result = dm.stop_module(module_id)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{module_id}/restart")
async def restart_service(module_id: str):
    """重启指定服务"""
    dm = _get_docker_manager()
    try:
        result = dm.restart_module(module_id)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{module_id}/update")
async def update_service(module_id: str):
    """更新指定服务（拉取最新镜像并重建）"""
    dm = _get_docker_manager()
    try:
        result = dm.update_module(module_id)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{module_id}/logs")
async def get_service_logs(module_id: str, lines: int = 100):
    """获取服务日志"""
    dm = _get_docker_manager()
    try:
        logs = dm.get_module_logs(module_id, lines)
        return {"module": module_id, "logs": logs}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
