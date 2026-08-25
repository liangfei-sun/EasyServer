"""
EasyServer 后台任务工具
提取路由文件中重复的后台异步任务逻辑。
"""
import asyncio
import logging

logger = logging.getLogger("easyserver.background_tasks")

# 后台任务引用集，防止异步任务被 GC 提前回收
_background_tasks = set()


def trigger_dns_sync_background():
    """异步触发一次 DNS 同步（不阻塞 HTTP 响应，异常不影响主流程）"""
    from ..routes.dns import sync_dns

    async def _run():
        try:
            result = await sync_dns()
            summary = result.get("summary", {}) if isinstance(result, dict) else {}
            logger.info("后台 DNS 同步完成: %s", summary)
        except Exception as e:
            logger.warning("后台 DNS 同步失败（不影响主流程）: %s", e)

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
