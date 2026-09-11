"""
EasyServer Backup API
备份管理接口
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from ..core.deps import get_config_manager, get_docker_manager
import asyncio
import json
import os
from pathlib import Path
from datetime import datetime

router = APIRouter(prefix="/api/backup", tags=["backup"])


class ScheduleUpdate(BaseModel):
    schedule: str
    retain_days: int = 7


def _dir_size_mb(path: Path) -> float:
    """统计目录内所有普通文件的总字节数并换算为 MB（目录不存在则返回 0）"""
    total = 0
    if path.exists():
        for f in path.rglob("*"):
            try:
                if f.is_file():
                    total += f.stat().st_size
            except OSError:
                # 遍历期间文件被删除或无权限时跳过，不影响整体统计
                continue
    return total / 1024 / 1024


def _normalize_restic_error(stderr: bytes, returncode: int) -> str:
    """把 restic / docker exec 的原始 stderr 归一化为可直接展示的简短原因"""
    text = (stderr.decode(errors="replace") if stderr else "").strip()
    lines = text.splitlines()
    last = lines[-1].strip() if lines else ""
    for prefix in ("Fatal: ", "Error: ", "error: "):
        if last.startswith(prefix):
            last = last[len(prefix):].strip()
            break
    if not last:
        return f"restic 退出码 {returncode}"
    if "No such container" in last or "is not running" in last:
        return "备份容器 easyserver-backup 未运行"
    return last


@router.get("/status")
async def backup_status():
    """获取备份状态和历史

    返回字段（前端 Backup.vue 契约，只增不减）：
      initialized    bool   当前活跃仓库目录是否存在
      snapshots      list   最近 10 个快照
      snapshot_count int    restic 报告的真实快照总条数（契约新增）
      last_backup    str    最后一次备份时间
      service_ok     bool   仅当 restic snapshots 成功执行且输出可解析为快照数组才为 True（契约新增）
      error          str    service_ok 为 True 时为空串，否则为归一化后的失败原因（契约新增）
      total_size_mb  float  data/backups 全目录大小（语义保持不变，含遗留旧库）
      repo_size_mb   float  仅当前活跃仓库大小（非契约字段，前端可选消费）
      repo_path      str    容器内仓库路径
      data_dir       str    容器内数据源目录
      password_set   bool   BACKUP_PASSWORD 是否已设置（绝不返回密码本身）
    """
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    backups_dir = data_dir / "backups"
    # 仓库路径已由 restic-repo 迁移为 restic-repo-v2；旧库 data/backups/restic-repo
    # （8.9G / 15 个快照）因加密密码永久丢失不可解密，按只读遗留存证原样保留，此处不再引用。
    repo_name = "restic-repo-v2"
    repo_dir = backups_dir / repo_name

    result = {
        "initialized": repo_dir.exists(),
        "snapshots": [],
        "snapshot_count": 0,
        "last_backup": "",
        "service_ok": False,
        "error": "",
        "repo_path": f"/backups/{repo_name}",
        "data_dir": "/data",
        "password_set": bool(os.environ.get("BACKUP_PASSWORD", "")),
    }

    if repo_dir.exists():
        try:
            # --no-lock：快照查询属只读操作，加此标志避免每次刷新面板都往仓库 locks/ 写入锁文件
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", "easyserver-backup",
                "restic", "snapshots", "--json", "--no-lock",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            out_text = stdout.decode(errors="replace") if stdout else ""
            if proc.returncode == 0 and out_text.strip():
                snapshots = json.loads(out_text)
                # M1：service_ok 只能在「解析 + 全部赋值」都成功之后才置 True，
                #   否则异常分支会产出 {service_ok: true, error: "..."} 的自相矛盾响应，
                #   前端 v-if="!service_ok" 不告警 → 绿色「正常」掩盖真实故障。
                # 类型防御：restic 对空仓库可能输出 JSON null（→ None），未来也可能
                #   改为 wrapper object；非 list / 含非对象元素一律按格式异常处理，
                #   service_ok 保持 False（len(None) 抛 TypeError 的路径被彻底消除）。
                if not isinstance(snapshots, list):
                    result["error"] = (
                        f"快照输出格式异常：期望 JSON 数组，实际为 {type(snapshots).__name__}"
                    )
                elif any(not isinstance(item, dict) for item in snapshots):
                    result["error"] = "快照输出格式异常：数组中存在非对象元素"
                else:
                    result["snapshot_count"] = len(snapshots)
                    result["snapshots"] = snapshots[-10:]  # 最近10个
                    if snapshots:
                        result["last_backup"] = snapshots[-1].get("time", "")
                    # 所有解析与赋值均已成功，此时才允许宣告服务正常
                    result["service_ok"] = True
            else:
                result["error"] = _normalize_restic_error(stderr, proc.returncode)
        except asyncio.TimeoutError:
            result["error"] = "读取快照超时（30s）"
        except json.JSONDecodeError as e:
            result["error"] = f"快照输出解析失败: {e}"
        except Exception as e:
            # ⚠ 原实现为 `except Exception: pass`，会把「容器不存在 / 密码错误 / 仓库损坏」
            #   全部静默吞掉，前端只显示 "0 快照" 而无任何异常提示，曾导致备份静默失效
            #   39 天无人察觉。现改为如实上报失败原因。
            result["error"] = f"读取快照失败: {e}"
    else:
        result["error"] = f"仓库目录不存在: {repo_dir}"

    # M1 契约兜底：service_ok 为 True 时 error 必为空。任何未来新增的赋值顺序
    # 疏漏都不会再把「有错误」的状态伪装成「服务正常」。
    if result["service_ok"] and result["error"]:
        result["service_ok"] = False

    # 计算备份目录大小（total_size_mb 语义保持不变：data/backups 全目录，含遗留旧库）
    result["total_size_mb"] = round(_dir_size_mb(backups_dir), 1)
    # 仅当前活跃仓库大小（新增，便于前端区分「有效备份」与「遗留死库」的磁盘占用）
    result["repo_size_mb"] = round(_dir_size_mb(repo_dir), 1)

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
