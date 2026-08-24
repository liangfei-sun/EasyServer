"""
EasyServer Config Manager
"""
import yaml
import secrets
import shutil
from pathlib import Path
from typing import Any, Optional
from dotenv import dotenv_values, set_key


class ConfigManager:
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.data_dir = self.project_root / "data"
        self.config_file = self.data_dir / "config.yaml"
        self.env_file = self.project_root / ".env"

    def _ensure_dirs(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> dict:
        if not self.config_file.exists():
            default = self._default_config()
            self.save_config(default)
            return default
        with open(self.config_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        if not config or not isinstance(config, dict):
            config = {}
        # 合并默认值，保留已有配置字段
        default = self._default_config()
        for key, value in default.items():
            if key not in config:
                config[key] = value
        return config

    def save_config(self, config: dict):
        self._ensure_dirs()
        with open(self.config_file, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

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

    def load_env(self) -> dict:
        if not self.env_file.exists():
            return {}
        return dict(dotenv_values(str(self.env_file)))

    def set_env_value(self, key: str, value: str):
        if not self.env_file.exists():
            example = self.project_root / ".env.example"
            if example.exists():
                shutil.copy(str(example), str(self.env_file))
            else:
                self.env_file.touch()
        set_key(str(self.env_file), key, value)

    def get_env_value(self, key: str, default: str = "") -> str:
        return self.load_env().get(key, default)

    def is_setup_completed(self) -> bool:
        return self.get_config_value("setup_completed", False)

    def mark_setup_completed(self):
        self.set_config_value("setup_completed", True)

    def is_network_configured(self) -> bool:
        return self.get_config_value("network_configured", False)

    def mark_network_configured(self):
        self.set_config_value("network_configured", True)

    def verify_password(self, password: str) -> bool:
        """验证管理密码"""
        stored_hash = self.get_config_value("admin_password_hash", "")
        if not stored_hash:
            return False
        import hashlib
        return hashlib.sha256(password.encode()).hexdigest() == stored_hash

    def set_admin_password(self, password: str):
        """设置管理密码（存储 SHA256 哈希）"""
        import hashlib
        self.set_config_value("admin_password_hash", hashlib.sha256(password.encode()).hexdigest())

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
