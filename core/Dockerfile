# ============================================================
# EasyServer 自包含镜像
# 构建上下文：项目根目录（docker compose build 时 context 设为 .）
# ============================================================

# 阶段1：构建前端
FROM node:20-alpine AS frontend-builder
WORKDIR /build
COPY core/web/package*.json ./
RUN npm install
COPY core/web/ ./
RUN npm run build

# 阶段2：Python 运行时
FROM python:3.11-slim

# 安装运行时依赖：curl 用于健康检查，Docker CLI 用于管理模块容器
RUN apt-get update && apt-get install -y ca-certificates curl gnupg && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update && apt-get install -y docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依赖
COPY core/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 后端代码
COPY core/__init__.py /app/core/__init__.py
COPY core/api/ /app/core/api/

# 前端构建产物
COPY --from=frontend-builder /build/dist/ /app/core/web/dist/

# 模块模板（首次启动时复制到宿主机数据目录）
COPY modules/ /app/modules_template/

# 环境变量模板
COPY .env.example /app/.env.example

# 运维脚本
COPY scripts/ /app/scripts/

# 文档文件
COPY docs/ /app/docs/

# 入口脚本
COPY core/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
