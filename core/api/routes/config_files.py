"""
EasyServer CONFIG FILES API
配置文件原始读写接口：支持直接编辑 config.yaml 和 .env 文件内容。

安全加固（5 项）：
1. 路径穿越防护：白名单 + 路径规范化 + 前缀校验
2. 文件大小限制：拒绝超过 1MB 的内容
3. 写入冲突检测：写入前后 mtime 对比 + 内容校验
4. 写入前自动备份：.bak 文件
5. 失败自动回滚：校验失败时恢复 .bak
"""
import os
import re
import yaml
import shutil
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
MAX_CONTENT_SIZE = 1 * 1024 * 1024  # 1MB

DATA_DIR = os.path.join(PROJECT_ROOT, "data")

# admin_password_hash 脱敏提示
_HASH_MASK_HINT = "***（通过界面密码修改功能更改）"


# ===== 工具函数 =====

def _resolve_file_path(filename: str) -> str:
    """根据白名单文件名返回绝对路径，含路径穿越防护。

    安全加固 #1：路径穿越防护
    - 白名单校验文件名
    - 路径规范化后校验是否仍在允许的目录内
    """
    if filename not in ALLOWED_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件: {filename}，仅允许 {', '.join(sorted(ALLOWED_FILES))}"
        )

    # 路径穿越防护：拒绝包含路径分隔符或 .. 的文件名
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="非法文件名：禁止路径穿越字符")

    if filename == "config.yaml":
        raw_path = os.path.join(DATA_DIR, "config.yaml")
        allowed_dir = DATA_DIR
    else:
        raw_path = os.path.join(PROJECT_ROOT, ".env")
        allowed_dir = PROJECT_ROOT

    # 规范化路径并校验前缀，防止符号链接等绕过
    resolved = os.path.realpath(raw_path)
    allowed_prefix = os.path.realpath(allowed_dir)
    if not resolved.startswith(allowed_prefix + os.sep) and resolved != allowed_prefix:
        raise HTTPException(status_code=400, detail="路径穿越检测失败：解析后路径超出允许范围")

    return resolved


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


def _validate_content_size(content: str):
    """安全加固 #2：文件大小限制，拒绝超过 1MB 的内容"""
    size = len(content.encode("utf-8"))
    if size > MAX_CONTENT_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件内容过大（{size / 1024 / 1024:.1f} MB），上限为 {MAX_CONTENT_SIZE / 1024 / 1024:.0f} MB"
        )


def _backup_file(filepath: str) -> str | None:
    """安全加固 #4：写入前自动备份为 .bak 文件，返回备份路径；文件不存在则跳过"""
    if not os.path.exists(filepath):
        return None
    bak_path = filepath + ".bak"
    try:
        shutil.copy2(filepath, bak_path)
        logger.info("已备份 %s → %s", filepath, bak_path)
        return bak_path
    except Exception as e:
        logger.warning("备份文件失败: %s", e)
        return None


def _rollback_file(filepath: str, bak_path: str | None):
    """安全加固 #5：写入失败时从 .bak 回滚"""
    if bak_path and os.path.exists(bak_path):
        try:
            shutil.copy2(bak_path, filepath)
            logger.info("已回滚 %s ← %s", filepath, bak_path)
        except Exception as e:
            logger.error("回滚失败: %s — 请手动从 %s 恢复", e, bak_path)


def _verify_write(filepath: str, old_mtime_ns: int, expected_content: str = None) -> bool:
    """安全加固 #3：写入后校验 mtime 是否更新，确认写入生效。

    Args:
        filepath: 写入的文件路径
        old_mtime_ns: 写入前的 mtime（纳秒）
        expected_content: 若提供，则额外校验内容一致性；
                         config.yaml 经 yaml.dump 重排后不提供，仅校验 mtime
    """
    try:
        new_mtime_ns = os.stat(filepath).st_mtime_ns
        if new_mtime_ns <= old_mtime_ns:
            logger.error("写入后 mtime 未更新: %s（可能写入冲突）", filepath)
            return False
        # 若提供了预期内容，则校验内容一致性
        if expected_content is not None:
            with open(filepath, "r", encoding="utf-8") as f:
                actual = f.read()
            if actual != expected_content:
                logger.error("写入后内容校验不一致: %s", filepath)
                return False
        return True
    except Exception as e:
        logger.error("写入校验异常: %s", e)
        return False


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
    """写入配置文件内容（含安全加固 + 校验 + 变更检测）"""
    filepath = _resolve_file_path(filename)
    content = body.content

    # ===== 安全加固 #2：文件大小限制 =====
    _validate_content_size(content)

    # ===== 写入前校验（先校验格式，通过后再备份和写入）=====
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

        # ===== 安全加固 #4：校验通过后，写入前自动备份 =====
        bak_path = _backup_file(filepath)
        # ===== 安全加固 #3：记录写入前 mtime 用于冲突检测 =====
        old_mtime_ns = os.stat(filepath).st_mtime_ns if os.path.exists(filepath) else 0

        # ===== 写入 =====
        try:
            cm.save_config(parsed)
        except Exception as e:
            # 安全加固 #5：写入失败自动回滚
            _rollback_file(filepath, bak_path)
            raise HTTPException(status_code=500, detail=f"写入 config.yaml 失败: {e}")

        # ===== 安全加固 #3：写入后校验（config.yaml 经 yaml.dump 重排，仅校验 mtime）=====
        if not _verify_write(filepath, old_mtime_ns):
            _rollback_file(filepath, bak_path)
            raise HTTPException(status_code=500, detail="写入后校验失败（mtime 未更新），已自动回滚")

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

        # ===== 安全加固 #4：校验通过后，写入前自动备份 =====
        bak_path = _backup_file(filepath)
        # ===== 安全加固 #3：记录写入前 mtime =====
        old_mtime_ns = os.stat(filepath).st_mtime_ns if os.path.exists(filepath) else 0

        try:
            _atomic_write(filepath, content)
        except Exception as e:
            # 安全加固 #5：写入失败自动回滚
            _rollback_file(filepath, bak_path)
            raise HTTPException(status_code=500, detail=f"写入 .env 失败: {e}")

        # 安全加固 #3：写入后校验（.env 为原样写入，校验 mtime + 内容一致性）
        if not _verify_write(filepath, old_mtime_ns, expected_content=content):
            _rollback_file(filepath, bak_path)
            raise HTTPException(status_code=500, detail="写入后校验失败，已自动回滚")

        logger.info(".env 文件已更新")
        return {"success": True, "warnings": []}
