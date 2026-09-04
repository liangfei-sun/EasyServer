"""
EasyServer Modules API
应用商店接口：可用模块列表、安装、卸载（后台任务化）
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from ..core.deps import MODULES_DIR, MODULES_TEMPLATE_DIR, get_config_manager, get_docker_manager, get_module_loader
from ..core.config_manager import ConfigManager
from ..core.docker_manager import DockerManager
from ..core.module_loader import ModuleLoader
import asyncio
import logging
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/modules", tags=["modules"])

# ---------------------------------------------------------------------------
# 安装任务表（内存存储）
# key = module_id，同一模块同一时间只允许一个安装任务（防重复安装）
# 任务结构：{module_id, status, stage, error, log, created_at, finished_at}
# status: pending / running / success / failed
# stage: prepare / pull / up / health（后台执行阶段）
# ---------------------------------------------------------------------------
_INSTALL_TASKS = {}
_TASK_MAX_RETENTION = 50  # 完成任务最多保留条数

TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_SUCCESS = "success"
TASK_FAILED = "failed"


class _InstallError(Exception):
    """安装过程错误，携带友好提示与原始详情"""

    def __init__(self, hint: str, detail: str = ""):
        super().__init__(hint)
        self.hint = hint
        self.detail = detail


def _cleanup_install_tasks():
    """清理完成任务，保留最近 _TASK_MAX_RETENTION 条"""
    finished = [t for t in _INSTALL_TASKS.values() if t["status"] in (TASK_SUCCESS, TASK_FAILED)]
    if len(finished) > _TASK_MAX_RETENTION:
        finished.sort(key=lambda t: t.get("finished_at") or 0)
        for t in finished[: len(finished) - _TASK_MAX_RETENTION]:
            _INSTALL_TASKS.pop(t["module_id"], None)


def _validate_required_config(metadata: dict, config: dict):
    """校验必填配置项；声明 auto_generate 的字段允许留空（自动生成）"""
    for field in metadata.get("config", []):
        key = field.get("key")
        if not field.get("required") or field.get("auto_generate"):
            continue
        value = config.get(key)
        if value is None or str(value).strip() == "":
            raise HTTPException(
                status_code=400,
                detail=f"字段「{field.get('label', key)}」为必填项，请填写后重试"
            )


def _fill_auto_generate_config(metadata: dict, config: dict):
    """为声明 auto_generate 且留空的字段生成随机值"""
    for field in metadata.get("config", []):
        key = field.get("key")
        if not field.get("auto_generate"):
            continue
        value = config.get(key)
        if value is None or str(value).strip() == "":
            config[key] = ConfigManager.generate_password()


async def _run_install_task(module_id: str, cm: ConfigManager, dm: DockerManager, ml: ModuleLoader):
    """后台执行安装：拉取镜像 → 启动容器；失败回滚已安装标记"""
    task = _INSTALL_TASKS.get(module_id)
    if not task:
        return
    try:
        # 阶段 1：拉取镜像（大镜像耗时长，失败多为网络/镜像问题）
        task["status"] = TASK_RUNNING
        task["stage"] = "pull"
        task["log"].append("正在拉取镜像，大镜像可能需要几分钟...")
        rc, stdout, stderr = await dm.async_pull_module(module_id)
        if stdout:
            # 显示本地命中/构建等 pull 阶段信息（如 F2 的 [local-hit]/[local-build]）
            task["log"].append(stdout.strip().split("\n")[-1])
        if rc != 0:
            diag = DockerManager.diagnose_pull_error(stderr or "")
            raise _InstallError(
                diag.get("hint") or f"镜像拉取失败（{module_id}）",
                stderr or ""
            )

        # 阶段 2：启动容器
        task["stage"] = "up"
        task["log"].append("镜像就绪，正在启动容器...")
        result = await dm.async_start_module(module_id)
        if not result.get("success"):
            raise _InstallError(
                f"容器启动失败: {result.get('error', '未知错误')}",
                result.get("error") or ""
            )

        # 阶段 3：健康门控（F1）——up 成功 ≠ 能稳定运行（如缺少证书/配置时容器会崩溃重启），
        # 安装完成前轮询容器状态，未达到健康则视为失败并走回滚
        task["stage"] = "health"
        task["log"].append("容器已启动，正在等待健康检查...")
        health = await dm.async_wait_module_healthy(module_id)
        if not health.get("success"):
            raise _InstallError(
                f"容器启动后未达到健康状态: {health.get('error', '未知原因')}",
                health.get("logs") or ""
            )

        task["status"] = TASK_SUCCESS
        task["stage"] = ""
        task["log"].append("安装完成")
        # 更新 Nginx 配置（失败不影响主流程）
        await _update_nginx_config(cm, ml)
    except _InstallError as e:
        cm.remove_installed_module(module_id)  # 回滚安装状态
        task["status"] = TASK_FAILED
        task["error"] = {"hint": e.hint, "detail": e.detail}
        task["log"].append(f"安装失败: {e.hint}")
    except Exception as e:
        cm.remove_installed_module(module_id)  # 回滚安装状态
        task["status"] = TASK_FAILED
        task["error"] = {"hint": f"安装过程中发生未预期错误: {str(e)}", "detail": str(e)}
        task["log"].append(f"安装失败: {str(e)}")
    finally:
        task["finished_at"] = time.time()
        _cleanup_install_tasks()


def _get_config_manager():
    return get_config_manager()


def _get_docker_manager():
    return get_docker_manager()


def _get_module_loader():
    return get_module_loader()


class InstallRequest(BaseModel):
    module_id: str
    config: dict = {}  # 用户填写的配置值


class UninstallRequest(BaseModel):
    remove_data: bool = False  # 是否同时删除数据目录


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
    """安装指定模块（后台任务执行，立即返回；通过 GET /{module_id}/install/status 查询进度）"""
    ml = _get_module_loader()
    cm = _get_config_manager()
    dm = _get_docker_manager()

    module_id = request.module_id
    metadata = ml.get_module_by_id(module_id)
    if not metadata:
        raise HTTPException(status_code=404, detail=f"模块 {module_id} 不存在")

    if not metadata.get("has_compose"):
        raise HTTPException(status_code=400, detail="模块缺少 docker-compose.yml")

    # 已安装或安装中，拒绝重复操作
    if module_id in cm.get_installed_modules():
        raise HTTPException(status_code=400, detail=f"模块 {module_id} 已安装")
    task = _INSTALL_TASKS.get(module_id)
    if task and task["status"] in (TASK_PENDING, TASK_RUNNING):
        raise HTTPException(status_code=409, detail=f"模块 {module_id} 正在安装中，请勿重复操作")

    # 检查依赖
    depends = metadata.get("depends_on", [])
    installed = cm.get_installed_modules()
    for dep in depends:
        if dep not in installed:
            raise HTTPException(
                status_code=400,
                detail=f"模块 {module_id} 依赖 {dep}，请先安装 {dep}"
            )

    # 校验必填配置项（auto_generate 字段留空自动生成）
    config = dict(request.config)
    _validate_required_config(metadata, config)
    _fill_auto_generate_config(metadata, config)

    # 写入用户配置到 .env
    for key, value in config.items():
        cm.set_env_value(key.upper(), str(value))

    # 标记为已安装（后台任务失败时回滚）
    cm.add_installed_module(module_id)

    # 创建后台安装任务：拉取镜像 → 启动容器
    _INSTALL_TASKS[module_id] = {
        "module_id": module_id,
        "status": TASK_PENDING,
        "stage": "",
        "error": None,
        "log": ["安装任务已创建，正在准备..."],
        "created_at": time.time(),
        "finished_at": None,
    }
    asyncio.create_task(_run_install_task(module_id, cm, dm, ml))

    return {
        "success": True,
        "module": module_id,
        "status": TASK_PENDING,
        "message": "安装任务已启动，可通过 /api/modules/{module_id}/install/status 查询进度"
    }


def _remove_path(path: Path):
    """删除文件或目录（忽略错误）"""
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink()
        except OSError:
            pass


@router.post("/{module_id}/uninstall")
async def uninstall_module(module_id: str, request: UninstallRequest):
    """卸载指定模块：停止容器 + 删除镜像，按用户选择删除数据"""
    cm = _get_config_manager()
    dm = _get_docker_manager()
    ml = _get_module_loader()

    # 防御性硬依赖检查（其他已安装模块依赖本模块时拒绝卸载）
    for mid in cm.get_installed_modules():
        if mid == module_id:
            continue
        m = ml.get_module_by_id(mid)
        if m and module_id in (m.get("depends_on") or []):
            raise HTTPException(
                status_code=400,
                detail=f"模块 {m['id']} 依赖 {module_id}，请先卸载 {m['id']}"
            )

    # 停止容器并删除镜像（失败记录 warning，不阻断卸载）
    remove_error = None
    try:
        await dm.async_remove_module(module_id)
    except Exception as e:
        remove_error = str(e)  # 记录错误，但继续卸载

    # 按用户选择删除数据目录
    removed_paths = []
    if request.remove_data:
        for p in dm.resolve_module_data_paths(module_id):
            await asyncio.to_thread(_remove_path, p)
            removed_paths.append(str(p))

    # 从已安装列表移除
    cm.remove_installed_module(module_id)

    # 更新 Nginx 配置
    nginx_warning = await _update_nginx_config(cm, ml)

    result = {
        "success": True,
        "module": module_id,
        "data_removed": request.remove_data,
        "removed_paths": removed_paths,
    }
    warnings = []
    if remove_error:
        warnings.append(f"模块已卸载，但停止容器/删除镜像时出错: {remove_error}")
    if nginx_warning:
        warnings.append(nginx_warning)
    if warnings:
        result["warnings"] = warnings
    return result


@router.get("/{module_id}/install/status")
async def get_install_status(module_id: str):
    """查询模块安装任务状态（无任务记录时返回 status=none）"""
    task = _INSTALL_TASKS.get(module_id)
    if not task:
        return {"module_id": module_id, "status": "none"}
    return {
        "module_id": module_id,
        "status": task["status"],
        "stage": task["stage"],
        "error": task["error"],
        "log": task["log"],
        "created_at": task["created_at"],
        "finished_at": task["finished_at"],
    }


@router.get("/{module_id}/validate")
async def validate_module(module_id: str):
    """验证模块配置"""
    ml = _get_module_loader()
    return ml.validate_module(module_id)


async def _update_nginx_config(cm: ConfigManager, ml: ModuleLoader) -> str | None:
    """更新 Nginx 配置，失败时返回警告信息"""
    try:
        config = cm.load_config()
        installed_ids = cm.get_installed_modules()
        installed_modules = []
        for mid in installed_ids:
            metadata = ml.get_module_by_id(mid)
            if metadata:
                installed_modules.append(metadata)

        from ..core.nginx_generator import NginxGenerator
        ng = NginxGenerator(MODULES_DIR, template_dir=MODULES_TEMPLATE_DIR)
        ng.generate_all(config, installed_modules)
        await ng.async_reload_nginx()
    except Exception as e:
        logger.warning(f"Failed to update Nginx config after module operation: {e}")
        return f"Nginx 配置更新失败（不影响当前操作）: {e}"
    return None
