"""
EasyServer Config Manager
"""
import os
import re
import yaml
import secrets
import shutil
import hashlib
import hmac
import tempfile
import bcrypt
from pathlib import Path
from typing import Any, Optional
from dotenv import dotenv_values


class ConfigManager:
    def __init__(self, project_root: str, data_dir: str = ""):
        self.project_root = Path(project_root)
        # 持久化数据目录（config.yaml / .env 落地位置）：
        # - Docker 部署：由 deps.get_config_manager() 传入 DATA_DIR（持久卷 /data）
        # - 未传入时回退 {project_root}/data（宿主开发模式）
        self.data_dir = Path(data_dir) if data_dir else self.project_root / "data"
        self.config_file = self.data_dir / "config.yaml"
        # 运行时 .env 写入目标：与 config.yaml 同落持久卷，容器重建后不丢失（含 JWT_SECRET）
        self.env_file = self.data_dir / ".env"
        # 旧布局 .env（宿主/未设 DATA_DIR 模式的旧部署位于 {project_root}/.env），
        # 仅作为读取回退候选，与 docker_manager._get_env_file 双候选口径对齐
        self._env_file_legacy = self.project_root / ".env"
        # 内存缓存
        self._config_cache: Optional[dict] = None
        self._config_mtime: float = 0
        self._env_cache: Optional[dict] = None
        self._env_mtime: float = 0

    def _ensure_dirs(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> dict:
        if not self.config_file.exists():
            default = self._default_config()
            self.save_config(default)
            return default
        # 基于 mtime 的缓存
        try:
            mtime = os.path.getmtime(str(self.config_file))
        except OSError:
            mtime = 0
        if self._config_cache is not None and mtime == self._config_mtime:
            return self._config_cache
        with open(self.config_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        if not config or not isinstance(config, dict):
            config = {}
        # 合并默认值，保留已有配置字段
        default = self._default_config()
        for key, value in default.items():
            if key not in config:
                config[key] = value
        self._config_cache = config
        self._config_mtime = mtime
        return config

    def save_config(self, config: dict):
        self._ensure_dirs()
        # 原子写入：先写临时文件，再原子替换
        dir_name = os.path.dirname(str(self.config_file))
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            os.replace(tmp_path, str(self.config_file))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        # 清除缓存
        self._config_cache = None
        self._config_mtime = 0

    def get_config_value(self, key: str, default: Any = None) -> Any:
        config = self.load_config()
        value = config
        for k in key.split("."):
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    def set_config_value(self, key: str, value: Any):
        config = self.load_config()
        keys = key.split(".")
        d = config
        for k in keys[:-1]:
            if k not in d:
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value
        self.save_config(config)

    def _default_config(self) -> dict:
        return {
            "domain": "",
            "access_mode": "domain",
            "https_port": 8443,
            "ssl_email": "",
            "dns_provider": "aliyun",
            "panel_subdomain": "panel",
            "installed_modules": [],
            "setup_completed": False,
            "network_configured": False,
            "admin_password_hash": "",
            # DNS 凭证存储（加密字段，API 层脱敏返回）
            "dns_credentials": {
                "aliyun": {"key": "", "secret": ""},
                "cloudflare": {"token": ""}
            }
        }

    def _env_read_path(self) -> Optional[Path]:
        """解析 .env 读取路径：优先持久卷 data_dir/.env，不存在则回退旧布局
        {project_root}/.env（宿主开发模式）；均不存在返回 None。
        与 docker_manager._get_env_file 的双候选顺序保持一致。
        """
        if self.env_file.is_file():
            return self.env_file
        if self._env_file_legacy.is_file():
            return self._env_file_legacy
        return None

    def load_env(self) -> dict:
        read_path = self._env_read_path()
        if read_path is None:
            return {}
        # 基于 mtime 的缓存
        try:
            mtime = os.path.getmtime(str(read_path))
        except OSError:
            mtime = 0
        if self._env_cache is not None and mtime == self._env_mtime:
            return self._env_cache
        env = dict(dotenv_values(str(read_path)))
        self._env_cache = env
        self._env_mtime = mtime
        return env

    def set_env_value(self, key: str, value: str):
        """设置 .env 键值对（BUG-6 fix: 同目录原子写入，避免 null bytes 污染）

        python-dotenv 的 set_key 使用 tempfile + shutil.move 跨文件系统移动，
        在 Docker overlay2 环境下可能导致文件被 null bytes 填充。
        此实现改为同目录临时文件 + os.replace 原子替换，彻底消除此问题。

        写入目标固定为持久卷 data_dir/.env（唯一权威源）。
        注意：不在此处 blanket 同步 os.environ —— 进程 env 会压制 compose
        --env-file 的值，对以占位值初始化的存量模块（如 joplin-db）在
        restart/update 时用新值认证旧库而静默失败（docker_manager C2 场景）。
        确需进程内同步的键（如 JWT_SECRET）由 mark_setup_completed() 显式处理。
        """
        if not self.env_file.exists():
            # 先确保 data_dir 存在，否则 copy/touch 会抛 FileNotFoundError
            self._ensure_dirs()
            example = self.project_root / ".env.example"
            if example.exists():
                shutil.copy(str(example), str(self.env_file))
            else:
                self.env_file.touch()
        self._atomic_set_key(str(self.env_file), key, value)
        # 清除缓存
        self._env_cache = None
        self._env_mtime = 0

    @staticmethod
    def _atomic_set_key(file_path: str, key: str, value: str):
        """原子写入 .env 键值对

        1. 读取全部内容
        2. 查找并替换目标 key（或追加）
        3. 写入同目录临时文件
        4. os.replace 原子替换（POSIX 保证同文件系统原子性）
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 匹配 KEY=... 或 export KEY=... 行（跳过注释行）
        pattern = re.compile(
            rf'^\s*(?:export\s+)?{re.escape(key)}\s*='
        )
        quoted_value = "'{}'".format(value.replace("'", "\\'"))
        new_line = f"{key}={quoted_value}\n"

        found = False
        new_lines = []
        for line in lines:
            if pattern.match(line):
                new_lines.append(new_line)
                found = True
            else:
                new_lines.append(line)

        if not found:
            # 确保文件末尾有换行再追加
            if new_lines and not new_lines[-1].endswith('\n'):
                new_lines[-1] += '\n'
            new_lines.append(new_line)

        # 同目录临时文件 + os.replace 原子替换
        dir_name = os.path.dirname(os.path.abspath(file_path))
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix='.env_', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
                f.writelines(new_lines)
            os.replace(tmp_path, file_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get_env_value(self, key: str, default: str = "") -> str:
        return self.load_env().get(key, default)

    def is_setup_completed(self) -> bool:
        return self.get_config_value("setup_completed", False)

    def mark_setup_completed(self):
        # 持久化 JWT_SECRET：确保重启后 Token 依然有效
        env = self.load_env()
        if not env.get("JWT_SECRET"):
            jwt_secret = secrets.token_hex(32)
            self.set_env_value("JWT_SECRET", jwt_secret)
            # 同步更新当前进程环境变量及 auth 模块密钥
            os.environ["JWT_SECRET"] = jwt_secret
            try:
                from . import auth as _auth
                _auth.JWT_SECRET = jwt_secret
            except Exception:
                pass
        self.set_config_value("setup_completed", True)

    def is_network_configured(self) -> bool:
        return self.get_config_value("network_configured", False)

    def mark_network_configured(self):
        self.set_config_value("network_configured", True)

    @staticmethod
    def hash_password(password: str) -> str:
        """使用 bcrypt 生成密码哈希字符串"""
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def verify_password(self, password: str) -> bool:
        """验证管理密码（双模式：优先 bcrypt，回退 SHA256 并自动迁移）"""
        stored_hash = self.get_config_value("admin_password_hash", "")
        if not stored_hash:
            return False
        # 优先尝试 bcrypt 验证
        try:
            if bcrypt.checkpw(password.encode(), stored_hash.encode()):
                return True
        except (ValueError, TypeError):
            pass
        # 回退到旧 SHA256 验证
        if hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored_hash):
            # 自动迁移为 bcrypt 哈希
            self.set_admin_password(password)
            return True
        return False

    def set_admin_password(self, password: str):
        """设置管理密码（存储 bcrypt 哈希）"""
        self.set_config_value("admin_password_hash", self.hash_password(password))

    def get_installed_modules(self) -> list:
        return self.get_config_value("installed_modules", [])

    def add_installed_module(self, module_id: str):
        installed = self.get_installed_modules()
        if module_id not in installed:
            installed.append(module_id)
            self.set_config_value("installed_modules", installed)

    def remove_installed_module(self, module_id: str):
        installed = self.get_installed_modules()
        if module_id in installed:
            installed.remove(module_id)
            self.set_config_value("installed_modules", installed)

    # ===== 多域名管理方法 =====

    def get_domains(self) -> list:
        """返回域名列表。
        若 domains 字段存在则直接返回；
        否则从 domain + dns_provider 构造单元素列表（向后兼容）。
        """
        domains = self.get_config_value("domains")
        if domains and isinstance(domains, list) and len(domains) > 0:
            return domains
        # 向后兼容：从 domain + dns_provider 构造
        domain = self.get_config_value("domain", "")
        if not domain:
            return []
        dns_provider = self.get_config_value("dns_provider", "aliyun")
        return [{
            "domain": domain,
            "dns_provider": dns_provider,
            "purpose": "nginx",
            "status": "active"
        }]

    def get_primary_domain(self) -> str:
        """返回主域名。优先读 domains[0].domain，回退读 domain 字段。"""
        domains = self.get_domains()
        if domains:
            return domains[0].get("domain", "")
        return self.get_config_value("domain", "")

    def get_domain_config(self, domain: str) -> dict:
        """获取指定域名的配置项（dns_provider, purpose, status 等）。
        未找到返回空 dict。
        """
        domains = self.get_domains()
        for d in domains:
            if d.get("domain") == domain:
                return d
        return {}

    def add_domain(self, domain_cfg: dict) -> bool:
        """添加域名到 domains 列表。
        domain_cfg 格式: {"domain": "xxx", "dns_provider": "aliyun", "purpose": "nginx"}
        自动设置 status: "active"。
        如果 domain 已存在则更新。
        同步更新 domain 字段为 domains[0].domain。
        """
        domain_name = domain_cfg.get("domain", "").strip()
        if not domain_name:
            return False

        domains = self.get_domains()
        # 确保每个条目都有 status
        domain_cfg = dict(domain_cfg)
        domain_cfg.setdefault("status", "active")

        # 查找是否已存在
        found = False
        for i, d in enumerate(domains):
            if d.get("domain") == domain_name:
                domains[i] = {**domains[i], **domain_cfg}  # 保留原有字段，覆盖传入字段
                found = True
                break
        if not found:
            domains.append(domain_cfg)

        self.set_config_value("domains", domains)
        # 同步 domain 字段为主域名
        self.set_config_value("domain", domains[0].get("domain", ""))
        return True

    def remove_domain(self, domain: str) -> bool:
        """从 domains 列表移除域名。不允许移除主域名（domains[0]）。"""
        domains = self.get_domains()
        if not domains:
            return False
        # 不允许移除主域名
        if domains[0].get("domain") == domain:
            return False
        new_domains = [d for d in domains if d.get("domain") != domain]
        if len(new_domains) == len(domains):
            return False  # 未找到
        self.set_config_value("domains", new_domains)
        return True

    def update_domain_status(self, domain: str, status: str):
        """更新指定域名的状态（active/inactive/error）。"""
        domains = self.get_domains()
        for d in domains:
            if d.get("domain") == domain:
                d["status"] = status
                self.set_config_value("domains", domains)
                return

    @staticmethod
    def generate_password(length: int = 32) -> str:
        return secrets.token_hex(length // 2)
