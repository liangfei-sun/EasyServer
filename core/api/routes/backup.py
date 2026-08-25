"""
EasyServer Backup API
备份管理接口
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from ..core.deps import PROJECT_ROOT, get_config_manager, get_docker_manager
import asyncio
import json
from pathlib import Path
from datetime import datetime

router = APIRouter(prefix="/api/backup", tags=["backup"])


class ScheduleUpdate(BaseModel):
    schedule: str
    retain_days: int = 7


@router.get("/status")
async def backup_status():
    """获取备份状态和历史"""
    data_dir = Path(PROJECT_ROOT) / "data"
    backups_dir = data_dir / "backups"
    repo_dir = backups_dir / "restic-repo"

    result = {"initialized": repo_dir.exists(), "snapshots": [], "last_backup": ""}

    if repo_dir.exists():
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", "easyserver-backup", "restic", "snapshots", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode == 0 and stdout.decode().strip():
                snapshots = json.loads(stdout.decode())
                result["snapshots"] = snapshots[-10:]  # 最近10个
                if snapshots:
                    result["last_backup"] = snapshots[-1].get("time", "")
        except Exception:
            pass

    # 计算备份目录大小
    total_size = 0
    if backups_dir.exists():
        for f in backups_dir.rglob("*"):
            if f.is_file():
                total_size += f.stat().st_size
    result["total_size_mb"] = round(total_size / 1024 / 1024, 1)

    return result


@router.post("/trigger")
async def trigger_backup():
    """手动触发一次备份"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "easyserver-backup", "/scripts/backup.sh",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
        return {
            "success": proc.returncode == 0,
            "output": stdout.decode()[-2000:] if stdout else "",
            "error": stderr.decode()[-500:] if stderr else ""
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="备份超时（10分钟）")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/schedule")
async def update_schedule(body: ScheduleUpdate):
    """更新备份周期"""
    cm = get_config_manager()
    cm.set_env_value("BACKUP_SCHEDULE", body.schedule)
    cm.set_env_value("BACKUP_RETAIN_DAYS", str(body.retain_days))
    # 重启备份容器使新计划生效
    dm = get_docker_manager()
    dm.restart_module("backup")
    return {"success": True, "schedule": body.schedule, "retain_days": body.retain_days}
