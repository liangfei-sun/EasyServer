"""
EasyServer Docker Manager
"""
import subprocess
from pathlib import Path
from typing import Optional


class DockerManager:
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.modules_dir = self.project_root / "modules"

    def _get_compose_file(self, module_id: str) -> Path:
        compose_file = self.modules_dir / module_id / "docker-compose.yml"
        if not compose_file.exists():
            raise FileNotFoundError(f"模块 {module_id} 的 docker-compose.yml 不存在")
        return compose_file

    def _get_env_file(self) -> Optional[Path]:
        env_file = self.project_root / ".env"
        return env_file if env_file.exists() else None

    def _run_compose(self, module_id: str, *args, check: bool = True) -> subprocess.CompletedProcess:
        compose_file = self._get_compose_file(module_id)
        cmd = ["docker", "compose", "-f", str(compose_file)]
        env_file = self._get_env_file()
        if env_file:
            cmd.extend(["--env-file", str(env_file)])
        cmd.extend(args)
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.project_root), timeout=120)
        if check and result.returncode != 0:
            raise RuntimeError(f"Docker compose 命令失败: {result.stderr}")
        return result

    def start_module(self, module_id: str) -> dict:
        result = self._run_compose(module_id, "up", "-d")
        return {"module": module_id, "action": "start", "success": result.returncode == 0, "output": result.stdout, "error": result.stderr if result.returncode != 0 else None}

    def stop_module(self, module_id: str) -> dict:
        result = self._run_compose(module_id, "down")
        return {"module": module_id, "action": "stop", "success": result.returncode == 0, "output": result.stdout, "error": result.stderr if result.returncode != 0 else None}

    def restart_module(self, module_id: str) -> dict:
        result = self._run_compose(module_id, "restart")
        return {"module": module_id, "action": "restart", "success": result.returncode == 0, "output": result.stdout, "error": result.stderr if result.returncode != 0 else None}

    def update_module(self, module_id: str) -> dict:
        pull_result = self._run_compose(module_id, "pull", check=False)
        up_result = self._run_compose(module_id, "up", "-d", "--force-recreate")
        return {"module": module_id, "action": "update", "success": up_result.returncode == 0, "output": up_result.stdout, "error": up_result.stderr if up_result.returncode != 0 else None}

    def get_module_status(self, module_id: str) -> dict:
        result = self._run_compose(module_id, "ps", "-a", check=False)
        containers = []
        for line in result.stdout.strip().split("\n")[2:]:
            if line.strip():
                parts = line.split()
                if len(parts) >= 3:
                    containers.append({"name": parts[0], "status": " ".join(parts[1:])})
        return {"module": module_id, "running": any("Up" in c.get("status", "") for c in containers), "containers": containers}

    def get_module_logs(self, module_id: str, lines: int = 100) -> str:
        result = self._run_compose(module_id, "logs", "--tail", str(lines), check=False)
        return result.stdout + result.stderr

    def get_all_status(self) -> list:
        from .module_loader import ModuleLoader
        loader = ModuleLoader(str(self.project_root))
        installed = loader.get_installed_modules()
        statuses = []
        for module in installed:
            try:
                status = self.get_module_status(module["id"])
                statuses.append(status)
            except Exception as e:
                statuses.append({"module": module["id"], "running": False, "error": str(e)})
        return statuses
