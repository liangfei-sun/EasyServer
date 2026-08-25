"""
EasyServer Nginx 配置工具
提取路由文件中重复的 Nginx 配置重新生成逻辑。
"""
import asyncio
import logging

logger = logging.getLogger("easyserver.nginx_utils")


def regenerate_nginx_config(cm, restart: bool = False) -> bool:
    """重新生成 Nginx 配置并热加载/重启。

    Args:
        cm: ConfigManager 实例
        restart: True 时执行 restart（端口变更），False 时执行 reload（常规热加载）

    Returns:
        True 表示成功，False 表示失败（Nginx 未运行或 reload 返回非零）
    """
    try:
        from .nginx_generator import NginxGenerator
        from .deps import PROJECT_ROOT, get_module_loader

        ng = NginxGenerator(PROJECT_ROOT)
        ml = get_module_loader()
        installed = ml.get_installed_modules()
        ng.generate_all(cm.load_config(), installed)
        if restart:
            ng.restart_nginx()
        else:
            if not ng.reload_nginx():
                logger.warning(
                    "Nginx 配置已重新生成，但热加载失败（nginx -s reload 返回非零），"
                    "请检查 Nginx 容器状态"
                )
                return False
        return True
    except Exception as e:
        logger.debug("Nginx 配置重新失败（不影响主流程）: %s", e)
        return False


async def async_regenerate_nginx_config(cm, restart: bool = False) -> bool:
    """异步版本：重新生成 Nginx 配置并热加载/重启。

    Args:
        cm: ConfigManager 实例
        restart: True 时执行 restart（端口变更），False 时执行 reload（常规热加载）

    Returns:
        True 表示成功，False 表示失败
    """
    try:
        from .nginx_generator import NginxGenerator
        from .deps import PROJECT_ROOT, get_module_loader

        ng = NginxGenerator(PROJECT_ROOT)
        ml = get_module_loader()
        installed = ml.get_installed_modules()
        ng.generate_all(cm.load_config(), installed)
        if restart:
            await ng.async_restart_nginx()
        else:
            if not await ng.async_reload_nginx():
                logger.warning(
                    "Nginx 配置已重新生成，但热加载失败（nginx -s reload 返回非零），"
                    "请检查 Nginx 容器状态"
                )
                return False
        return True
    except Exception as e:
        logger.debug("Nginx 配置重新失败（不影响主流程）: %s", e)
        return False
