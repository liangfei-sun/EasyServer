"""
EasyServer Public IP Utilities
公网 IP 检测工具：探测服务器公网 IPv4 / IPv6 地址

兼容契约（不得破坏）：
    get_public_ipv4() / get_public_ipv6() / get_public_ips()
    函数名、签名、返回类型不变，失败一律返回空字符串 / 空值。

IPv6 探测路径选择（先做廉价本地判定，见 _probe_ipv6_sync 注释）：
    1. 本机存在【已生效的】scope-global 全球单播地址（GUA, 2000::/3）
       → 原 urllib 直连探测（container-direct，适配未来 IPv6-enabled 部署）；
    2. 否则若 /var/run/docker.sock 可用 → 经 docker daemon 在【宿主网络命名空间】
       起一次性容器代理探测（host-namespace）；
    3. 否则（宿主直跑 / 开发模式，无 socket）→ urllib 直连兜底（best effort）。
    注：_in_container() 仅作日志信息，不再作为门控条件——避免 cgroup v2 私有
    cgroupns 或 runc 无 /.dockerenv 时假阴性，把"宿主有 IPv6"误判为 no_ipv6。

代理探测的 no_ipv6 vs probe_failed 采用【确定性判定】，不靠 curl 退出码猜测：
    第一步 `docker run --network host --entrypoint cat <image> /proc/net/if_inet6`
    读取宿主视图（共享 _parse_if_inet6 解析）：
      - 宿主无已生效 GUA → no_ipv6（error=None，前端不告警）——家宽无 IPv6 的正确归类；
      - 宿主有 GUA → 再进入 curl -6 三源探测；三源全败 → probe_failed（error=可读原因）。

错误分类：
    - 成功：value 非空，method ∈ {'host-namespace', 'container-direct'}，error=None
    - 确无 IPv6（no_ipv6）：确定性判定宿主无公网 IPv6 出口 → value=""，error=None
    - 探测失败（probe_failed）：docker socket 不可用 / 无可用代理镜像 / 子进程超时
      或异常 / 预算耗尽 / 宿主有 GUA 但所有源不可达 → value=""，error=人类可读原因
"""

import asyncio
import ipaddress
import logging
import os
import subprocess
import threading
import time
import urllib.request

logger = logging.getLogger("easyserver.ip_utils")

__all__ = [
    "IPV4_PROVIDERS", "IPV6_PROVIDERS",
    "get_public_ipv4", "get_public_ipv6", "get_public_ips",
    "get_public_ipv4_detailed", "get_public_ipv6_detailed",
    "aget_public_ipv6_detailed", "aget_public_ips_detailed",
    "invalidate_ipv6_cache",
]

# IPv4 探测接口（A1：容器内实证优选 3 个稳定低延迟源，可用源前置，按序尝试）。
# 实测证据（easyserver-proxy 网络内 curl -4，7 轮全 rc=0 HTTP=200，返回 117.147.30.30）：
#   checkip.amazonaws.com  T=0.27~1.37s（多数 <0.5s，最低延迟）
#   ipinfo.io/ip           T=0.32~0.67s（稳定）
#   ifconfig.me/ip         T=0.66~1.15s（稳定）
# 已剔除实测永久失效/剧烈抖动源：
#   api.ipify.org（连接被拒 rc=7 Errno111，有 A 记录无 AAAA，永久失效）
#   api.my-ip.io（12s 连接超时 rc=28，永久失效）
#   ipv4.icanhazip.com / icanhazip.com（T 抖动 0.6~8.7s，并现 12s TLS 超时）
#   4.ipw.cn（DNS 无记录 Errno-5，永久失效）
IPV4_PROVIDERS = [
    "https://checkip.amazonaws.com",
    "https://ipinfo.io/ip",
    "https://ifconfig.me/ip",
]

# IPv6 探测接口（均为 IPv6-only 域名，仅有 AAAA 记录，解析器必走 IPv6；
# 已移除 DNS 解析失败的 https://6.ipw.cn）
IPV6_PROVIDERS = [
    "https://api6.ipify.org",
    "https://ipv6.icanhazip.com",
    "https://v6.ident.me",
]

DOCKER_SOCK = "/var/run/docker.sock"
CORE_CONTAINER = "easyserver-core"
ALPINE_FALLBACK = "alpine:latest"

# ===== 时延预算（M-b）：内层各步 timeout 必须 < 外层总预算，且总预算 < 前端 30s =====
# 前端 axios timeout=30000ms（core/web/src/api/index.js），此处留 5s 余量。
_FETCH_TIMEOUT = 8          # urllib 单次直连探测超时（秒）
_CURL_TIMEOUT = 6           # 代理容器内 curl/wget 单次探测自身超时（秒）
_SUBPROC_TIMEOUT = 12       # 单次 docker run 子进程硬上限（含容器启动开销）
_RESOLVE_PER_CALL = 5       # 镜像解析单次 docker inspect 超时（秒）
_RESOLVE_BUDGET = 12        # 镜像解析总预算（秒）
_TOTAL_PROBE_BUDGET = 25    # 代理探测总预算（秒，须 < 30s 前端超时）
_IPV4_AGG_TIMEOUT = 12      # IPv4 分支聚合硬上限（秒）：urllib 单次 timeout 非硬上限
                            # （TLS 握手实测可突破至 13s+），故在协程级/预算级封顶，
                            # 保证 3 源串行累积不突破，且远 < _TOTAL_PROBE_BUDGET。

# /proc/net/if_inet6 flags 位：tentative(0x40) / dadfailed-duplicate(0x08) 视为未生效
_IF_INET6_UNUSABLE_FLAGS = 0x40 | 0x08

# TTL 缓存（IPv6 探测可能 spawn 一次性容器，代价高，缓存 300s）
_CACHE_TTL = 300
# started：本次缓存结果对应探测的【开始】时刻，用于 CAS 防止旧结果覆盖新结果（S4）
_cache = {"value": "", "method": "none", "error": None, "ts": 0.0, "started": 0.0}
_cache_lock = threading.Lock()

# 同步探测互斥：防止同步链路并发刷新重复 spawn 代理容器（双重检查见 _probe_ipv6_sync）
_probe_lock = threading.Lock()
# 异步探测互斥（事件循环内协程级）。跨同步/异步链路的并发由 _set_cache 的 CAS 兜底（S4）
_async_probe_lock = asyncio.Lock()

# 代理镜像解析缓存：docker inspect 每次 ~100ms 且结果在容器生命周期内不变；
# 解析失败（None）时不缓存，下次探测重试
_image_cache = {"image": None, "tool": None}

# IPv4 短 TTL 缓存（A4 可选优化，60s）：独立于 IPv6 缓存结构/锁，绝不相互覆盖。
# 仅缓存【成功】结果，绝不缓存失败——避免掩盖探测源恢复；写入带 started CAS，
# 与 IPv6 缓存同款模式，防跨同步/异步链路并发时旧结果覆盖新结果。
_IPV4_CACHE_TTL = 60
_ipv4_cache = {"value": "", "ts": 0.0, "started": 0.0}
_ipv4_cache_lock = threading.Lock()


def _get_cached_ipv4():
    """读取未过期的 IPv4 缓存；返回 dict 副本（含 from_cache=True）或 None"""
    with _ipv4_cache_lock:
        if _ipv4_cache["ts"] and time.time() - _ipv4_cache["ts"] < _IPV4_CACHE_TTL:
            return {"value": _ipv4_cache["value"], "method": "container-direct",
                    "error": None, "cached_at": _ipv4_cache["ts"], "from_cache": True}
        return None


def _set_cached_ipv4(value: str, started: float):
    """写入 IPv4 缓存（仅成功值；started CAS 防旧覆盖新）"""
    if not value:
        return
    with _ipv4_cache_lock:
        if started < _ipv4_cache.get("started", 0.0):
            return
        _ipv4_cache.update({"value": value, "ts": time.time(), "started": started})


# ===== 缓存管理 =====

def invalidate_ipv6_cache():
    """清空 IPv6 探测缓存（公开接口，M-e）。

    配置变更（如切换 access_mode / ipv6_direct / 保存网络配置）后调用，强制下次
    重新探测，避免诊断与 DNS 状态沿用最长 _CACHE_TTL(300s) 的陈旧结果。
    """
    with _cache_lock:
        _cache["ts"] = 0.0
        _cache["started"] = 0.0


# 兼容旧私有名（grep 确认全仓无其它调用点，保留别名以防外部引用）
_invalidate_cache = invalidate_ipv6_cache


def _get_cached():
    """读取未过期的缓存；返回 dict 副本（含 from_cache=True 标记）或 None"""
    with _cache_lock:
        if _cache["ts"] and time.time() - _cache["ts"] < _CACHE_TTL:
            cached = dict(_cache)
            cached["cached_at"] = cached["ts"]  # 契约键名归一：cached_at
            cached["from_cache"] = True
            return cached
        return None


def _set_cache(value: str, method: str, error, started: float):
    """写入缓存，带 CAS（S4）：若已缓存结果由【更晚开始】的探测写入，则放弃覆盖，
    防止跨同步/异步链路并发时旧探测结果覆盖新结果。"""
    with _cache_lock:
        if started < _cache.get("started", 0.0):
            return
        _cache.update({
            "value": value, "method": method, "error": error,
            "ts": time.time(), "started": started,
        })


def _fetch(url: str, timeout: int = _FETCH_TIMEOUT) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "EasyServer/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8").strip()


# ===== /proc/net/if_inet6 解析（C1 + M-a：本地判定与代理 cat 路径共用） =====

def _parse_if_inet6(text: str) -> bool:
    """解析 /proc/net/if_inet6 文本，判断是否存在【已生效的】scope-global 全球单播地址(GUA)。

    内核每行 6 字段：addr ifindex prefixlen scope flags ifname
      - addr：32 位十六进制无冒号，需重组为冒号分隔再交 IPv6Address 解析；
      - scope：parts[3] == "00" 为 global（0x00）；
      - flags：parts[4] 为十六进制，过滤 tentative(0x40)/dadfailed-duplicate(0x08)
        等尚未生效的地址；
      - 归属：addr ∈ 2000::/3 且 not is_private（排除 ULA fc00::/7）。
    本地 _has_global_ipv6() 与代理 cat 路径共用此函数，消除重复解析逻辑。
    """
    for line in (text or "").splitlines():
        parts = line.split()
        # 6 字段：addr ifindex prefixlen scope flags ifname（不足 6 字段的畸形行跳过）
        if len(parts) < 6:
            continue
        try:
            addr = ipaddress.IPv6Address(
                ":".join(parts[0][i:i + 4] for i in range(0, 32, 4))
            )
        except ValueError:
            continue
        # scope 必须为 global(00)
        if parts[3] != "00":
            continue
        # 过滤未生效地址（tentative / duplicate-dadfailed）
        try:
            flags = int(parts[4], 16)
        except ValueError:
            continue
        if flags & _IF_INET6_UNUSABLE_FLAGS:
            continue
        # 归属校验：GUA 2000::/3 且非私有（排除 ULA / link-local / loopback）
        if addr in ipaddress.IPv6Network("2000::/3") and not addr.is_private:
            return True
    return False


# ===== 本地环境判定（廉价，无网络/子进程开销） =====

def _has_global_ipv6() -> bool:
    """读本机 /proc/net/if_inet6，判断是否存在已生效的 scope-global GUA。
    文件不存在（IPv6 被禁用）或不可读时返回 False。解析逻辑见 _parse_if_inet6。
    """
    try:
        with open("/proc/net/if_inet6") as f:
            content = f.read()
    except OSError:
        return False
    return _parse_if_inet6(content)


def _in_container() -> bool:
    """多信号判定是否运行在容器内（M-d 健壮化，仅作日志信息，不作路径门控）。

    cgroup v2 + 私有 cgroupns 下容器内 /proc/1/cgroup 为 '0::/' 不含 docker 子串，
    原单一 cgroup 分支恒 False（死代码）；仅靠 /.dockerenv（runc 私产物）会假阴性。
    改为多信号 OR：
      - /.dockerenv 或 /run/.containerenv 存在；
      - /proc/self/mountinfo 含 docker/containerd/kubepods 或 'overlay / '；
      - /proc/1/comm 非 systemd/init（PID1 非宿主 init）。
    """
    if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
        return True
    try:
        with open("/proc/self/mountinfo", "rb") as f:
            mounts = f.read().decode(errors="replace")
        if any(tag in mounts for tag in ("docker", "containerd", "kubepods", "overlay / ")):
            return True
    except OSError:
        pass
    try:
        with open("/proc/1/comm", "rb") as f:
            comm = f.read().decode(errors="replace").strip()
        if comm and comm not in ("systemd", "init"):
            return True
    except OSError:
        pass
    return False


def _docker_sock_available() -> bool:
    return os.access(DOCKER_SOCK, os.R_OK | os.W_OK)


# ===== 代理镜像解析（对齐 docker_manager._core_image 的模式，M-b/M-c） =====

def _resolve_proxy_image(deadline=None) -> tuple:
    """解析 host 命名空间代理探测所用镜像，返回 (image, tool) 或 (None, None)。

    M-c：仅使用【本地已存在】的镜像，移除 busybox（无 TLS，https 探测必败且会触发 pull）：
      - 主用 _core_image() 同款解析：docker inspect easyserver-core 取 .Config.Image
        （core 镜像必在本地且内含 curl）→ tool='curl'；
      - 兜底 alpine:latest，但必须先 docker image inspect 确认本地存在才用 → tool='wget'；
      - 无任一可用本地镜像 → (None, None)，由调用方归类 probe_failed。
    所有 docker run 由调用方加 --pull=never，探测路径绝不触发 pull。
    M-b：接收绝对 deadline，每次 docker inspect 前检查剩余时间，
    timeout=min(_RESOLVE_PER_CALL, remaining)；剩余<=0 立即停止。
    """
    if _image_cache["image"]:
        return _image_cache["image"], _image_cache["tool"]
    if deadline is None:
        deadline = time.monotonic() + _RESOLVE_BUDGET

    def _run(args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None  # 预算耗尽
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=min(_RESOLVE_PER_CALL, remaining))

    # 主用：core 镜像（内含 curl）
    image = None
    try:
        result = _run(["docker", "inspect", CORE_CONTAINER,
                       "--format", "{{.Config.Image}}"])
        if result and result.returncode == 0 and result.stdout.strip():
            image = result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        image = None
    if image:
        _image_cache.update({"image": image, "tool": "curl"})
        return image, "curl"

    # 兜底：alpine（必须本地已存在），用 wget（IPv6-only 域名，解析器必走 IPv6）
    try:
        result = _run(["docker", "image", "inspect", ALPINE_FALLBACK])
        if result and result.returncode == 0:
            _image_cache.update({"image": ALPINE_FALLBACK, "tool": "wget"})
            return ALPINE_FALLBACK, "wget"
    except (subprocess.TimeoutExpired, OSError):
        pass

    # 无可用本地镜像（或预算耗尽）→ 不缓存，返回 (None, None)
    return None, None


def _proxy_cat_cmd(image: str) -> list:
    """构造读取宿主 /proc/net/if_inet6 的一次性容器命令（C1 确定性判定第一步）"""
    return ["docker", "run", "--rm", "--network", "host", "--pull=never",
            "--entrypoint", "cat", image, "/proc/net/if_inet6"]


def _proxy_cmd(image: str, tool: str, url: str, timeout: int) -> list:
    """构造一次性代理容器探测命令（对齐 docker_manager._write_host_file 的
    docker run --rm --entrypoint 模式，宿主网络命名空间）。
    M-c：一律 --pull=never；S5：curl 用 -sS 使 stderr 输出错误行供排障。"""
    base = ["docker", "run", "--rm", "--network", "host", "--pull=never", "--entrypoint"]
    if tool == "curl":
        return base + ["curl", image, "-6", "-sS", "--max-time", str(timeout), url]
    # alpine busybox wget：-T 为连接超时；IPv6 探测源为 IPv6-only 域名，必走 IPv6
    return base + ["wget", image, "-qO-", "-T", str(timeout), url]


def _parse_ipv6(text: str) -> str:
    """严格校验探测输出为合法 IPv6 地址（S2），返回原始字符串（非法返回空）。
    ipaddress.IPv6Address 严格解析，防探测源返回含冒号的非 IP 正文被缓存并流入
    dns.py _build_targets 拼成垃圾 AAAA 提交给云 API。"""
    text = (text or "").strip()
    if not text or ":" not in text:
        return ""
    try:
        ipaddress.IPv6Address(text)
    except ValueError:
        return ""
    return text


# ===== host 命名空间代理探测（C1 确定性判定 + M-b 预算 + S1/S3/S5） =====

def _probe_ipv6_via_docker_sync(deadline=None) -> dict:
    """同步 host 命名空间代理探测（subprocess.run，供同步入口使用）。

    流程：解析镜像 → cat /proc/net/if_inet6 确定性判定 no_ipv6 → 有 GUA 才 curl -6 三源。
    """
    def _fail(error):
        return {"value": "", "method": "host-namespace", "error": error}

    if not _docker_sock_available():
        return _fail("容器无 IPv6 且 docker socket 不可用")
    start = time.monotonic()
    if deadline is None:
        deadline = start + _TOTAL_PROBE_BUDGET
    resolve_deadline = min(start + _RESOLVE_BUDGET, deadline)

    image, tool = _resolve_proxy_image(resolve_deadline)
    if image is None:
        return _fail("无可用代理镜像（core/alpine 均不在本地）")

    # 第一步：确定性读取宿主 IPv6 路由表
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return _fail("IPv6 探测超时，预算耗尽")
    try:
        cat = subprocess.run(_proxy_cat_cmd(image), capture_output=True, text=True,
                             timeout=min(_SUBPROC_TIMEOUT, remaining))
    except subprocess.TimeoutExpired:
        return _fail("读取宿主 IPv6 路由表超时")
    except OSError as e:
        return _fail(f"无法执行 docker 命令：{e}")
    if cat.returncode != 0:
        err = (cat.stderr or "").strip().splitlines()
        return _fail(f"读取宿主 IPv6 路由表失败：{err[-1][:80] if err else 'exit ' + str(cat.returncode)}")
    if not _parse_if_inet6(cat.stdout):
        # 宿主无已生效 GUA → 确定性 no_ipv6（前端不告警）
        return {"value": "", "method": "host-namespace", "error": None}

    # 第二步：宿主有 GUA，curl -6 三源探测取首个成功
    failures = []
    for url in IPV6_PROVIDERS:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _fail(f"IPv6 探测超时，预算耗尽：{'; '.join(failures)}")
        subproc_t = min(_SUBPROC_TIMEOUT, remaining)
        curl_t = min(_CURL_TIMEOUT, max(1, int(subproc_t) - 1))
        try:
            res = subprocess.run(_proxy_cmd(image, tool, url, curl_t),
                                 capture_output=True, text=True, timeout=subproc_t)
        except subprocess.TimeoutExpired:
            failures.append(f"{url} (subprocess timeout)")
            continue
        except OSError as e:
            return _fail(f"无法执行 docker 命令：{e}")
        if res.returncode == 0:
            ip = _parse_ipv6(res.stdout)
            if ip:
                return {"value": ip, "method": "host-namespace", "error": None}
        err = (res.stderr or "").strip().splitlines()
        failures.append(f"{url} (exit {res.returncode}: {err[-1][:80] if err else 'no output'})")
    return _fail(f"宿主有 IPv6 但所有探测源不可达：{'; '.join(failures)}")


async def _probe_ipv6_via_docker_async(deadline=None) -> dict:
    """异步 host 命名空间代理探测（asyncio.create_subprocess_exec，
    对齐 docker_manager._write_host_file 的既有模式）。流程与同步版一致。

    S1：循环体开头 proc=None；超时 handler 里 proc.kill() 后 await proc.wait() 回收，
    防僵尸并让 --rm 清理代理容器（不再捕获 UnboundLocalError 误 kill 上一轮进程）。
    S3：拆分 asyncio.TimeoutError 与 OSError，Py3.11 下 TimeoutError.str() 为空，
    避免产出"解析失败:"空原因直显前端。
    """
    def _fail(error):
        return {"value": "", "method": "host-namespace", "error": error}

    if not _docker_sock_available():
        return _fail("容器无 IPv6 且 docker socket 不可用")
    start = time.monotonic()
    if deadline is None:
        deadline = start + _TOTAL_PROBE_BUDGET
    resolve_deadline = min(start + _RESOLVE_BUDGET, deadline)

    # M-b：resolve 靠子进程自身 timeout 封顶；wait_for 仅作二次护栏（to_thread 不可取消）
    try:
        image, tool = await asyncio.wait_for(
            asyncio.to_thread(_resolve_proxy_image, resolve_deadline),
            timeout=_RESOLVE_BUDGET)
    except asyncio.TimeoutError:
        return _fail(f"代理镜像解析超时 >{_RESOLVE_BUDGET}s，daemon 无响应")
    except OSError as e:
        return _fail(f"代理镜像解析失败：{e}")
    if image is None:
        return _fail("无可用代理镜像（core/alpine 均不在本地）")

    # 第一步：确定性读取宿主 IPv6 路由表
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return _fail("IPv6 探测超时，预算耗尽")
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *_proxy_cat_cmd(image),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=min(_SUBPROC_TIMEOUT, remaining))
    except asyncio.TimeoutError:
        if proc is not None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
        return _fail("读取宿主 IPv6 路由表超时")
    except OSError as e:
        return _fail(f"无法执行 docker 命令：{e}")
    if proc.returncode != 0:
        err = (stderr.decode(errors="replace") or "").strip().splitlines()
        return _fail(f"读取宿主 IPv6 路由表失败：{err[-1][:80] if err else 'exit ' + str(proc.returncode)}")
    if not _parse_if_inet6(stdout.decode(errors="replace")):
        return {"value": "", "method": "host-namespace", "error": None}

    # 第二步：宿主有 GUA，curl -6 三源探测
    failures = []
    for url in IPV6_PROVIDERS:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _fail(f"IPv6 探测超时，预算耗尽：{'; '.join(failures)}")
        subproc_t = min(_SUBPROC_TIMEOUT, remaining)
        curl_t = min(_CURL_TIMEOUT, max(1, int(subproc_t) - 1))
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *_proxy_cmd(image, tool, url, curl_t),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=subproc_t)
        except asyncio.TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()
            failures.append(f"{url} (timeout)")
            continue
        except OSError as e:
            return _fail(f"无法执行 docker 命令：{e}")
        if proc.returncode == 0:
            ip = _parse_ipv6(stdout.decode(errors="replace"))
            if ip:
                return {"value": ip, "method": "host-namespace", "error": None}
        err = (stderr.decode(errors="replace") or "").strip().splitlines()
        failures.append(f"{url} (exit {proc.returncode}: {err[-1][:80] if err else 'no output'})")
    return _fail(f"宿主有 IPv6 但所有探测源不可达：{'; '.join(failures)}")


# ===== 探测主流程 =====

def _probe_ipv4_sync(deadline=None) -> dict:
    """IPv4 直连探测（容器网络有 IPv4 出口，无需代理）。

    A1：源已实证优选（checkip.amazonaws / ipinfo.io / ifconfig.me，剔除永久失效源）。
    A2/A3：接收绝对 deadline，每源探测前检查剩余预算，per-call timeout=min(_FETCH_TIMEOUT,
    remaining)，避免 3 源串行累积突破总预算；默认 deadline=start+_IPV4_AGG_TIMEOUT。
    A4：命中短 TTL 缓存直返；探测成功写缓存（仅成功值）。
    向后兼容：无参调用语义与原实现一致——成功返回 value；全败返回 value='' + error 可读原因。
    """
    cached = _get_cached_ipv4()
    if cached:
        return cached
    started = time.time()
    start = time.monotonic()
    if deadline is None:
        deadline = start + _IPV4_AGG_TIMEOUT
    failures = []
    for url in IPV4_PROVIDERS:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            failures.append(f"{url}: 预算耗尽未尝试")
            break
        try:
            # per-call 上限：min(单次超时, 剩余预算)，封住串行累积
            ip = _fetch(url, timeout=min(_FETCH_TIMEOUT, remaining))
            if ip:
                _set_cached_ipv4(ip, started)
                return {"value": ip, "method": "container-direct", "error": None,
                        "cached_at": time.time(), "from_cache": False}
        except Exception as e:
            failures.append(f"{url}: {e}")
    return {"value": "", "method": "container-direct",
            "error": f"所有 IPv4 探测源不可达：{'; '.join(failures)}" if failures else "所有 IPv4 探测源不可达",
            "cached_at": time.time(), "from_cache": False}


async def _probe_ipv4_async() -> dict:
    """IPv4 异步探测：to_thread 跑同步探测 + 协程级聚合硬上限 _IPV4_AGG_TIMEOUT（A2）。

    urllib 为同步阻塞 IO，TLS 握手可能突破单次 timeout（实测 13s+）；to_thread 底层
    线程不可取消，但 wait_for 到点即返回超时结果，主流程不再阻塞，后台线程自然收敛。
    返回值形态与 _probe_ipv4_sync 一致（永不抛异常）。
    """
    deadline = time.monotonic() + _IPV4_AGG_TIMEOUT
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_probe_ipv4_sync, deadline),
            timeout=_IPV4_AGG_TIMEOUT)
    except asyncio.TimeoutError:
        return {"value": "", "method": "container-direct",
                "error": f"IPv4 探测超时 >{_IPV4_AGG_TIMEOUT}s（聚合硬上限，可能 TLS 握手阻塞）",
                "cached_at": time.time(), "from_cache": False}


def _probe_ipv6_direct_sync() -> dict:
    """urllib 直连 IPv6 探测（本机有 GUA，或宿主/开发模式无 socket 兜底）。

    S2：复用 _parse_ipv6() 严格校验，替代弱判定 ':' in ip。
    取舍：直连模式无法区分"本机无 IPv6 出口"与"探测源故障"，为保持向后兼容的
    "失败返回空"语义，失败一律按 no_ipv6（error=None）处理。
    """
    for url in IPV6_PROVIDERS:
        try:
            ip = _parse_ipv6(_fetch(url))
            if ip:
                return {"value": ip, "method": "container-direct", "error": None}
        except Exception:
            continue
    return {"value": "", "method": "container-direct", "error": None}


def _probe_ipv6_sync() -> dict:
    """同步 IPv6 探测主流程（含路径选择 + 并发互斥 + 双重检查缓存 + CAS 写入）。

    路径选择（M-d）：
    1. 本机有已生效 GUA → urllib 直连（container-direct）；
    2. 否则 docker.sock 可用 → host 命名空间代理探测（host-namespace）；
    3. 否则 → urllib 直连兜底（best effort，宿主/开发模式）。
    """
    cached = _get_cached()
    if cached:
        return cached
    started = time.time()
    with _probe_lock:
        # 双重检查：等锁期间其他线程可能已完成刷新，避免重复 spawn 容器
        cached = _get_cached()
        if cached:
            return cached
        has_gua = _has_global_ipv6()
        if has_gua:
            result = _probe_ipv6_direct_sync()
        elif _docker_sock_available():
            result = _probe_ipv6_via_docker_sync()
        else:
            result = _probe_ipv6_direct_sync()
        logger.debug("IPv6 同步探测：in_container=%s has_gua=%s method=%s error=%s",
                     _in_container(), has_gua, result.get("method"), result.get("error"))
        result["cached_at"] = time.time()
        result["from_cache"] = False
        _set_cache(result["value"], result["method"], result["error"], started)
        return result


async def _probe_ipv6_async() -> dict:
    """异步 IPv6 探测主流程（路径选择与同步版一致）"""
    cached = await asyncio.to_thread(_get_cached)
    if cached:
        return cached
    started = time.time()
    async with _async_probe_lock:
        cached = await asyncio.to_thread(_get_cached)
        if cached:
            return cached
        has_gua = _has_global_ipv6()
        if has_gua:
            # urllib 为同步阻塞 IO，放入线程池避免阻塞事件循环
            result = await asyncio.to_thread(_probe_ipv6_direct_sync)
        elif _docker_sock_available():
            result = await _probe_ipv6_via_docker_async()
        else:
            result = await asyncio.to_thread(_probe_ipv6_direct_sync)
        logger.debug("IPv6 异步探测：in_container=%s has_gua=%s method=%s error=%s",
                     _in_container(), has_gua, result.get("method"), result.get("error"))
        result["cached_at"] = time.time()
        result["from_cache"] = False
        await asyncio.to_thread(
            _set_cache, result["value"], result["method"], result["error"], started)
        return result


# ===== 结构化探测接口 =====

def get_public_ipv6_detailed() -> dict:
    """结构化 IPv6 探测（同步入口，带 TTL 缓存）

    返回 {value: str, method: str, error: str|None, cached_at: float}
    - value 非空 → error 为 None，method ∈ {'host-namespace', 'container-direct'}
    - value 空且 error 为 None → 确认宿主无公网 IPv6（no_ipv6）
    - value 空且 error 非空 → 探测失败（probe_failed），error 为可读原因
    """
    return _probe_ipv6_sync()


async def aget_public_ipv6_detailed() -> dict:
    """结构化 IPv6 探测（异步入口，不阻塞事件循环）"""
    return await _probe_ipv6_async()


def get_public_ipv4_detailed() -> dict:
    """结构化 IPv4 探测（同步直连，接口形态与 IPv6 版对齐）"""
    return _probe_ipv4_sync()


async def aget_public_ips_detailed() -> dict:
    """异步探测 IPv4 + IPv6，供 async 路由使用（消除事件循环阻塞）

    返回：ipv4 / ipv6 / record_types（与 get_public_ips 同构），
    另含 ipv6_source（探测方法，缓存命中时由消费方映射为 'cache'，未探得为 'none'）、
    ipv6_error（探测失败原因，成功或确无 IPv6 时为 None）、
    ipv6_from_cache（是否命中 TTL 缓存，供路由映射 public_ipv6_source='cache'）、
    ipv4_error（IPv4 探测失败原因，成功时为 None，与 ipv6_error 对称，A4）。

    A3：IPv4 与 IPv6 【并发】（asyncio.gather）而非串行——IPv4 分支自身封顶
    _IPV4_AGG_TIMEOUT(12s)，IPv6 分支走内部预算；外层再对整体加聚合上限
    _TOTAL_PROBE_BUDGET(25s)，保证 diagnostics 端到端 < 前端 30s（即使 IPv6 直连
    路径 urllib TLS 握手突破，外层 wait_for 亦兜底封顶，绝不突破前端超时）。
    """
    try:
        ipv4_result, ipv6_result = await asyncio.wait_for(
            asyncio.gather(_probe_ipv4_async(), _probe_ipv6_async()),
            timeout=_TOTAL_PROBE_BUDGET)
    except asyncio.TimeoutError:
        # 整体聚合预算耗尽（极端病理：如 IPv6 直连路径多源 TLS 握手连环突破）。
        # 双空 + 可读原因，绝不突破前端 30s；下次调用重新探测。
        reason = f"IP 探测总预算耗尽 >{_TOTAL_PROBE_BUDGET}s"
        return {
            "ipv4": "", "ipv6": "", "record_types": [],
            "ipv6_source": "none", "ipv6_error": reason,
            "ipv6_from_cache": False, "ipv4_error": reason,
        }
    ipv6 = ipv6_result["value"]
    method = ipv6_result.get("method", "none")
    return {
        "ipv4": ipv4_result["value"],
        "ipv6": ipv6,
        # 推荐的记录类型：有 IPv6 则同时创建 AAAA，否则只创建 A（逻辑保持不变）
        "record_types": (["AAAA", "A"] if ipv6 else ["A"])
                        if (ipv4_result["value"] or ipv6) else [],
        "ipv6_source": method if (ipv6 or ipv6_result.get("error")) else "none",
        "ipv6_error": ipv6_result.get("error"),
        "ipv6_from_cache": bool(ipv6_result.get("from_cache")),
        "ipv4_error": ipv4_result.get("error"),
    }


# ===== 向后兼容接口（签名/返回类型/"失败返回空字符串"语义不变） =====

def get_public_ipv4() -> str:
    """获取公网 IPv4 地址（失败返回空字符串）"""
    return get_public_ipv4_detailed()["value"]


def get_public_ipv6() -> str:
    """获取公网 IPv6 地址（失败返回空字符串，表示服务器无公网 IPv6 或探测失败）"""
    return get_public_ipv6_detailed()["value"]


def get_public_ips() -> dict:
    """同时探测 IPv4 与 IPv6，返回检测结果（字段与语义保持不变）"""
    ipv4 = get_public_ipv4()
    ipv6 = get_public_ipv6()
    return {
        "ipv4": ipv4,
        "ipv6": ipv6,
        # 推荐的记录类型：有 IPv6 则同时创建 AAAA，否则只创建 A
        "record_types": (["AAAA", "A"] if ipv6 else ["A"]) if ipv4 or ipv6 else [],
    }
