"""
EasyServer Docker Manager
"""
import asyncio
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

import yaml

from .module_loader import ModuleLoader

logger = logging.getLogger(__name__)


def _parse_compose_ps_containers(stdout: str) -> list:
    """解析 docker compose ps --format json 输出，兼容逐行 JSON 与整体数组两种格式"""
    if not stdout or not stdout.strip():
        return []
    try:
        parsed = json.loads(stdout)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass
    containers = []
    for line in stdout.strip().split("\n"):
        if line.strip():
            try:
                containers.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return containers


class DockerManager:
    # 镜像仓库网络错误诊断规则：(类型, 正则, 友好提示)
    _DIAGNOSE_RULES = [
        ("registry_github", r"ghcr\.io", "无法连接 GitHub 容器仓库 ghcr.io，请检查网络连通性，或配置代理/镜像加速器后重试"),
        ("registry_dockerhub", r"registry-1\.docker\.io|docker\.io", "无法连接 Docker Hub 镜像仓库，请检查网络连通性，或配置镜像加速器后重试"),
        ("network", r"i/o timeout|context deadline exceeded|timed out|timeout|dial tcp|connection (refused|reset|closed)|TLS handshake", "镜像拉取网络超时或连接失败，请检查网络连通性，或配置代理/镜像加速器后重试"),
        ("manifest", r"manifest unknown|not found|unauthorized|denied|no matching manifest", "镜像不存在或无拉取权限，请检查镜像地址是否正确"),
    ]

    @staticmethod
    def diagnose_pull_error(stderr: str) -> dict:
        """解析 docker pull/compose pull 失败输出，返回友好诊断提示

        返回 {type, hint}，type 为诊断类型（registry_github / registry_dockerhub /
        network / manifest / unknown），hint 为中文友好提示；未命中返回 type=unknown。
        """
        if not stderr:
            return {"type": "unknown", "hint": ""}
        for diag_type, pattern, hint in DockerManager._DIAGNOSE_RULES:
            if re.search(pattern, stderr, re.IGNORECASE):
                return {"type": diag_type, "hint": hint}
        return {"type": "unknown", "hint": ""}

    def __init__(self, project_root: str, modules_dir: str = ""):
        self.project_root = Path(project_root)
        # 模块工作目录：优先使用传入的 modules_dir，否则回退到 {project_root}/modules
        if modules_dir:
            self.modules_dir = Path(modules_dir)
        else:
            self.modules_dir = self.project_root / "modules"

    def _get_compose_file(self, module_id: str) -> Path:
        compose_file = self.modules_dir / module_id / "docker-compose.yml"
        if not compose_file.exists():
            raise FileNotFoundError(f"模块 {module_id} 的 docker-compose.yml 不存在")
        return compose_file

    def _get_env_file(self) -> Optional[Path]:
        env_file = self.project_root / ".env"
        # AA 附带防御：R29 曾出现 .env 为目录的陷阱，is_file 避免把目录传给 --env-file
        return env_file if env_file.is_file() else None

    @staticmethod
    def _read_env_file_keys(env_file: Path) -> set:
        """读取 env 文件中定义的键名集合（AA：用于从进程环境剔除同键变量）"""
        keys = set()
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    keys.add(line.split("=", 1)[0].strip())
        except OSError:
            pass
        return keys

    def _compose_process_env(self) -> dict:
        """构建 compose 子进程环境变量（AA）

        docker compose 变量解析中进程 env 优先于 --env-file；core 容器经
        docker-compose.yml 的 env_file: .env 预置的模块占位键（如
        NEXTCLOUD_PORT=8888、NEXTCLOUD_ADMIN_PASSWORD=change_me_nextcloud）
        会压制安装时写入 --env-file 的真实 config 值。
        故剔除与 env-file 同键的进程变量（让 --env-file 即安装 config 生效），
        随后仍应用宿主路径覆盖（PROJECT_ROOT_HOST/DATA_DIR_HOST 不受影响）。
        """
        env = dict(os.environ)
        env_file = self._get_env_file()
        if env_file:
            for key in self._read_env_file_keys(env_file):
                env.pop(key, None)
        env.update(self._get_host_env_overrides())
        return env

    def _get_host_env_overrides(self) -> dict:
        """当运行在 Docker 容器内时，返回需要用宿主机路径覆盖的环境变量映射。

        Docker daemon 在宿主机上解析 volume 路径，需要用宿主机路径覆盖 .env 中的容器内路径。
        通过 PROJECT_ROOT_HOST / DATA_DIR_HOST 环境变量（由 core 的 docker-compose.yml 注入）
        覆盖 .env 中的 PROJECT_ROOT / DATA_DIR。
        """
        overrides = {}
        host_project_root = os.environ.get("PROJECT_ROOT_HOST")
        host_data_dir = os.environ.get("DATA_DIR_HOST")
        if host_project_root:
            overrides["PROJECT_ROOT"] = host_project_root
        if host_data_dir:
            overrides["DATA_DIR"] = host_data_dir
        return overrides

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
        module_dir = self.modules_dir / module_id
        # AA：剔除与 env-file 同键的进程占位变量（安装 config 生效）+ 宿主路径覆盖
        env = self._compose_process_env()
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(module_dir), timeout=120, env=env)
        if check and result.returncode != 0:
            raise RuntimeError(f"Docker compose 命令失败: {result.stderr}")
        return result

    async def _async_run_compose(self, module_id: str, *args, check: bool = True, timeout: int = 120) -> tuple:
        """异步执行 docker compose 命令，返回 (returncode, stdout, stderr)"""
        cmd = self._build_compose_cmd(module_id, *args)
        # AA：剔除与 env-file 同键的进程占位变量（安装 config 生效）+ 宿主路径覆盖
        env = self._compose_process_env()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.modules_dir / module_id),
            env=env
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

    async def async_pull_module(self, module_id: str, max_retries: int = 3) -> tuple:
        """拉取模块镜像，返回 (returncode, stdout, stderr)

        与启动分离：pull 失败说明是镜像/网络问题，可精确定位诊断。
        大镜像拉取耗时长，超时设为 10 分钟。
        网络波动时自动指数退避重试（最多 max_retries 次）。

        F2：拉取前先做本地短路——
        - compose 含 build 段（如 backup/nextcloud）→ registry 无此镜像，
          pull 必然结构性失败，改为显式 compose build 本地构建；
        - 全部引用镜像本地已存在 → 跳过网络拉取（stdout 返回 [local-hit]）。
        """
        # F2：本地短路（build 型走本地构建，已拉取镜像直接命中）
        if self._compose_has_build(module_id):
            logger.info(f"Module {module_id} compose has build section, building locally instead of pull")
            # 构建含基础镜像拉取与软件包安装，耗时上限独立于 pull 设为 20 分钟
            rc, stdout, stderr = await self._async_run_compose(module_id, "build", check=False, timeout=1200)
            if rc == 0:
                return 0, "[local-build] compose 含 build 段，已改为本地构建镜像", stderr
            return rc, stdout, stderr
        images = await self.get_module_images(module_id)
        if images and all(self.has_local_image(img) for img in images):
            logger.info(f"Module {module_id} images all present locally: {images}")
            return 0, f"[local-hit] 镜像本地已存在，跳过拉取: {', '.join(images)}", ""

        base_delay = 2
        for attempt in range(max_retries):
            rc, stdout, stderr = await self._async_run_compose(module_id, "pull", check=False, timeout=600)
            if rc == 0:
                return rc, stdout, stderr
            # 最后一次尝试：F3 降级兑底（denied/manifest）→ 仍缺镜像则维持原失败
            if attempt == max_retries - 1:
                diag = self.diagnose_pull_error(stderr or "")
                if diag.get("type") == "manifest":
                    # 精确 tag 被拒（denied/manifest unknown）→ 仅对本次拉取后仍缺失的镜像
                    # 尝试拉 repo:latest 并回打原 tag（Z：compose pull 已成功的镜像已在本地，
                    # 不纳入降级候选，避免多镜像 compose 把成功项一并作废）
                    images = await self.get_module_images(module_id)
                    candidates = [img for img in images if "@" not in img and not self.has_local_image(img)]
                    degraded = await self._fallback_pull_latest(candidates) if candidates else []
                    # Z：成功判据结果导向——compose 所需镜像全部本地可用即成功，
                    # 个别 latest 拉取失败不整体作废；仍缺镜像则维持原失败
                    missing = [img for img in images if not self.has_local_image(img)]
                    if images and not missing:
                        detail = "; ".join(degraded) if degraded else "（所需镜像已在本地，无需降级）"
                        logger.info(f"Latest-tag fallback for {module_id}: {detail}")
                        return 0, f"[latest-fallback] 精确 tag 拉取被拒，已降级 latest 并回打原 tag: {detail}", stderr
                logger.warning(f"Image pull failed for {module_id} after {max_retries} attempts")
                return rc, stdout, stderr
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Image pull failed for {module_id} (attempt {attempt + 1}/{max_retries}), retrying in {delay}s: {stderr[:200]}")
            await asyncio.sleep(delay)
        # unreachable, but satisfy type checker
        return rc, stdout, stderr

    @staticmethod
    async def _run_cmd_with_timeout(cmd: list, timeout: int) -> tuple:
        """Z：执行命令并在超时时终止子进程

        asyncio.wait_for 超时仅取消等待、不终止子进程，会遗留孤儿 docker pull
        长时间占用资源；此处超时后 terminate → 等待 10s → 仍不退则 kill。
        返回 (returncode, stdout, stderr)；超时或无法创建进程时 rc=-1。
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except OSError as e:
            return -1, "", f"failed to spawn {' '.join(cmd)}: {e}"
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode, stdout.decode(), stderr.decode()
        except asyncio.TimeoutError:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            return -1, "", f"command timed out after {timeout}s and was terminated: {' '.join(cmd)}"

    async def _fallback_pull_latest(self, images: list) -> list:
        """F3：对非 latest 镜像引用执行 tag 降级（pull repo:latest + tag 回原引用）

        返回成功降级的镜像明细列表（如 'repo:1.0 ← repo:latest'）。
        单个镜像降级失败不影响其他镜像；是否整体成功由调用方以结果导向判定
        （Z：compose 所需镜像是否全部本地可用）。
        """
        degraded = []
        for image in images:
            if "@" in image:  # digest 引用不降级
                continue
            repo, sep, tag = image.rpartition(":")
            if not sep or not repo or tag == "latest":
                continue
            rc, _, _ = await self._run_cmd_with_timeout(["docker", "pull", f"{repo}:latest"], timeout=600)
            if rc != 0:
                continue
            rc, _, _ = await self._run_cmd_with_timeout(["docker", "tag", f"{repo}:latest", image], timeout=30)
            if rc != 0:
                continue
            degraded.append(f"{image} ← {repo}:latest")
            logger.info(f"Image latest-fallback: pulled {repo}:latest and tagged as {image}")
        return degraded

    async def get_module_images(self, module_id: str) -> list:
        """列出模块 compose 引用的镜像（docker compose config --images）"""
        try:
            rc, stdout, stderr = await self._async_run_compose(module_id, "config", "--images", check=False)
        except Exception:
            return []
        if rc != 0:
            return []
        return [line.strip() for line in stdout.strip().split("\n") if line.strip()]

    def has_local_image(self, image: str) -> bool:
        """检查镜像是否已存在于本地（docker image inspect）"""
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True, text=True, timeout=15
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _compose_has_build(self, module_id: str) -> bool:
        """检查模块 compose 是否包含 build 段（build 型模块不走 registry pull）"""
        compose_file = self.modules_dir / module_id / "docker-compose.yml"
        if not compose_file.exists():
            return False
        try:
            with open(compose_file, "r", encoding="utf-8") as f:
                compose = yaml.safe_load(f) or {}
        except Exception:
            return False
        for svc in (compose.get("services") or {}).values():
            if isinstance(svc, dict) and svc.get("build") is not None:
                return True
        return False

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

    async def async_remove_module(self, module_id: str) -> dict:
        """卸载模块：停止并删除容器 + 删除镜像（docker compose down --rmi all）"""
        # 删除镜像可能较慢，超时设为 10 分钟
        rc, stdout, stderr = await self._async_run_compose(module_id, "down", "--rmi", "all", timeout=600)
        return {"module": module_id, "action": "remove", "success": rc == 0, "output": stdout, "error": stderr if rc != 0 else None}

    def resolve_module_data_paths(self, module_id: str) -> list:
        """解析模块数据目录：docker-compose volumes 中挂载在数据区的路径

        用于卸载时按用户选择删除数据。路径以代码运行时视角返回（容器内为
        /app、/app/data，宿主开发环境为项目根目录）：.env 中的 PROJECT_ROOT
        映射到 self.project_root，DATA_DIR 映射到 self.project_root/data。
        安全规则：
        - 仅接受 `${DATA_DIR}/<module_id>/` 下的路径（如 data/jellyfin/config）
        - 兼容 `data/<module_id>-xxx` 同级目录（如 data/filebrowser-db）
        - 接受 `${PROJECT_ROOT}/modules/<module_id>/` 下除配置类目录（conf.d/templates/scripts）外的路径（如 nginx 的 ssl/log）
        - 排除 DATA_DIR / PROJECT_ROOT / 模块目录本身（防止误删全部数据）
        """
        compose_file = self.modules_dir / module_id / "docker-compose.yml"
        if not compose_file.exists():
            return []
        env = self._load_env_dict()
        project_root = self.project_root.resolve()
        # .env 中的宿主路径（compose 变量值），用于路径映射
        env_project = Path(env.get("PROJECT_ROOT", str(project_root))).expanduser().resolve()
        env_data = Path(env.get("DATA_DIR", str(project_root / "data"))).expanduser().resolve()
        module_dir = (self.modules_dir / module_id).resolve()
        # 数据根目录（根 compose 将 ${DATA_DIR} 挂载到容器 /data，同时 ./data 挂载到 /app/data）
        data_root = project_root / "data"
        data_prefix = data_root / module_id
        keep_names = {"conf.d", "templates", "scripts"}

        def _runtime_path(p: Path) -> Path:
            """将 .env 宿主路径映射为代码运行时的可见路径"""
            try:
                rel = p.relative_to(env_project)
                return (project_root / rel).resolve()
            except ValueError:
                pass
            try:
                rel = p.relative_to(env_data)
                return (data_root / rel).resolve()
            except ValueError:
                return p.resolve()

        def _expand(value: str) -> str:
            def repl(m):
                default = m.group(2) or ""
                return env.get(m.group(1)) or default
            value = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}", repl, value)
            value = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", lambda m: env.get(m.group(1), ""), value)
            return value

        try:
            with open(compose_file, "r", encoding="utf-8") as f:
                compose = yaml.safe_load(f) or {}
        except Exception:
            return []

        data_paths = set()
        module_paths = set()

        def _split_host_source(vol: str) -> str:
            """提取卷的宿主机路径，跳过 ${...} 块（其默认值可能包含冒号或嵌套 ${...}）"""
            i = 0
            depth = 0
            while i < len(vol):
                ch = vol[i]
                if ch == "$" and i + 1 < len(vol) and vol[i + 1] == "{":
                    depth = 1
                    i += 2  # 跳过 ${
                    continue
                if depth:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                    i += 1
                    continue
                if ch == ":":
                    return vol[:i]
                i += 1
            return vol

        for svc in (compose.get("services") or {}).values():
            volumes = svc.get("volumes") or []
            if isinstance(volumes, dict):
                volumes = list(volumes.values())
            for vol in volumes:
                source = ""
                if isinstance(vol, dict):
                    source = vol.get("source", "") or vol.get("src", "")
                elif isinstance(vol, str):
                    source = _split_host_source(vol)
                if not source:
                    continue
                host_path = _expand(source)
                if not host_path:
                    continue
                try:
                    p = _runtime_path(Path(host_path).expanduser())
                except Exception:
                    continue
                if p == data_root or p == project_root or p == module_dir:
                    continue
                try:
                    if p.is_relative_to(data_prefix):
                        data_paths.add(data_prefix)
                    elif p.parent == data_root and p.name.startswith(f"{module_id}-"):
                        data_paths.add(p)
                    elif p.is_relative_to(module_dir) and p.name not in keep_names:
                        module_paths.add(p)
                except ValueError:
                    continue

        # 按深度降序返回（先删除子目录）
        result = list(data_paths) + list(module_paths)
        result.sort(key=lambda x: len(x.parts), reverse=True)
        return result

    # 配置类文件扩展名：bind 挂载源路径带此类后缀视为单文件挂载（F4）
    _CONFIG_FILE_SUFFIXES = {".yaml", ".yml", ".json", ".env", ".conf", ".ini", ".toml", ".xml", ".properties"}

    def _expand_env_value(self, value: str, env: dict) -> str:
        """展开 compose 值中的 ${VAR:-default} / $VAR 变量（与 resolve_module_data_paths 同规则）"""
        def repl(m):
            default = m.group(2) or ""
            return env.get(m.group(1)) or default
        value = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}", repl, value)
        value = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", lambda m: env.get(m.group(1), ""), value)
        return value

    async def _write_host_file(self, host_path: str, content: str) -> tuple:
        """经 docker daemon 在宿主侧写入文件（F4）

        core 容器未挂载宿主数据路径（仅挂 docker.sock），无法直接写宿主文件；
        使用 core 自身镜像起一次性容器执行写入，避免额外镜像依赖。
        父目录不存在时 bind 挂载会由 daemon 自动创建。
        返回 (成功, 错误信息)。
        """
        parent = str(Path(host_path).parent.as_posix())
        fname = Path(host_path).name
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "run", "--rm", "-i", "--entrypoint", "sh",
                "-v", f"{parent}:/mnt",
                self._core_image(),
                "-c", f"cat > /mnt/{fname}",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(content.encode()), timeout=120)
            if proc.returncode != 0:
                return False, stderr.decode(errors="replace").strip()[:200]
            return True, ""
        except (asyncio.TimeoutError, OSError) as e:
            return False, str(e)[:200]

    def _core_image(self) -> str:
        """获取 core 自身镜像名（用于经 daemon 执行宿主侧写文件）"""
        try:
            result = subprocess.run(
                ["docker", "inspect", "easyserver-core", "--format", "{{.Config.Image}}"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, OSError):
            pass
        return "busybox:latest"

    def _build_render_context(self, module_id: str, config: dict) -> dict:
        """构建模块模板渲染上下文（F4）

        同时提供：原始键、小写键、剥离模块前缀的小写键（如
        NOTEDISCOVERY_PASSWORD → password），覆盖常见模板命名习惯；
        auth_enabled 为布尔约定：存在非空 password 即启用认证。
        """
        ctx = {}
        prefix = module_id.replace("-", "_").upper() + "_"
        for k, v in config.items():
            ctx[k] = v
            ctx[k.lower()] = v
            if k.upper().startswith(prefix):
                ctx[k[len(prefix):].lower()] = v
        ctx.setdefault("auth_enabled", bool(ctx.get("password")))
        return ctx

    async def prepare_single_file_mounts(self, module_id: str, config: dict) -> list:
        """安装前预创建 compose 单文件 bind 挂载的宿主文件（F4）

        Docker 对不存在的 bind 源只会自动创建目录——期望单文件的挂载会变成
        同名目录陷阱（容器活着但配置永远写不进）。本方法在安装前：
        - 解析 compose volumes 中宿主源路径不存在且带配置类扩展名的挂载；
        - 模块 templates/<文件名>.j2 存在 → 用安装配置渲染生成；
        - 无模板 → 创建空文件并记录警告（部分应用空配置仍会崩溃，需模块指南说明）。
        宿主已存在的路径一律跳过（不覆盖用户数据）。
        返回动作描述列表（供安装日志展示）。
        """
        compose_file = self.modules_dir / module_id / "docker-compose.yml"
        if not compose_file.exists():
            return []
        try:
            with open(compose_file, "r", encoding="utf-8") as f:
                compose = yaml.safe_load(f) or {}
        except Exception:
            return []
        env = self._load_env_dict()
        env.update(self._get_host_env_overrides())  # daemon 视角宿主路径覆盖优先

        actions = []
        for svc in (compose.get("services") or {}).values():
            volumes = []
            if isinstance(svc, dict):
                volumes = svc.get("volumes") or []
            if isinstance(volumes, dict):
                volumes = list(volumes.values())
            for vol in volumes:
                source = ""
                if isinstance(vol, dict):
                    source = vol.get("source", "") or vol.get("src", "")
                elif isinstance(vol, str):
                    # 提取宿主段（跳过 ${...} 块，其内部可能含冒号；同 _split_host_source 规则）
                    i, depth = 0, 0
                    while i < len(vol):
                        ch = vol[i]
                        if ch == "$" and i + 1 < len(vol) and vol[i + 1] == "{":
                            depth = 1
                            i += 2  # 一起消费 ${
                            continue
                        if depth:
                            if ch == "{":
                                depth += 1
                            elif ch == "}":
                                depth -= 1
                            i += 1
                            continue
                        if ch == ":":
                            break
                        i += 1
                    source = vol[:i]
                if not source:
                    continue
                host_path = self._expand_env_value(source, env).strip()
                if not host_path:
                    continue
                p = Path(host_path)
                if p.exists() or p.suffix.lower() not in self._CONFIG_FILE_SUFFIXES:
                    continue

                template = self.modules_dir / module_id / "templates" / f"{p.name}.j2"
                if template.exists():
                    try:
                        from jinja2 import Environment, FileSystemLoader
                        jenv = Environment(loader=FileSystemLoader(str(template.parent)))
                        ctx = self._build_render_context(module_id, config)
                        content = jenv.get_template(template.name).render(**ctx)
                        how = f"模板渲染 {template.name}"
                    except Exception as e:
                        actions.append(f"警告：模板 {template.name} 渲染失败（{e}），将创建空文件")
                        content, how = "", "空文件"
                else:
                    content = ""
                    how = "空文件（模块未提供模板，若应用要求合法配置请参考模块指南）"
                ok, err = await self._write_host_file(host_path, content)
                if ok:
                    actions.append(f"预创建配置文件 {host_path}（{how}）")
                else:
                    actions.append(f"警告：预创建 {host_path} 失败: {err}")
        return actions

    async def prepare_data_dirs(self, module_id: str) -> list:
        """安装前预创建模块数据目录并修正属主为 uid 1000（AB）

        docker daemon 为不存在的 bind 源创建的目录属主为 root:root，以
        uid 1000 运行的镜像（filebrowser 等）首启写入即 EACCES（API 呈现 403）。
        经 docker compose config 渲染解析 bind 挂载（变量插值与 up 实际一致），
        仅对运行时数据根（DATA_DIR / PROJECT_ROOT）之下、宿主不存在的新建目录
        chown 1000:1000；已存在目录一律不触碰（避免破坏 postgres 类
        非 1000 属主数据，其镜像入口会自行 chown）。只读挂载与单文件挂载
        （F4 prepare_single_file_mounts 负责）跳过。core 进程以 root 运行且
        数据根为宿主 bind 挂载，chown 直接生效于宿主。
        返回动作描述列表（供安装日志展示）。
        """
        actions = []
        try:
            rc, stdout, stderr = await self._async_run_compose(module_id, "config", check=False)
        except Exception as e:
            logger.warning(f"Module {module_id} prepare_data_dirs: compose config failed: {e}")
            return actions
        if rc != 0:
            logger.warning(f"Module {module_id} prepare_data_dirs: compose config rc={rc}")
            return actions
        try:
            compose = yaml.safe_load(stdout) or {}
        except yaml.YAMLError as e:
            logger.warning(f"Module {module_id} prepare_data_dirs: parse config failed: {e}")
            return actions
        data_root = (os.environ.get("DATA_DIR_HOST") or os.environ.get("DATA_DIR") or "/data").rstrip("/")
        project_root = (os.environ.get("PROJECT_ROOT_HOST") or str(self.project_root)).rstrip("/")
        roots = [data_root, project_root]
        for svc in (compose.get("services") or {}).values():
            volumes = (svc.get("volumes") or []) if isinstance(svc, dict) else []
            for vol in volumes:
                if not isinstance(vol, dict):
                    continue
                if vol.get("type") not in (None, "bind") or vol.get("read_only"):
                    continue
                source = str(vol.get("source") or "")
                if not source.startswith("/"):
                    if source.startswith(("./", "../")):
                        source = str((self.modules_dir / module_id / source).resolve())
                    else:
                        continue  # 命名卷由 daemon 管理
                if Path(source).suffix.lower() in self._CONFIG_FILE_SUFFIXES:
                    continue  # 单文件挂载由 F4 处理
                if not any(source.startswith(r + "/") for r in roots):
                    continue  # 仅运行时数据根之下
                p = Path(source)
                if p.exists():
                    continue  # 已存在目录不触碰（避免破坏既有属主）
                try:
                    p.mkdir(parents=True, exist_ok=True)
                    os.chown(p, 1000, 1000)
                    actions.append(f"预创建数据目录并修正属主 1000:1000: {source}")
                    logger.info(f"Module {module_id} data dir prepared with owner 1000:1000: {source}")
                except OSError as e:
                    logger.warning(f"Module {module_id} data dir prepare failed for {source}: {e}")
                    actions.append(f"警告：数据目录 {source} 预创建/chown 失败: {e}")
        return actions

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

    async def _async_inspect_state(self, container_id: str) -> Optional[dict]:
        """docker inspect 读取容器 State（Status/Health/RestartCount），失败返回 None"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "inspect", "--format", "{{json .State}}", container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                return None
            return json.loads(stdout.decode())
        except (asyncio.TimeoutError, json.JSONDecodeError, OSError):
            return None

    async def async_wait_module_healthy(self, module_id: str, timeout: int = 90, interval: int = 3) -> dict:
        """安装后健康门控：轮询模块容器状态，稳定运行判成功（F1）

        成功条件：全部容器 Status=running（声明了 healthcheck 的须 Health=healthy），
        且连续 2 次轮询 RestartCount 不增（排除启动即崩溃重启的假健康）。
        仅依赖 Docker 状态探测，不做 HTTP 探测——core 与模块处于不同网络，
        无法通过宿主 127.0.0.1 端口探测。
        失败/超时返回时附带 compose logs --tail 30，用于展示真实失败原因。

        返回 {success, error, logs, containers, restarts}
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        stable_rounds = 0
        prev_restarts = None
        last_reason = f"健康探测超时（{timeout}s）"

        while loop.time() < deadline:
            rc, stdout, stderr = await self._async_run_compose(
                module_id, "ps", "--format", "json", check=False
            )
            containers = _parse_compose_ps_containers(stdout) if rc == 0 else []
            if not containers:
                last_reason = (stderr or "").strip() or "docker compose ps 未发现任何容器"
                stable_rounds = 0
                prev_restarts = None
                await asyncio.sleep(interval)
                continue

            container_names = []
            all_ok = True
            total_restarts = 0
            reasons = []
            for c in containers:
                cid = c.get("ID") or c.get("Id") or ""
                name = c.get("Name") or c.get("name") or cid
                container_names.append(name)
                state = await self._async_inspect_state(cid) if cid else None
                if state is None:
                    all_ok = False
                    reasons.append(f"容器 {name} 无法读取运行状态")
                    continue
                status = state.get("Status", "")
                health = (state.get("Health") or {}).get("Status")  # 无 healthcheck 时为 None
                restarts = state.get("RestartCount", 0) or 0
                total_restarts += restarts
                running = status == "running"
                health_ok = health is None or health == "healthy"
                if not running:
                    all_ok = False
                    reason = f"容器 {name} 状态为 {status}"
                    if state.get("ExitCode") not in (None, 0):
                        reason += f"（退出码 {state.get('ExitCode')}）"
                    reasons.append(reason)
                elif not health_ok:
                    all_ok = False
                    reasons.append(f"容器 {name} 健康检查为 {health}")

            if all_ok:
                if prev_restarts is not None and total_restarts <= prev_restarts:
                    stable_rounds += 1
                else:
                    stable_rounds = 1
                prev_restarts = total_restarts
                if stable_rounds >= 2:
                    return {
                        "success": True,
                        "error": "",
                        "logs": "",
                        "containers": container_names,
                        "restarts": total_restarts,
                    }
            else:
                stable_rounds = 0
                prev_restarts = None
                last_reason = "; ".join(reasons) or last_reason
            await asyncio.sleep(interval)

        logs = await self.async_get_module_logs(module_id, lines=30)
        return {
            "success": False,
            "error": last_reason,
            "logs": logs,
            "containers": [],
            "restarts": None,
        }

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
        from .deps import MODULES_DIR
        loader = ModuleLoader(MODULES_DIR)
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
