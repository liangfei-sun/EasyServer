"""
EasyServer 公共依赖工厂
集中管理路径常量与各核心组件的实例化，消除路由文件中的重复定义。

路径体系（Docker 镜像一键部署模式）：
- APP_ROOT (PROJECT_ROOT): 镜像内 /app，代码路径（只读）
- DATA_DIR: /data，数据持久卷（config.yaml / 运行时 .env 落地位置）
- MODULES_DIR: /easyserver_data/modules，宿主机 modules 卷映射（可编辑工作目录）
- MODULES_TEMPLATE_DIR: /app/modules_template，镜像内模块初始模板（回退用）

向后兼容：若 EASYSERVER_MODULES_DIR 未设置，回退到 {APP_ROOT}/modules（开发模式）。
"""
import os
from .config_manager import ConfigManager
from .docker_manager import DockerManager
from .module_loader import ModuleLoader

# 镜像内代码根目录（只读）
PROJECT_ROOT = os.environ.get("EASYSERVER_ROOT", "/app")

# 数据持久化目录（容器内 /data → 宿主 data/ 卷）；
# config.yaml 与运行时 .env 必须落在此处，容器重建后不丢失。
# 未设置 DATA_DIR 时回退 {PROJECT_ROOT}/data（宿主开发模式，行为与旧版一致）。
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(PROJECT_ROOT, "data"))

# 模块工作目录（宿主机卷映射，可编辑）
MODULES_DIR = os.environ.get("EASYSERVER_MODULES_DIR", os.path.join(PROJECT_ROOT, "modules"))

# 模块初始模板目录（镜像内，回退用）
MODULES_TEMPLATE_DIR = os.environ.get(
    "EASYSERVER_MODULES_TEMPLATE_DIR",
    os.path.join(PROJECT_ROOT, "modules_template"),
)


def get_config_manager() -> ConfigManager:
    return ConfigManager(PROJECT_ROOT, data_dir=DATA_DIR)


def get_docker_manager() -> DockerManager:
    return DockerManager(PROJECT_ROOT, modules_dir=MODULES_DIR, data_dir=DATA_DIR)


def get_module_loader() -> ModuleLoader:
    return ModuleLoader(MODULES_DIR)
