"""
EasyServer Auth - JWT 鉴权中间件
"""
import hashlib
import hmac
import json
import time
import base64
import os
import secrets
import logging
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# JWT 密钥（从环境变量读取，未设置则每次启动随机生成）
_env_jwt_secret = os.environ.get("JWT_SECRET")
if _env_jwt_secret:
    JWT_SECRET = _env_jwt_secret
else:
    JWT_SECRET = secrets.token_hex(32)
    logger.warning("JWT_SECRET 环境变量未设置，已使用随机密钥。"
                   "重启后所有现有 Token 将失效，建议设置 JWT_SECRET 环境变量。")
JWT_EXPIRE_SECONDS = 7 * 24 * 3600  # 7 天

# 白名单路径：不需要鉴权
WHITELIST_PATHS = {
    "/api/health",
    "/api/config/auth/login",
    "/api/config/setup/status",
}

# Setup 阶段白名单前缀（setup 未完成时仅放行 setup 接口）
SETUP_WHITELIST_PREFIX = "/api/config/setup"

# ── 登录速率限制（基于 IP，内存字典） ──
_login_attempts: dict[str, dict] = {}  # {ip: {"count": int, "window_start": float}}
LOGIN_RATE_LIMIT_MAX = 10        # 每个窗口最大尝试次数
LOGIN_RATE_LIMIT_WINDOW = 60     # 窗口大小（秒）


def check_login_rate_limit(client_ip: str) -> bool:
    """检查 IP 是否超出登录速率限制，返回 True 表示允许。"""
    now = time.time()
    record = _login_attempts.get(client_ip)
    if record is None:
        return True
    # 窗口已过期，重置
    if now - record["window_start"] >= LOGIN_RATE_LIMIT_WINDOW:
        del _login_attempts[client_ip]
        return True
    return record["count"] < LOGIN_RATE_LIMIT_MAX


def record_login_attempt(client_ip: str) -> None:
    """记录一次登录尝试。"""
    now = time.time()
    record = _login_attempts.get(client_ip)
    if record is None or now - record["window_start"] >= LOGIN_RATE_LIMIT_WINDOW:
        _login_attempts[client_ip] = {"count": 1, "window_start": now}
    else:
        record["count"] += 1


def reset_login_rate_limit(client_ip: str) -> None:
    """登录成功后重置该 IP 的计数器。"""
    _login_attempts.pop(client_ip, None)


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

        # Setup 阶段：放行 setup 相关接口
        if path.startswith(SETUP_WHITELIST_PREFIX):
            return await call_next(request)

        # 检查 setup 状态，未完成时返回 401（setup 路径已在上方放行）
        try:
            from .config_manager import ConfigManager
            cm = ConfigManager(os.environ.get("EASYSERVER_ROOT", "/app"))
            if not cm.is_setup_completed():
                return JSONResponse(
                    status_code=401,
                    content={"detail": "系统尚未完成初始化配置"}
                )
        except Exception:
            pass

        # 验证 Token（仅从 Authorization header 获取）
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = ""

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
