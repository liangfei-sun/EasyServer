#!/bin/bash
set -e
set -o pipefail

# ============================================================
# EasyServer 容器入口脚本
# 职责：初始化配置、数据目录、Docker 网络、模块模板，然后启动应用
# ============================================================

DATA_DIR="${DATA_DIR:-/data}"
PROJECT_ROOT="${PROJECT_ROOT:-/easyserver_data}"

log() {
    echo "[entrypoint] $*"
}

# ---- 1. 初始化持久化配置（.env / config.yaml）----
# 运行时 .env 与 config.yaml 落在 DATA_DIR 持久卷（容器内 /data → 宿主 data/），
# 与 ConfigManager / DockerManager / NginxGenerator 读写路径一致；
# 容器重建后不丢失（含 UI 写入的端口、Token 及 setup 生成的 JWT_SECRET）。
mkdir -p "${DATA_DIR}"
ENV_FILE="${DATA_DIR}/.env"
CONFIG_FILE="${DATA_DIR}/config.yaml"

# ---- 1a. 旧布局一次性迁移（防御性兜底 + WARN）----
# 注意：跨容器 recreate 时旧可写层已销毁，此兜底主要覆盖“同容器内路径切换”；
# 真正可靠的迁移是运维步骤（升级前把配置放入宿主 data/），由部署流程处理。
if [ ! -f "${CONFIG_FILE}" ] && [ -f /app/data/config.yaml ]; then
    cp /app/data/config.yaml "${CONFIG_FILE}"
    log "WARN: 检测到旧布局 /app/data/config.yaml，已迁移到持久卷 ${CONFIG_FILE}"
    log "WARN: 该兜底不覆盖容器 recreate 场景，请确认宿主 data/ 已包含最新配置"
fi
if [ ! -f "${ENV_FILE}" ] && [ -f /app/.env ]; then
    cp /app/.env "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    log "WARN: 检测到旧布局 /app/.env，已迁移到持久卷 ${ENV_FILE}"
    log "WARN: 该兜底不覆盖容器 recreate 场景，请确认宿主 data/ 已包含最新配置"
fi

# ---- 1b. 首启播种 .env（持久卷与旧布局均无时，从模板生成）----
if [ ! -f "${ENV_FILE}" ]; then
    log "未检测到持久化 .env，从模板生成: ${ENV_FILE}"
    cp /app/.env.example "${ENV_FILE}"
    sed -i "s|^DATA_DIR=.*|DATA_DIR=${DATA_DIR}|" "${ENV_FILE}"
    sed -i "s|^PROJECT_ROOT=.*|PROJECT_ROOT=${PROJECT_ROOT}|" "${ENV_FILE}"
    chmod 600 "${ENV_FILE}"
    log ".env 已生成（DATA_DIR=${DATA_DIR}, PROJECT_ROOT=${PROJECT_ROOT}）"
else
    log ".env 已存在于持久卷，跳过生成: ${ENV_FILE}"
fi

# ---- 2. 确保数据目录存在 ----
mkdir -p "${DATA_DIR}/backups"
log "数据目录已就绪: ${DATA_DIR}"

# ---- 3. 创建 Docker 网络（幂等） ----
if docker network inspect easyserver-proxy >/dev/null 2>&1; then
    log "Docker 网络 easyserver-proxy 已存在"
else
    log "创建 Docker 网络 easyserver-proxy..."
    if ! docker network create easyserver-proxy 2>/tmp/net_create_err; then
        # 可能是并发创建导致的竞争条件，再次检查
        if docker network inspect easyserver-proxy >/dev/null 2>&1; then
            log "Docker 网络 easyserver-proxy 已由其他进程创建"
        else
            log "警告: Docker 网络创建失败: $(cat /tmp/net_create_err)"
            log "请确保 Docker 守护进程正在运行且有足够权限"
        fi
    else
        log "Docker 网络 easyserver-proxy 创建成功"
    fi
fi

# ---- 4. 初始化 modules 目录 ----
# 如果宿主机 modules 目录缺少注册表，从镜像内模板复制
if [ ! -f "${PROJECT_ROOT}/modules/_registry.yaml" ]; then
    log "首次启动：从镜像模板初始化 modules 目录..."
    mkdir -p "${PROJECT_ROOT}/modules"
    cp -r /app/modules_template/* "${PROJECT_ROOT}/modules/"
    log "modules 目录已初始化"
else
    log "modules 目录已存在，跳过初始化"
fi

# ---- 5. 处理 --sync-modules 参数：手动同步模块模板 ----
if [ "$1" = "--sync-modules" ]; then
    log "同步模块模板到 ${PROJECT_ROOT}/modules/ ..."
    cp -rn /app/modules_template/* "${PROJECT_ROOT}/modules/" 2>/dev/null || true
    log "模块同步完成（仅新增，不覆盖已有）"
    shift
fi

# ---- 6. 路径可达性检查 ----
if [ ! -d "${PROJECT_ROOT}/modules" ]; then
    log "错误: modules 目录不存在: ${PROJECT_ROOT}/modules，请检查 PROJECT_ROOT 配置"
    exit 1
fi
if [ ! -d "${DATA_DIR}" ]; then
    log "错误: 数据目录不可访问: ${DATA_DIR}，请检查 DATA_DIR 配置"
    exit 1
fi

# ---- 7. 启动应用 ----
log "启动 EasyServer 核心引擎..."
exec uvicorn core.api.main:app --host 0.0.0.0 --port 8000 "$@"
