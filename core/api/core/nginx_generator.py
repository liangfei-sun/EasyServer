"""
EasyServer Nginx Config Generator
"""
import subprocess
from pathlib import Path
from jinja2 import Environment, FileSystemLoader


class NginxGenerator:
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.nginx_module_dir = self.project_root / "modules" / "nginx"
        self.templates_dir = self.nginx_module_dir / "templates"
        self.conf_dir = self.nginx_module_dir / "conf.d"

    def generate_all(self, config: dict, modules: list):
        access_mode = config.get("access_mode", "domain")
        if access_mode == "ipv6_direct":
            self._generate_minimal_config(config)
            return
        self._generate_default_conf(config)
        self._generate_sites_conf(config, modules)
        self._copy_ssl_params()

    def _generate_default_conf(self, config: dict):
        env = Environment(loader=FileSystemLoader(str(self.templates_dir)))
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
        env = Environment(loader=FileSystemLoader(str(self.templates_dir)))
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
        src = self.templates_dir / "ssl-params.conf"
        dst = self.conf_dir / "ssl-params.conf"
        if src.exists():
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
