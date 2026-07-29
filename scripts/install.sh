#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# EasyServer 安装脚本
# 用法: curl -fsSL https://raw.githubusercontent.com/liangfei-sun/EasyServer/main/scripts/install.sh | bash
# ============================================================

EASYSERVER_ROOT="${EASYSERVER_ROOT:-$HOME/easyserver}"
REPO_URL="${REPO_URL:-git@github.com:liangfei-sun/EasyServer.git}"

RED='[0;31m'
GREEN='[0;32m'
YELLOW='[1;33m'
BLUE='[0;34m'
NC='[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*" >&2; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ===== 参数解析 =====
AUTO_DEPLOY=false
CHECK_ONLY=false
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --auto-deploy)
            AUTO_DEPLOY=true
            shift
            ;;
        --check-only)
            CHECK_ONLY=true
            shift
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

# ===== 环境探测 =====
detect_environment() {
    echo "🔍 检测系统环境..."

    # OS 发行版
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_NAME="$NAME"
        OS_VERSION="$VERSION_ID"
        echo "  系统: $OS_NAME $OS_VERSION"
    else
        echo "  ⚠ 无法检测操作系统"
    fi

    # Docker 版本检查
    if command -v docker >/dev/null 2>&1; then
        DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null)
        DOCKER_MAJOR=$(echo "$DOCKER_VERSION" | cut -d. -f1)
        echo "  Docker: $DOCKER_VERSION"
        if [ "$DOCKER_MAJOR" -lt 20 ] 2>/dev/null; then
            echo "  ⚠ Docker 版本过低（需 ≥20.10），建议升级"
        fi
    else
        echo "  Docker: 未安装（将自动安装）"
    fi

    # Docker Compose v2 检查
    if docker compose version >/dev/null 2>&1; then
        echo "  Docker Compose: $(docker compose version --short 2>/dev/null)"
    elif command -v docker-compose >/dev/null 2>&1; then
        echo "  Docker Compose: $(docker-compose --version 2>/dev/null) (v1)"
    else
        echo "  Docker Compose: 未安装（将自动安装）"
    fi

    # 内存检查（最低 1GB）
    MEM_TOTAL=$(free -m 2>/dev/null | awk '/^Mem:/{print $2}')
    if [ -n "$MEM_TOTAL" ]; then
        echo "  内存: ${MEM_TOTAL}MB"
        if [ "$MEM_TOTAL" -lt 1024 ] 2>/dev/null; then
            echo "  ⚠ 内存不足 1GB，部分服务可能运行缓慢"
        fi
    fi

    # 磁盘空间检查（最低 10GB）
    DISK_AVAIL=$(df -BG / 2>/dev/null | awk 'NR==2{print $4}' | tr -d 'G')
    if [ -n "$DISK_AVAIL" ]; then
        echo "  可用磁盘: ${DISK_AVAIL}GB"
        if [ "$DISK_AVAIL" -lt 10 ] 2>/dev/null; then
            echo "  ⚠ 磁盘空间不足 10GB"
        fi
    fi

    # IPv6 可用性
    if ip -6 addr show scope global 2>/dev/null | grep -q inet6; then
        IPV6_ADDR=$(ip -6 addr show scope global 2>/dev/null | grep inet6 | head -1 | awk '{print $2}' | cut -d/ -f1)
        echo "  IPv6: 可用 ($IPV6_ADDR)"
        HAS_IPV6=true
    else
        echo "  IPv6: 不可用"
        HAS_IPV6=false
    fi

    # 公网 IP
    PUBLIC_IP=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || curl -s --max-time 5 icanhazip.com 2>/dev/null)
    if [ -n "$PUBLIC_IP" ]; then
        echo "  公网 IP: $PUBLIC_IP"
    else
        echo "  公网 IP: 无法获取（可能无公网 IPv4）"
    fi

    # 端口检测
    echo "  端口检测:"
    for port in 80 443 8443 8900; do
        if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
            echo "    ${port}: 已占用"
        else
            echo "    ${port}: 可用"
        fi
    done

    echo "✅ 环境检测完成"
}

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
        chmod 600 "$EASYSERVER_ROOT/.env"
        ok ".env 已创建，权限已设置为 600，请编辑: $EASYSERVER_ROOT/.env"
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

    detect_environment

    # --check-only 模式：仅检测环境，不执行安装
    if [ "$CHECK_ONLY" = "true" ]; then
        echo ""
        echo "环境检测完成（--check-only 模式），未执行安装操作"
        exit 0
    fi

    check_docker
    setup_project
    init_env
    init_dirs
    init_network
    start_core

    # 自动部署支持
    if [ "$AUTO_DEPLOY" = "true" ]; then
        echo "🚀 自动开始部署..."
        INSTALL_DIR="${EASYSERVER_ROOT}"
        bash "$INSTALL_DIR/scripts/auto-deploy.sh" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
    fi
}

main "$@"
