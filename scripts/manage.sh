#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# EasyServer 管理脚本
# 用法: ./scripts/manage.sh <command>
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

usage() {
    echo "用法: $0 <command>"
    echo ""
    echo "命令:"
    echo "  start       启动所有服务"
    echo "  stop        停止所有服务"
    echo "  restart     重启所有服务"
    echo "  status      查看所有服务状态"
    echo "  update      更新 EasyServer 到最新版本"
    echo "  logs        查看核心引擎日志"
    echo "  backup      备份数据到 data/backups/"
    echo "  svc <id> <action>  操作单个服务 (start/stop/restart/logs)"
    echo ""
}

cmd_start() {
    echo -e "${BLUE}[INFO]${NC} 启动 EasyServer..."
    docker compose up -d
    echo -e "${GREEN}[OK]${NC} 所有服务已启动"
}

cmd_stop() {
    echo -e "${BLUE}[INFO]${NC} 停止 EasyServer..."
    docker compose down
    echo -e "${GREEN}[OK]${NC} 所有服务已停止"
}

cmd_restart() {
    cmd_stop
    cmd_start
}

cmd_status() {
    echo "========================================="
    echo "  EasyServer 服务状态"
    echo "========================================="
    echo ""

    # 核心引擎
    echo -e "${BLUE}核心引擎:${NC}"
    docker compose ps 2>/dev/null || echo "  未运行"
    echo ""

    # 各模块
    echo -e "${BLUE}服务模块:${NC}"
    for module_dir in modules/*/; do
        local mod_name=$(basename "$module_dir")
        [ "$mod_name" = "_registry.yaml" ] && continue
        [ ! -f "$module_dir/docker-compose.yml" ] && continue

        local status=$(docker compose -f "$module_dir/docker-compose.yml" ps --format json 2>/dev/null | python3 -c "
import sys, json
running = 0
total = 0
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try:
        d = json.loads(line)
        total += 1
        if 'running' in d.get('State', '').lower():
            running += 1
    except: pass
if total == 0:
    print('stopped')
elif running == total:
    print('running')
else:
    print(f'partial ({running}/{total})')
" 2>/dev/null || echo "unknown")

        if echo "$status" | grep -q "running"; then
            echo -e "  ${GREEN}●${NC} $mod_name: $status"
        elif echo "$status" | grep -q "stopped"; then
            echo -e "  ${RED}●${NC} $mod_name: $status"
        else
            echo -e "  ${YELLOW}●${NC} $mod_name: $status"
        fi
    done
}

cmd_update() {
    echo -e "${BLUE}[INFO]${NC} 更新 EasyServer..."
    git pull --ff-only
    docker compose up -d --build
    echo -e "${GREEN}[OK]${NC} 更新完成"
}

cmd_logs() {
    local lines=${1:-100}
    docker compose logs --tail="$lines" -f
}

cmd_backup() {
    local backup_dir="data/backups"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$backup_dir/backup_$timestamp.tar.gz"

    mkdir -p "$backup_dir"
    echo -e "${BLUE}[INFO]${NC} 备份数据到 $backup_file ..."

    tar -czf "$backup_file" \
        --exclude='data/backups' \
        --exclude='*.log' \
        data/ \
        .env \
        2>/dev/null || true

    local size=$(du -h "$backup_file" | cut -f1)
    echo -e "${GREEN}[OK]${NC} 备份完成 ($size)"
}

cmd_svc() {
    local svc_id=$1
    local action=$2
    local module_dir="modules/$svc_id"

    if [ ! -d "$module_dir" ]; then
        echo -e "${RED}[ERROR]${NC} 模块 $svc_id 不存在"
        exit 1
    fi

    case "$action" in
        start)
            docker compose -f "$module_dir/docker-compose.yml" up -d
            echo -e "${GREEN}[OK]${NC} $svc_id 已启动"
            ;;
        stop)
            docker compose -f "$module_dir/docker-compose.yml" down
            echo -e "${GREEN}[OK]${NC} $svc_id 已停止"
            ;;
        restart)
            docker compose -f "$module_dir/docker-compose.yml" restart
            echo -e "${GREEN}[OK]${NC} $svc_id 已重启"
            ;;
        logs)
            docker compose -f "$module_dir/docker-compose.yml" logs -f --tail=100
            ;;
        *)
            echo -e "${RED}[ERROR]${NC} 未知操作: $action (可用: start/stop/restart/logs)"
            exit 1
            ;;
    esac
}

# ---- 主入口 ----
case "${1:-}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    status)  cmd_status ;;
    update)  cmd_update ;;
    logs)    cmd_logs "${2:-100}" ;;
    backup)  cmd_backup ;;
    svc)     cmd_svc "${2:-}" "${3:-}" ;;
    *)       usage ;;
esac
