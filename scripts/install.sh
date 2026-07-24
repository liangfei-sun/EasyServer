#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# EasyServer 安装脚本
# 用法: curl -fsSL https://raw.githubusercontent.com/liangfei-sun/EasyServer/main/scripts/install.sh | bash
# ============================================================

EASYSERVER_ROOT="${EASYSERVER_ROOT:-$HOME/easyserver}"
REPO_URL="${REPO_URL:-https://github.com/liangfei-sun/EasyServer.git}"

RED='[0;31m'
GREEN='[0;32m'
YELLOW='[1;33m'
BLUE='[0;34m'
NC='[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*" >&2; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

check_docker() {
    if ! command -v docker &>/dev/null; then
        warn "Docker 未安装，正在安装..."
        curl -fsSL https://get.docker.com | bash
        systemctl enable docker 2>/dev/null || true
        systemctl start docker 2>/dev/null || true
        ok "Docker 安装完成"
    fi
    if ! docker compose version &>/dev/null; then
        err "Docker Compose 插件未找到，请手动安装"
        exit 1
    fi
    ok "Docker $(docker --version) 就绪"
    ok "Compose $(docker compose version --short) 就绪"
}

setup_project() {
    if [ -d "$EASYSERVER_ROOT/.git" ]; then
        info "项目已存在，更新中..."
        cd "$EASYSERVER_ROOT" && git pull --ff-only || warn "git pull 失败"
    elif [ -d "$EASYSERVER_ROOT" ]; then
        info "目录已存在，跳过克隆"
    else
        info "克隆项目到 $EASYSERVER_ROOT ..."
        git clone --depth 1 "$REPO_URL" "$EASYSERVER_ROOT"
    fi
}

init_env() {
    cd "$EASYSERVER_ROOT"
    if [ ! -f .env ]; then
        cp .env.example .env
        sed -i "s|^DATA_DIR=.*|DATA_DIR=${EASYSERVER_ROOT}/data|" .env
        ok ".env 已创建，请编辑: $EASYSERVER_ROOT/.env"
    else
        ok ".env 已存在"
    fi
}

init_dirs() {
    cd "$EASYSERVER_ROOT"
    mkdir -p data
    mkdir -p modules/nginx/{conf.d,ssl,log,acme-challenge}
    ok "数据目录已就绪"
}

init_network() {
    if ! docker network inspect easyserver-proxy &>/dev/null; then
        docker network create easyserver-proxy
        ok "Docker 网络 easyserver-proxy 已创建"
    else
        ok "Docker 网络已存在"
    fi
}

start_core() {
    cd "$EASYSERVER_ROOT"
    info "启动核心引擎..."
    docker compose up -d --build
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  EasyServer 安装完成！${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo "  管理面板: http://localhost:8900"
    echo "  API 文档: http://localhost:8900/docs"
    echo "  首次访问请完成设置向导"
    echo ""
}

main() {
    echo ""
    echo "========================================="
    echo "  EasyServer 安装向导"
    echo "========================================="
    check_docker
    setup_project
    init_env
    init_dirs
    init_network
    start_core
}

main "$@"
