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
import subprocess
import re

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


@router.get("/port-check")
async def port_check():
    """检查所有已安装模块的端口冲突情况"""
    ml = _get_module_loader()
    installed = ml.get_installed_modules()

    # 收集所有模块端口
    module_ports = []
    for m in installed:
        access = m.get("access", {})
        port = access.get("port")
        if port:
            module_ports.append({"module": m["id"], "name": m.get("name", m["id"]), "port": int(port)})

    # 检查模块之间端口冲突
    port_map = {}
    for item in module_ports:
        port_map.setdefault(item["port"], []).append(item["module"])
    conflicts = []
    for port, modules in port_map.items():
        if len(modules) > 1:
            conflicts.append({"port": port, "type": "module_conflict", "modules": modules,
                              "message": f"端口 {port} 被多个模块共用: {', '.join(modules)}"})

    # 检查系统端口占用
    try:
        result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=5)
        system_ports = set()
        for line in result.stdout.strip().split("\n")[1:]:
            match = re.search(r':(\d+)\s', line)
            if match:
                system_ports.add(int(match.group(1)))
        for item in module_ports:
            if item["port"] in system_ports:
                # 排除本服务自己占用的端口
                conflicts.append({"port": item["port"], "type": "system_occupied",
                                  "module": item["module"],
                                  "message": f"端口 {item['port']} 已被系统进程占用"})
    except Exception:
        pass

    return {"has_conflict": len(conflicts) > 0, "conflicts": conflicts, "module_ports": module_ports}


@router.put("/{module_id}/port")
async def update_service_port(module_id: str, port: int):
    """修改服务端口（更新 .env，需重启服务生效）"""
    if port < 1 or port > 65535:
        raise HTTPException(status_code=400, detail="端口号必须在 1-65535 之间")

    ml = _get_module_loader()
    cm = _get_config_manager()
    module = ml.get_module_by_id(module_id)
    if not module:
        raise HTTPException(status_code=404, detail=f"模块 {module_id} 不存在")

    # 检查端口是否被系统占用
    try:
        result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=5)
        for line in result.stdout.strip().split("\n")[1:]:
            match = re.search(r':(\d+)\s', line)
            if match and int(match.group(1)) == port:
                raise HTTPException(status_code=409, detail=f"端口 {port} 已被系统进程占用")
    except HTTPException:
        raise
    except Exception:
        pass

    # 找到模块的端口配置 key
    config_items = module.get("config", [])
    port_key = None
    for item in config_items:
        if item.get("type") == "number" and "port" in item.get("key", "").lower():
            port_key = item["key"]
            break

    if not port_key:
        raise HTTPException(status_code=400, detail=f"模块 {module_id} 未找到可配置的端口项")

    # 更新 .env
    cm.set_env_value(port_key, str(port))

    # 端口修改后触发 Nginx 配置重新生成
    try:
        from ..core.nginx_generator import NginxGenerator
        ng = NginxGenerator(PROJECT_ROOT)
        installed_modules = ml.get_installed_modules()
        ng.generate_all(cm.load_config(), installed_modules)
        ng.reload_nginx()
    except Exception:
        pass

    return {"success": True, "module": module_id, "port": port, "env_key": port_key,
            "message": f"已将 {port_key} 更新为 {port}，请重启服务使其生效"}


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
