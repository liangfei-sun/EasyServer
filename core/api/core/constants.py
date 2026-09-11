"""
EasyServer 后端公共常量与纯函数工具

集中存放「前后端同源」的契约常量与无副作用的小工具函数，避免同一份白名单/
占位符规则在多个路由文件里各写一遍而漂移。

本模块不得导入 deps / config_manager / docker_manager 等重组件，
以防循环导入（deps → docker_manager → constants 这类链路）。
"""
import os
import re

# ---------------------------------------------------------------------------
# 系统组件白名单（与前端 Market.vue 的 SYSTEM_MODULE_IDS 逐字同源）
#
# 这些模块由网络配置流程（routes/network.py 切换 access_mode、
# routes/cloudflare.py 一键接入）自动启停与管理，不经应用商店安装/卸载：
#   - nginx / acme：域名反代与证书签发的基础设施
#   - cloudflare-tunnel：Tunnel 接入模式的中转容器
# 前端仅隐藏按钮不足以阻止直接 curl 调用 API，故后端 install/uninstall
# 入口必须做服务端守卫（见 routes/modules.py）。
# ---------------------------------------------------------------------------
SYSTEM_MODULE_IDS = frozenset({"nginx", "acme", "cloudflare-tunnel"})

# 数据目录占位符：模块 module.yaml 的 config default 里允许写 ${DATA_DIR}/xxx，
# 由前端预填后原样提交。docker compose 的变量插值是「单趟、不递归」的：
# 一旦该键在 .env 里被设值，compose 就不会再对值内部的 ${DATA_DIR} 二次展开，
# 卷源会退化成含花括号的字面量相对路径，daemon 据此创建畸形目录。
# 因此落盘 .env 前必须把占位符展开为宿主真实绝对路径。
DATA_DIR_PLACEHOLDER = "${DATA_DIR}"

# 仅匹配 DATA_DIR 占位符（${DATA_DIR} / ${DATA_DIR:-default} / $DATA_DIR），
# 绝不触碰其它变量：其它键的既有 .env 值必须原样保留。
_DATA_DIR_PATTERN = re.compile(
    r"\$\{DATA_DIR(?::-[^}]*)?\}"   # ${DATA_DIR} 或 ${DATA_DIR:-/data}
    r"|\$DATA_DIR(?![A-Za-z0-9_])"  # $DATA_DIR（后面不再跟标识符字符）
)


def host_data_dir(fallback: str = "") -> str:
    """返回「宿主视角」的 DATA_DIR 绝对路径（docker daemon 解析卷源时看到的路径）

    优先级与 DockerManager._runtime_data_roots 保持一致：
      DATA_DIR_HOST（core 容器由 docker-compose.yml 注入的宿主路径）
      → DATA_DIR（宿主直跑模式下的真实路径 / 容器内为 /data）
      → fallback（调用方传入的 deps.DATA_DIR）→ "/data"
    """
    for key in ("DATA_DIR_HOST", "DATA_DIR"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return _strip_trailing_slash(value)
    if fallback and fallback.strip():
        return _strip_trailing_slash(fallback.strip())
    return "/data"


def expand_data_dir_placeholder(value, data_dir: str = ""):
    """把配置值中的 ${DATA_DIR} 占位符展开为宿主真实绝对路径

    - 非字符串（如 int/bool 配置项）原样返回；
    - 不含 DATA_DIR 字样的值走快速返回，不做任何改写；
    - 仅展开 DATA_DIR，其它 ${VAR} 一律保留（不改变既有语义）。
    """
    if not isinstance(value, str) or "DATA_DIR" not in value:
        return value
    resolved = data_dir or host_data_dir()
    return _DATA_DIR_PATTERN.sub(lambda _m: resolved, value)


def _strip_trailing_slash(path: str) -> str:
    """去掉末尾多余的 '/'（根 '/' 本身保留，避免退化成空串）"""
    stripped = path.rstrip("/")
    return stripped or "/"
