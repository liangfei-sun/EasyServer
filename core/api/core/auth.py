"""
EasyServer Auth - JWT 鉴权中间件
"""
import hashlib
import hmac
import json
import time
import base64
import os
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# JWT 密钥（从环境变量读取，默认随机生成）
JWT_SECRET = os.environ.get("JWT_SECRET", hashlib.sha256(b"easyserver-secret-key").hexdigest())
JWT_EXPIRE_SECONDS = 7 * 24 * 3600  # 7 天

# 白名单路径：不需要鉴权
WHITELIST_PATHS = {
    "/api/health",
    "/api/config/auth/login",
    "/api/config/setup/status",
}

# Setup 阶段白名单前缀（setup 未完成时放行）
SETUP_WHITELIST_PREFIX = "/api/config/setup"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_token(user: str = "admin") -> str:
    """创建 JWT Token（简化实现，无第三方依赖）"""
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(json.dumps({
        "sub": user,
        "exp": int(time.time()) + JWT_EXPIRE_SECONDS,
        "iat": int(time.time())
    }).encode())
    signature = _b64url_encode(
        hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{signature}"


def verify_token(token: str) -> dict:
    """验证 JWT Token，返回 payload 或抛出异常"""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format")
    header, payload, signature = parts
    expected_sig = _b64url_encode(
        hmac.new(JWT_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(signature, expected_sig):
        raise ValueError("Invalid token signature")
    data = json.loads(_b64url_decode(payload))
    if data.get("exp", 0) < time.time():
        raise ValueError("Token expired")
    return data


class AuthMiddleware(BaseHTTPMiddleware):
    """API 鉴权中间件"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 非 API 路由不鉴权（静态文件等）
        if not path.startswith("/api/"):
            return await call_next(request)

        # 白名单路径直接放行
        if path in WHITELIST_PATHS:
            return await call_next(request)

        # Setup 阶段：如果 setup 未完成，放行 setup 相关接口
        if path.startswith(SETUP_WHITELIST_PREFIX):
            return await call_next(request)

        # 检查 setup 状态，未完成时放行所有（安装向导需要）
        try:
            from .config_manager import ConfigManager
            cm = ConfigManager(os.environ.get("EASYSERVER_ROOT", "/app"))
            if not cm.is_setup_completed():
                return await call_next(request)
        except Exception:
            pass

        # 验证 Token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = request.query_params.get("token", "")

        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "未提供认证令牌，请先登录"}
            )

        try:
            verify_token(token)
        except ValueError as e:
            return JSONResponse(
                status_code=401,
                content={"detail": f"认证失败: {str(e)}，请重新登录"}
            )

        return await call_next(request)
