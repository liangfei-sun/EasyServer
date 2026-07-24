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
            return self._default_config()
        with open(self.config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or self._default_config()

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
        return {"domain": "", "access_mode": "domain", "https_port": 8443, "ssl_email": "", "dns_provider": "aliyun", "installed_modules": [], "setup_completed": False}

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

    @staticmethod
    def generate_password(length: int = 32) -> str:
        return secrets.token_hex(length // 2)
