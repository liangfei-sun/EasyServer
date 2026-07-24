"""
EasyServer Module Loader
"""
import yaml
from pathlib import Path
from typing import Optional


class ModuleLoader:
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.modules_dir = self.project_root / "modules"
        self.registry_file = self.modules_dir / "_registry.yaml"

    def _load_yaml(self, path: Path) -> dict:
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def load_registry(self) -> dict:
        return self._load_yaml(self.registry_file)

    def load_module_metadata(self, module_id: str) -> Optional[dict]:
        module_dir = self.modules_dir / module_id
        module_yaml = module_dir / "module.yaml"
        if not module_yaml.exists():
            return None
        metadata = self._load_yaml(module_yaml)
        metadata["id"] = module_id
        metadata["path"] = str(module_dir)
        metadata["has_compose"] = (module_dir / "docker-compose.yml").exists()
        metadata["has_templates"] = (module_dir / "templates").exists()
        return metadata

    def get_all_modules(self) -> list:
        registry = self.load_registry()
        categories = registry.get("categories", [])
        all_modules = []
        for category in categories:
            for module_id in category.get("modules", []):
                metadata = self.load_module_metadata(module_id)
                if metadata:
                    metadata["category"] = category["id"]
                    metadata["category_name"] = category.get("name", "")
                    all_modules.append(metadata)
        return all_modules

    def get_installed_modules(self) -> list:
        return [m for m in self.get_all_modules() if m.get("has_compose")]

    def get_module_by_id(self, module_id: str) -> Optional[dict]:
        return self.load_module_metadata(module_id)

    def get_categories(self) -> list:
        registry = self.load_registry()
        return registry.get("categories", [])

    def validate_module(self, module_id: str) -> dict:
        module_dir = self.modules_dir / module_id
        issues = []
        module_yaml = module_dir / "module.yaml"
        if not module_yaml.exists():
            issues.append("缺少 module.yaml")
        else:
            metadata = self._load_yaml(module_yaml)
            for field in ["id", "name", "version", "description", "category"]:
                if field not in metadata:
                    issues.append(f"module.yaml 缺少必填字段: {field}")
        if not (module_dir / "docker-compose.yml").exists():
            issues.append("缺少 docker-compose.yml")
        return {"module_id": module_id, "valid": len(issues) == 0, "issues": issues}
