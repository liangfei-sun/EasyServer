"""
EasyServer Docker Manager
"""
import asyncio
import json
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

    def _build_compose_cmd(self, module_id: str, *args) -> list:
        """构建 docker compose 命令列表"""
        compose_file = self._get_compose_file(module_id)
        cmd = ["docker", "compose", "--file", str(compose_file)]
        env_file = self._get_env_file()
        if env_file:
            cmd.extend(["--env-file", str(env_file)])
        cmd.extend(args)
        return cmd

    def _run_compose(self, module_id: str, *args, check: bool = True) -> subprocess.CompletedProcess:
        cmd = self._build_compose_cmd(module_id, *args)
        # cwd 设为模块目录，确保 compose 中相对路径（如 ./scripts）正确解析
        module_dir = self.modules_dir / module_id
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(module_dir), timeout=120)
        if check and result.returncode != 0:
            raise RuntimeError(f"Docker compose 命令失败: {result.stderr}")
        return result

    async def _async_run_compose(self, module_id: str, *args, check: bool = True, timeout: int = 120) -> tuple:
        """异步执行 docker compose 命令，返回 (returncode, stdout, stderr)"""
        cmd = self._build_compose_cmd(module_id, *args)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.modules_dir / module_id)
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        stdout_str = stdout.decode()
        stderr_str = stderr.decode()
        if check and proc.returncode != 0:
            raise RuntimeError(f"Docker compose 命令失败: {stderr_str}")
        return proc.returncode, stdout_str, stderr_str

    def start_module(self, module_id: str) -> dict:
        result = self._run_compose(module_id, "up", "-d")
        return {"module": module_id, "action": "start", "success": result.returncode == 0, "output": result.stdout, "error": result.stderr if result.returncode != 0 else None}

    def stop_module(self, module_id: str) -> dict:
        result = self._run_compose(module_id, "down")
        return {"module": module_id, "action": "stop", "success": result.returncode == 0, "output": result.stdout, "error": result.stderr if result.returncode != 0 else None}

    def restart_module(self, module_id: str) -> dict:
        stop_result = self.stop_module(module_id)
        start_result = self.start_module(module_id)
        return {
            "module": module_id,
            "action": "restart",
            "success": start_result["success"],
            "output": start_result.get("output", ""),
            "error": start_result.get("error")
        }

    def update_module(self, module_id: str) -> dict:
        pull_result = self._run_compose(module_id, "pull", check=False)
        up_result = self._run_compose(module_id, "up", "-d", "--force-recreate")
        return {"module": module_id, "action": "update", "success": up_result.returncode == 0, "output": up_result.stdout, "error": up_result.stderr if up_result.returncode != 0 else None}

    def get_module_status(self, module_id: str) -> dict:
        result = self._run_compose(module_id, "ps", "-a", "--format", "json", check=False)
        containers = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                try:
                    c = json.loads(line)
                    containers.append({
                        "name": c.get("Name", ""),
                        "status": c.get("Status", ""),
                        "state": c.get("State", "")
                    })
                except json.JSONDecodeError:
                    continue
        return {
            "module": module_id,
            "running": any(c.get("state") == "running" or "Up" in c.get("status", "") for c in containers),
            "containers": containers
        }

    def get_module_logs(self, module_id: str, lines: int = 100) -> str:
        result = self._run_compose(module_id, "logs", "--no-color", "--tail", str(lines), check=False)
        return result.stdout + result.stderr

    async def async_start_module(self, module_id: str) -> dict:
        # 启动可能涉及镜像拉取，超时设为 10 分钟
        rc, stdout, stderr = await self._async_run_compose(module_id, "up", "-d", timeout=600)
        return {"module": module_id, "action": "start", "success": rc == 0, "output": stdout, "error": stderr if rc != 0 else None}

    async def async_stop_module(self, module_id: str) -> dict:
        rc, stdout, stderr = await self._async_run_compose(module_id, "down")
        return {"module": module_id, "action": "stop", "success": rc == 0, "output": stdout, "error": stderr if rc != 0 else None}

    async def async_restart_module(self, module_id: str) -> dict:
        stop = await self.async_stop_module(module_id)
        start = await self.async_start_module(module_id)
        return {"module": module_id, "action": "restart", "success": start["success"], "output": start.get("output", ""), "error": start.get("error")}

    async def async_update_module(self, module_id: str) -> dict:
        # 更新涉及拉取镜像，超时设为 10 分钟
        await self._async_run_compose(module_id, "pull", check=False, timeout=600)
        rc, stdout, stderr = await self._async_run_compose(module_id, "up", "-d", "--force-recreate", timeout=600)
        return {"module": module_id, "action": "update", "success": rc == 0, "output": stdout, "error": stderr if rc != 0 else None}

    async def async_get_module_status(self, module_id: str) -> dict:
        rc, stdout, stderr = await self._async_run_compose(module_id, "ps", "-a", "--format", "json", check=False)
        containers = []
        for line in stdout.strip().split("\n"):
            if line.strip():
                try:
                    c = json.loads(line)
                    containers.append({"name": c.get("Name", ""), "status": c.get("Status", ""), "state": c.get("State", "")})
                except json.JSONDecodeError:
                    continue
        return {"module": module_id, "running": any(c.get("state") == "running" or "Up" in c.get("status", "") for c in containers), "containers": containers}

    async def async_get_module_logs(self, module_id: str, lines: int = 100) -> str:
        rc, stdout, stderr = await self._async_run_compose(module_id, "logs", "--no-color", "--tail", str(lines), check=False)
        return stdout + stderr

    def _load_env_dict(self) -> dict:
        """加载 .env 文件为字典"""
        env_file = self._get_env_file()
        if not env_file:
            return {}
        env_dict = {}
        import re
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, _, value = line.partition('=')
                    value = value.strip().strip("'\"")
                    env_dict[key.strip()] = value
        return env_dict

    def _find_port_env_key(self, module: dict) -> str:
        """查找模块对应的端口环境变量名"""
        config_items = module.get("config", [])
        for item in config_items:
            if item.get("type") == "number" and "port" in item.get("key", "").lower():
                # 优先匹配含 HTTPS 的端口 key
                if "https" in item.get("key", "").lower():
                    return item["key"]
        # fallback: 返回第一个含 port 的 number 配置项
        for item in config_items:
            if item.get("type") == "number" and "port" in item.get("key", "").lower():
                return item["key"]
        return ""

    def _fetch_all_containers(self) -> list:
        """单次 docker ps 获取所有容器状态，避免串行调用"""
        try:
            result = subprocess.run(
                ["docker", "ps", "-a", "--format", "json"],
                capture_output=True, text=True, timeout=15
            )
            containers = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    try:
                        containers.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            return containers
        except Exception:
            return []

    def _match_containers_to_module(self, all_containers: list, module_id: str) -> list:
        """从全量容器列表中匹配属于指定模块的容器"""
        prefix = f"easyserver-{module_id}"
        matched = []
        for c in all_containers:
            name = c.get("Names", "") or c.get("Name", "")
            if name.startswith(prefix):
                matched.append({
                    "name": name,
                    "status": c.get("Status", ""),
                    "state": c.get("State", "")
                })
        return matched

    def get_all_status(self) -> list:
        from .module_loader import ModuleLoader
        loader = ModuleLoader(str(self.project_root))
        installed = loader.get_installed_modules()
        env = self._load_env_dict()  # 只读一次
        # 单次获取所有容器状态
        all_containers = self._fetch_all_containers()
        statuses = []
        for module in installed:
            try:
                containers = self._match_containers_to_module(all_containers, module["id"])
                running = any(
                    c.get("state") == "running" or "Up" in c.get("status", "")
                    for c in containers
                ) if containers else False
                status = {
                    "module": module["id"],
                    "running": running,
                    "containers": containers
                }
                # 合并 module.yaml 元数据
                access = module.get("access", {})
                status["name"] = module.get("name", module["id"])
                status["description"] = module.get("description", "")
                status["version"] = module.get("version", "")
                status["icon"] = module.get("icon", "")
                port = access.get("port")
                # 从 .env 读取实际端口值
                port_env_key = self._find_port_env_key(module)
                if port_env_key and port_env_key in env:
                    try:
                        port = int(env[port_env_key])
                    except (ValueError, TypeError):
                        pass
                status["port"] = port
                status["subdomain"] = access.get("subdomain", "")
                status["protocol"] = access.get("protocol", "http")
                statuses.append(status)
            except Exception as e:
                statuses.append({"module": module["id"], "name": module.get("name", module["id"]), "running": False, "error": str(e)})
        return statuses
