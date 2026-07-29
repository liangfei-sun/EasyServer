"""
EasyServer Backup API
备份管理接口
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from ..core.docker_manager import DockerManager
from ..core.config_manager import ConfigManager
import os
import subprocess
import json
from pathlib import Path
from datetime import datetime

router = APIRouter(prefix="/api/backup", tags=["backup"])
PROJECT_ROOT = os.environ.get("EASYSERVER_ROOT", "/app")


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
            proc = subprocess.run(
                ["docker", "exec", "easyserver-backup", "restic", "snapshots", "--json"],
                capture_output=True, text=True, timeout=30
            )
            if proc.returncode == 0 and proc.stdout.strip():
                snapshots = json.loads(proc.stdout)
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
        proc = subprocess.run(
            ["docker", "exec", "easyserver-backup", "/scripts/backup.sh"],
            capture_output=True, text=True, timeout=600
        )
        return {
            "success": proc.returncode == 0,
            "output": proc.stdout[-2000:] if proc.stdout else "",
            "error": proc.stderr[-500:] if proc.stderr else ""
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="备份超时（10分钟）")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/schedule")
async def update_schedule(body: ScheduleUpdate):
    """更新备份周期"""
    cm = ConfigManager(PROJECT_ROOT)
    cm.set_env_value("BACKUP_SCHEDULE", body.schedule)
    cm.set_env_value("BACKUP_RETAIN_DAYS", str(body.retain_days))
    # 重启备份容器使新计划生效
    dm = DockerManager(PROJECT_ROOT)
    dm.restart_module("backup")
    return {"success": True, "schedule": body.schedule, "retain_days": body.retain_days}
