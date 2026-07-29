# 阶段1：构建前端
FROM node:20-alpine AS frontend-builder
WORKDIR /build
COPY web/package*.json ./
RUN npm install
COPY web/ ./
RUN npm run build

# 阶段2：Python 后端
FROM python:3.11-slim

WORKDIR /app

# 安装 curl（Docker CLI 通过 docker-compose 从宿主机挂载）
RUN apt-get update && apt-get install -y curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY __init__.py ./core/
COPY api/ ./core/api/

# 复制前端构建产物
COPY --from=frontend-builder /build/dist/ ./core/web/dist/

EXPOSE 8000

CMD ["uvicorn", "core.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
