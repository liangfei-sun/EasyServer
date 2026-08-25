"""
EasyServer 公共依赖工厂
集中管理 PROJECT_ROOT 常量与各核心组件的实例化，消除路由文件中的重复定义。
"""
import os
from .config_manager import ConfigManager
from .docker_manager import DockerManager
from .module_loader import ModuleLoader

# 项目根目录（容器内为 /app，开发时为环境变量指定）
PROJECT_ROOT = os.environ.get("EASYSERVER_ROOT", "/app")


def get_config_manager() -> ConfigManager:
    return ConfigManager(PROJECT_ROOT)


def get_docker_manager() -> DockerManager:
    return DockerManager(PROJECT_ROOT)


def get_module_loader() -> ModuleLoader:
    return ModuleLoader(PROJECT_ROOT)
