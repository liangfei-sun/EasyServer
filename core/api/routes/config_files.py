"""
EasyServer Config FILES API
配置文件原始读写接口：支持直接编辑 config.yaml 和 .env 文件内容。
"""
import os
import re
import yaml
import tempfile
import logging
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core.deps import PROJECT_ROOT, get_config_manager
from ..core.nginx_utils import async_regenerate_nginx_config
from ..core.background_tasks import trigger_dns_sync_background

router = APIRouter(prefix="/api/config", tags=["config"])
logger = logging.getLogger("easyserver.config_files")

# ===== 常量 =====

ALLOWED_FILES = {"config.yaml", ".env"}

DATA_DIR = os.path.join(PROJECT_ROOT, "data")

# admin_password_hash 脱敏提示
_HASH_MASK_HINT = "***（通过界面密码修改功能更改）"


# ===== 工具函数 =====

def _resolve_file_path(filename: str) -> str:
    """根据白名单文件名返回绝对路径，非法文件名抛出 400"""
    if filename not in ALLOWED_FILES:
        raise HTTPException(status_code=400, detail=f"不支持的文件: {filename}，仅允许 {', '.join(sorted(ALLOWED_FILES))}")
    if filename == "config.yaml":
        return os.path.join(DATA_DIR, "config.yaml")
    # .env
    return os.path.join(PROJECT_ROOT, ".env")


def _file_meta(filepath: str) -> dict:
    """返回文件元信息"""
    try:
        stat = os.stat(filepath)
        return {
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        }
    except FileNotFoundError:
        return {"size": 0, "modified": ""}


def _mask_password_hash(content: str, real_hash: str) -> str:
    """将 config.yaml 文本中的 admin_password_hash 值替换为脱敏提示"""
    if not real_hash:
        return content
    # 替换 YAML 中的 admin_password_hash: <value>
    pattern = r"(admin_password_hash\s*:\s*).*"
    return re.sub(pattern, rf"\1{_HASH_MASK_HINT}", content)


def _validate_env_content(content: str):
    """校验 .env 文件内容格式，返回 (ok, error_msg)"""
    for lineno, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        # 空行、注释行允许
        if not stripped or stripped.startswith("#"):
            continue
        # 必须是 KEY=VALUE 格式
        if "=" not in stripped:
            return False, f"第 {lineno} 行格式错误：缺少 '='（{stripped[:40]}）"
    return True, ""


def _atomic_write(filepath: str, content: str):
    """原子写入文件"""
    dir_name = os.path.dirname(filepath)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, filepath)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ===== Pydantic 模型 =====

class FileWriteRequest(BaseModel):
    content: str


# ===== API 接口 =====

@router.get("/files")
async def list_config_files():
    """返回可编辑配置文件列表"""
    files = []
    for name in sorted(ALLOWED_FILES):
        filepath = _resolve_file_path(name)
        meta = _file_meta(filepath)
        files.append({
            "name": name,
            "path": filepath,
            "exists": os.path.exists(filepath),
            **meta,
        })
    return {"files": files}


@router.get("/files/{filename}")
async def read_config_file(filename: str):
    """读取配置文件原始内容（含脱敏）"""
    filepath = _resolve_file_path(filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取文件失败: {e}")

    # 对 config.yaml 中的 admin_password_hash 做脱敏
    if filename == "config.yaml":
        cm = get_config_manager()
        real_hash = cm.get_config_value("admin_password_hash", "")
        content = _mask_password_hash(content, real_hash)

    meta = _file_meta(filepath)
    return {
        "filename": filename,
        "content": content,
        **meta,
    }


@router.put("/files/{filename}")
async def write_config_file(filename: str, body: FileWriteRequest):
    """写入配置文件内容（含校验与变更检测）"""
    filepath = _resolve_file_path(filename)
    content = body.content

    # ===== 写入前校验 =====
    if filename == "config.yaml":
        # 1. YAML 语法校验
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise HTTPException(status_code=400, detail=f"YAML 语法错误: {e}")
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="YAML 内容必须为对象格式")

        # 2. 关键字段存在性
        for required_field in ("setup_completed", "access_mode"):
            if required_field not in parsed:
                raise HTTPException(
                    status_code=400,
                    detail=f"缺少必要字段: {required_field}"
                )

        # 3. admin_password_hash 未被篡改
        cm = get_config_manager()
        current_hash = cm.get_config_value("admin_password_hash", "")
        new_hash = parsed.get("admin_password_hash", "")
        # 脱敏值以 *** 开头视为未修改，允许通过
        if isinstance(new_hash, str) and not new_hash.startswith("***"):
            if current_hash and new_hash != current_hash:
                raise HTTPException(
                    status_code=400,
                    detail="不允许通过文件编辑修改 admin_password_hash，请使用界面密码修改功能"
                )
        # 保持原始 hash 不变（防止误写空值）
        if current_hash:
            parsed["admin_password_hash"] = current_hash

        # 记录写入前状态用于变更检测
        old_config = cm.load_config()

        # ===== 写入 =====
        try:
            cm.save_config(parsed)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"写入 config.yaml 失败: {e}")

        # ===== 写入后变更检测 =====
        warnings = []
        new_config = parsed
        try:
            # 端口变更 → Nginx 重启
            old_port = old_config.get("https_port")
            new_port = new_config.get("https_port")
            if old_port != new_port:
                logger.info("检测到 https_port 变更: %s → %s，触发 Nginx 重启", old_port, new_port)
                await async_regenerate_nginx_config(cm, restart=True)
                warnings.append(f"端口变更 ({old_port} → {new_port})，已触发 Nginx 重启")

            # 域名/子域名/访问模式变更 → Nginx 重载
            nginx_reload_needed = False
            for field in ("domain", "panel_subdomain", "access_mode"):
                if old_config.get(field) != new_config.get(field):
                    nginx_reload_needed = True
                    break
            if nginx_reload_needed:
                logger.info("检测到域名/模式变更，触发 Nginx 重载")
                await async_regenerate_nginx_config(cm, restart=False)
                warnings.append("域名或访问模式变更，已触发 Nginx 重载")

            # DNS 提供商/凭证变更 → DNS 同步
            dns_changed = False
            for field in ("dns_provider", "dns_credentials"):
                if old_config.get(field) != new_config.get(field):
                    dns_changed = True
                    break
            if dns_changed:
                logger.info("检测到 DNS 配置变更，触发后台 DNS 同步")
                trigger_dns_sync_background()
                warnings.append("DNS 配置变更，已触发后台 DNS 同步")

        except Exception as e:
            logger.warning("变更检测或关联操作失败: %s", e)
            warnings.append(f"变更检测异常（配置已保存）: {e}")

        return {"success": True, "warnings": warnings}

    else:
        # ===== .env 文件 =====
        ok, err = _validate_env_content(content)
        if not ok:
            raise HTTPException(status_code=400, detail=err)

        try:
            _atomic_write(filepath, content)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"写入 .env 失败: {e}")

        logger.info(".env 文件已更新")
        return {"success": True, "warnings": []}
