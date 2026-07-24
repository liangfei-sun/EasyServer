"""
EasyServer API - FastAPI 入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from .routes import services, config, modules, nginx

app = FastAPI(
    title="EasyServer API",
    description="个人服务器一站式管理引擎",
    version="1.0.0"
)

# CORS 配置（允许前端开发时跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(services.router)
app.include_router(config.router)
app.include_router(modules.router)
app.include_router(nginx.router)


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "easyserver-core"}


@app.get("/api/info")
async def system_info():
    """系统信息"""
    return {
        "name": "EasyServer",
        "version": "1.0.0",
        "description": "个人服务器一站式部署方案"
    }


# 静态文件服务（Vue 前端）
PROJECT_ROOT = os.environ.get("EASYSERVER_ROOT", "/app")
WEB_DIST = os.path.join(PROJECT_ROOT, "api", "..", "web", "dist")

if os.path.isdir(WEB_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(WEB_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """所有未匹配的路由返回前端 index.html（SPA 支持）"""
        index_path = os.path.join(WEB_DIST, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "EasyServer API is running. Web UI not built yet."}
else:
    @app.get("/")
    async def root():
        return {
            "message": "EasyServer API is running",
            "docs": "/docs",
            "api": "/api/health"
        }
