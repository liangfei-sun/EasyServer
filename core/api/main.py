"""
EasyServer API - FastAPI 入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi import Request
from fastapi.responses import FileResponse, Response
from starlette.routing import Route
import os
import shutil

from .routes import services, config, modules, nginx, docs, backup
from .core.auth import AuthMiddleware

app = FastAPI(
    title="EasyServer API",
    description="个人服务器一站式管理引擎",
    version="0.2.4"
)

# CORS 配置：从环境变量或 config.yaml 动态读取允许的域名
_cors_origins = ["http://127.0.0.1:8900", "http://localhost:8900"]
_cors_origins_str = os.environ.get("CORS_ORIGINS", "")
if _cors_origins_str:
    _cors_origins = [o.strip() for o in _cors_origins_str.split(",") if o.strip()]
else:
    # 尝试从 config.yaml 读取域名，容错处理（setup 阶段可能不存在）
    try:
        from .core.config_manager import ConfigManager
        _cm = ConfigManager(os.environ.get("EASYSERVER_ROOT", "/app"))
        _cfg = _cm.load_config()
        _domain = _cfg.get("domain", "")
        if _domain:
            _cors_origins.append(f"https://{_domain}")
            _cors_origins.append(f"https://*.{_domain}")
    except Exception:
        pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 鉴权中间件
app.add_middleware(AuthMiddleware)

# 注册路由
app.include_router(services.router)
app.include_router(config.router)
app.include_router(modules.router)
app.include_router(nginx.router)
app.include_router(docs.router)
app.include_router(backup.router)


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "easyserver-core"}


def _get_system_resources() -> dict:
    """获取系统资源使用情况（使用标准库，无需额外依赖）"""
    # 内存信息：读取 /proc/meminfo
    mem_total = mem_used = mem_percent = 0
    try:
        with open("/proc/meminfo", "r") as f:
            meminfo = {}
            for line in f:
                parts = line.split()
                if parts[0] in ("MemTotal:", "MemAvailable:", "MemFree:", "Buffers:", "Cached:"):
                    meminfo[parts[0].rstrip(":")] = int(parts[1])  # kB
            mem_total_kb = meminfo.get("MemTotal", 0)
            mem_available_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
            mem_used_kb = mem_total_kb - mem_available_kb
            mem_total = round(mem_total_kb / 1024)  # MB
            mem_used = round(mem_used_kb / 1024)
            mem_percent = round(mem_used_kb / mem_total_kb * 100) if mem_total_kb > 0 else 0
    except Exception:
        pass

    # 磁盘信息：shutil.disk_usage
    disk_total = disk_used = disk_percent = 0
    try:
        usage = shutil.disk_usage("/")
        disk_total = round(usage.total / (1024 ** 3), 1)  # GB
        disk_used = round(usage.used / (1024 ** 3), 1)
        disk_percent = round(usage.used / usage.total * 100) if usage.total > 0 else 0
    except Exception:
        pass

    # CPU 使用率：读取 /proc/stat 两次采样计算
    cpu_percent = 0
    try:
        import time
        def _read_cpu_stat():
            with open("/proc/stat", "r") as f:
                parts = f.readline().split()
            vals = [int(x) for x in parts[1:]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
            total = sum(vals)
            return idle, total
        idle1, total1 = _read_cpu_stat()
        time.sleep(0.3)
        idle2, total2 = _read_cpu_stat()
        idle_delta = idle2 - idle1
        total_delta = total2 - total1
        if total_delta > 0:
            cpu_percent = round((1 - idle_delta / total_delta) * 100, 1)
    except Exception:
        pass

    return {
        "cpu": cpu_percent,
        "memUsed": mem_used,
        "memTotal": mem_total,
        "memPercent": mem_percent,
        "diskUsed": disk_used,
        "diskTotal": disk_total,
        "diskPercent": disk_percent,
    }


@app.get("/api/info")
async def system_info():
    """系统信息（含资源使用）"""
    resources = _get_system_resources()
    return {
        "name": "EasyServer",
        "version": "0.2.4",
        "description": "个人服务器一站式部署方案",
        **resources,
    }


# 静态文件服务（Vue 前端）
PROJECT_ROOT = os.environ.get("EASYSERVER_ROOT", "/app")
WEB_DIST = os.path.join(PROJECT_ROOT, "core", "web", "dist")

if os.path.isdir(WEB_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(WEB_DIST, "assets")), name="assets")

    async def serve_frontend(request: Request):
        """所有未匹配的路由返回前端 index.html（SPA 支持）"""
        index_path = os.path.join(WEB_DIST, "index.html")
        if request.method == "HEAD":
            if os.path.exists(index_path):
                return Response(status_code=200)
            return Response(status_code=404)
        if os.path.exists(index_path):
            return FileResponse(
                index_path,
                headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
            )
        return {"message": "EasyServer API is running. Web UI not built yet."}

    app.router.routes.append(
        Route("/{full_path:path}", serve_frontend, methods=["GET", "HEAD"])
    )
else:
    @app.get("/")
    async def root():
        return {
            "message": "EasyServer API is running",
            "docs": "/docs",
            "api": "/api/health"
        }
