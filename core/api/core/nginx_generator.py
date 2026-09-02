"""
EasyServer Nginx Config Generator

模板读取与配置写入路径体系：
- 模板优先从 MODULES_DIR/nginx/templates/ 读取（用户可自定义）
- 不存在时回退到 MODULES_TEMPLATE_DIR/nginx/templates/（镜像内置默认模板）
- 配置文件统一写入 MODULES_DIR/nginx/conf.d/
"""
import asyncio
import subprocess
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


class NginxGenerator:
    def __init__(self, modules_dir: str, template_dir: str = ""):
        """
        Args:
            modules_dir: 模块工作目录（如 /easyserver_data/modules）
            template_dir: 模块模板目录（回退路径，如 /app/modules_template）；
                          为空则不启用回退。
        """
        self.modules_dir = Path(modules_dir)
        self.nginx_module_dir = self.modules_dir / "nginx"
        self.conf_dir = self.nginx_module_dir / "conf.d"

        # 模板搜索路径：优先 MODULES_DIR，回退到 template_dir
        self._template_dirs = [str(self.nginx_module_dir / "templates")]
        if template_dir:
            fallback = Path(template_dir) / "nginx" / "templates"
            if fallback.is_dir():
                self._template_dirs.append(str(fallback))

        # 用于非 Jinja2 的静态文件回退（如 ssl-params.conf）
        self._template_fallback_dir = Path(template_dir) / "nginx" if template_dir else None

    def _get_jinja_env(self) -> Environment:
        """创建 Jinja2 环境，按搜索路径依次查找模板"""
        return Environment(loader=FileSystemLoader(self._template_dirs))

    def _resolve_template_file(self, filename: str) -> Path | None:
        """在模板搜索路径中查找文件，返回第一个匹配路径"""
        for d in self._template_dirs:
            candidate = Path(d) / filename
            if candidate.exists():
                return candidate
        # 额外检查 fallback 目录（非 Jinja2 模板文件，如 ssl-params.conf）
        if self._template_fallback_dir:
            candidate = self._template_fallback_dir / "templates" / filename
            if candidate.exists():
                return candidate
        return None

    def generate_all(self, config: dict, modules: list):
        access_mode = config.get("access_mode", "domain")
        if access_mode == "ipv6_direct":
            self._generate_minimal_config(config)
            return
        self._generate_default_conf(config)
        self._generate_sites_conf(config, modules)
        self._copy_ssl_params()

    def _generate_default_conf(self, config: dict):
        env = self._get_jinja_env()
        template = env.get_template("default.conf.j2")
        content = template.render(http_port=config.get("http_port", 80))
        output = self.conf_dir / "default.conf"
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w") as f:
            f.write(content)

    def _generate_sites_conf(self, config: dict, modules: list):
        domain = config.get("domain", "")
        if not domain:
            return
        env = self._get_jinja_env()
        template = env.get_template("sites.conf.j2")
        server_names = []
        sites = []
        for module in modules:
            access = module.get("access", {})
            if not access or access.get("is_proxy"):
                continue
            subdomain = access.get("subdomain", "")
            port = access.get("port", 0)
            if not subdomain or not port:
                continue
            server_name = f"{subdomain}.{domain}"
            server_names.append(server_name)
            site = {"name": module.get("name", module["id"]), "server_name": server_name, "backend_port": port, "proxy_extra": access.get("proxy_extra", {})}
            proxy_extra = access.get("proxy_extra", {})
            if "client_max_body_size" in proxy_extra:
                site["client_max_body_size"] = proxy_extra["client_max_body_size"]
            sites.append(site)

        # 插入 EasyServer 管理面板自身的 server block
        panel_subdomain = config.get("panel_subdomain", "panel")
        if panel_subdomain:
            panel_name = f"{panel_subdomain}.{domain}"
            server_names.append(panel_name)
            sites.insert(0, {
                "name": "EasyServer 管理面板",
                "server_name": panel_name,
                "backend_port": 8900
            })

        content = template.render(http_port=config.get("http_port", 80), https_port=config.get("https_port", 8443), domain=domain, server_names=" ".join(server_names), sites=sites)
        with open(self.conf_dir / "sites.conf", "w") as f:
            f.write(content)

    def _copy_ssl_params(self):
        src = self._resolve_template_file("ssl-params.conf")
        dst = self.conf_dir / "ssl-params.conf"
        if src and src.exists():
            with open(src, "r") as f:
                content = f.read()
            with open(dst, "w") as f:
                f.write(content)

    def _generate_minimal_config(self, config: dict):
        content = f"""# EasyServer - IPv6 直连模式\nserver {{\n    listen {config.get('http_port', 80)} default_server;\n    listen [::]:{config.get('http_port', 80)} default_server;\n    server_name _;\n    location / {{\n        return 444;\n    }}\n}}\n"""
        self.conf_dir.mkdir(parents=True, exist_ok=True)
        with open(self.conf_dir / "default.conf", "w") as f:
            f.write(content)
        sites = self.conf_dir / "sites.conf"
        if sites.exists():
            sites.unlink()

    def reload_nginx(self) -> bool:
        result = subprocess.run(["docker", "exec", "easyserver-nginx", "nginx", "-s", "reload"], capture_output=True, text=True)
        return result.returncode == 0

    def restart_nginx(self) -> bool:
        """重启 Nginx 容器（端口变更时需要）"""
        result = subprocess.run(["docker", "restart", "easyserver-nginx"], capture_output=True, text=True)
        return result.returncode == 0

    async def async_reload_nginx(self) -> bool:
        """异步重载 Nginx"""
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "easyserver-nginx", "nginx", "-s", "reload",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        return proc.returncode == 0

    async def async_restart_nginx(self) -> bool:
        """异步重启 Nginx 容器（端口变更时需要）"""
        proc = await asyncio.create_subprocess_exec(
            "docker", "restart", "easyserver-nginx",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        return proc.returncode == 0
