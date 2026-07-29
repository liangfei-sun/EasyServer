#!/bin/bash
# ============================================================
# EasyServer 一键自动化部署脚本
# 用法: bash auto-deploy.sh [选项]
# ============================================================

set -uo pipefail

# ==================== 颜色定义 ====================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ==================== 默认值 ====================
DOMAIN=""
EMAIL=""
ALI_KEY=""
ALI_SECRET=""
CF_TOKEN=""
PASSWORD=""
PORT="8900"
API_BASE="http://127.0.0.1:${PORT}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_FILE=""
NON_INTERACTIVE=false
HTTPS_PORT=8443

# ==================== 断点续部署状态文件 ====================
STATE_FILE="/tmp/easyserver-deploy-state"

mark_step() {
    echo "$1" >> "$STATE_FILE"
}

is_step_done() {
    grep -q "^$1$" "$STATE_FILE" 2>/dev/null
}

# 清理旧状态文件（新部署时）
reset_state() {
    rm -f "$STATE_FILE"
    touch "$STATE_FILE"
}

# ==================== 网络环境检测 ====================
check_port_blocked() {
    if curl -s --max-time 3 https://127.0.0.1:443 >/dev/null 2>&1; then
        echo "443 端口可用"
        HTTPS_PORT=443
    else
        echo "443 端口可能被封锁，使用 8443"
        HTTPS_PORT=8443
    fi
}

# ==================== 帮助信息 ====================
show_help() {
    cat <<'EOF'
EasyServer 一键自动化部署脚本

用法: bash auto-deploy.sh [选项]

选项:
  --domain DOMAIN          主域名（必填）
  --email EMAIL            SSL 证书邮箱（必填）
  --ali-key KEY            阿里云 AccessKey ID
  --ali-secret SECRET      阿里云 AccessKey Secret
  --cf-token TOKEN         Cloudflare Tunnel Token
  --password PASS          服务密码（未提供则自动生成）
  --port PORT              EasyServer 端口（默认 8900）
  --config FILE            JSON 配置文件（非交互模式）
  --non-interactive        非交互模式（需配合 --config 使用）
  --reset-state            清除断点续部署状态，从头开始
  -h, --help               显示帮助信息

配置文件格式 (deploy-config.json):
{
    "domain": "example.com",
    "email": "user@example.com",
    "ali_key": "your_access_key_id",
    "ali_secret": "your_access_key_secret",
    "cf_tunnel_token": "your_cloudflare_tunnel_token",
    "password": "your_password",
    "dns_provider": "aliyun",
    "https_port": 8443,
    "modules": ["nginx", "acme", "ddns-go", "uptime-kuma", "notediscovery", "joplin", "jellyfin", "calibre-web", "filebrowser", "cloudflare-tunnel"]
}

示例:
  bash auto-deploy.sh
  bash auto-deploy.sh --domain example.com --email user@example.com \
       --ali-key KEY --ali-secret SECRET --cf-token TOKEN
  bash auto-deploy.sh --config deploy-config.json --non-interactive
EOF
}

# ==================== 参数解析 ====================
while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)           DOMAIN="$2";          shift 2 ;;
        --email)            EMAIL="$2";           shift 2 ;;
        --ali-key)          ALI_KEY="$2";         shift 2 ;;
        --ali-secret)       ALI_SECRET="$2";      shift 2 ;;
        --cf-token)         CF_TOKEN="$2";        shift 2 ;;
        --password)         PASSWORD="$2";        shift 2 ;;
        --port)             PORT="$2"; API_BASE="http://127.0.0.1:${PORT}"; shift 2 ;;
        --config)           CONFIG_FILE="$2";     shift 2 ;;
        --non-interactive)  NON_INTERACTIVE=true; shift ;;
        --reset-state)      reset_state;          shift ;;
        --help|-h)          show_help; exit 0 ;;
        *) echo -e "${RED}错误: 未知参数: $1${NC}"; show_help; exit 1 ;;
    esac
done

# ==================== 从配置文件读取参数 ====================
if [ -n "$CONFIG_FILE" ] && [ -f "$CONFIG_FILE" ]; then
    NON_INTERACTIVE=true
    # 从 JSON 配置文件读取参数（命令行参数优先，不为空时不覆盖）
    _cfg_domain=$(jq -r '.domain // empty' "$CONFIG_FILE" 2>/dev/null)
    _cfg_email=$(jq -r '.email // empty' "$CONFIG_FILE" 2>/dev/null)
    _cfg_ali_key=$(jq -r '.ali_key // empty' "$CONFIG_FILE" 2>/dev/null)
    _cfg_ali_secret=$(jq -r '.ali_secret // empty' "$CONFIG_FILE" 2>/dev/null)
    _cfg_cf_token=$(jq -r '.cf_tunnel_token // empty' "$CONFIG_FILE" 2>/dev/null)
    _cfg_password=$(jq -r '.password // empty' "$CONFIG_FILE" 2>/dev/null)
    _cfg_https_port=$(jq -r '.https_port // empty' "$CONFIG_FILE" 2>/dev/null)

    [ -z "$DOMAIN" ]     && DOMAIN="$_cfg_domain"
    [ -z "$EMAIL" ]      && EMAIL="$_cfg_email"
    [ -z "$ALI_KEY" ]    && ALI_KEY="$_cfg_ali_key"
    [ -z "$ALI_SECRET" ] && ALI_SECRET="$_cfg_ali_secret"
    [ -z "$CF_TOKEN" ]   && CF_TOKEN="$_cfg_cf_token"
    [ -z "$PASSWORD" ]   && PASSWORD="$_cfg_password"
    [ -n "$_cfg_https_port" ] && HTTPS_PORT="$_cfg_https_port"

    echo -e "${BLUE}[INFO]${NC} 已从配置文件加载参数: $CONFIG_FILE"
fi

# ==================== 必填参数校验 ====================
if [ -z "$DOMAIN" ]; then
    echo "❌ 错误: 必须通过 --domain 参数或配置文件指定域名"
    exit 1
fi

if [ -z "$EMAIL" ]; then
    echo "❌ 错误: 必须通过 --email 参数或配置文件指定 SSL 证书邮箱"
    exit 1
fi

if [ -z "$PASSWORD" ]; then
    PASSWORD=$(openssl rand -base64 16 2>/dev/null || head -c 32 /dev/urandom | base64)
    echo "⚠ 未提供密码，已自动生成: $PASSWORD"
fi

# ==================== 工具函数 ====================
log_pass()  { echo -e "  ${GREEN}[✓]${NC} $1"; }
log_fail()  { echo -e "  ${RED}[✗]${NC} $1"; }
log_warn()  { echo -e "  ${YELLOW}[!]${NC} $1"; }
log_info()  { echo -e "  ${BLUE}[i]${NC} $1"; }
log_step()  { echo -e "\n${CYAN}${BOLD}>>> $1${NC}"; }

FAIL_COUNT=0
INSTALLED_MODULES_CACHE=""

api_call() {
    local method="$1" url="$2" data="${3:-}"
    local response http_code body
    if [[ -n "$data" ]]; then
        response=$(curl -s -w "\n%{http_code}" -X "$method" "$url" \
            -H "Content-Type: application/json" -d "$data" 2>&1)
    else
        response=$(curl -s -w "\n%{http_code}" -X "$method" "$url" 2>&1)
    fi
    http_code=$(echo "$response" | tail -1)
    body=$(echo "$response" | sed '$d')
    if [[ "$http_code" -ge 200 && "$http_code" -lt 300 ]]; then
        echo "$body"
        return 0
    else
        echo "API 错误 [HTTP $http_code]: $body" >&2
        return 1
    fi
}

# 缓存已安装模块列表（只查询一次 API）
refresh_installed_cache() {
    local resp
    resp=$(curl -sf "$API_BASE/api/modules" 2>/dev/null || echo "")
    if [[ -z "$resp" ]]; then
        INSTALLED_MODULES_CACHE=""
        return
    fi
    # 用 jq 提取已安装模块 ID 列表
    INSTALLED_MODULES_CACHE=$(echo "$resp" | jq -r '
        (if type == "array" then . else .modules // .data // [] end)
        | map(select(.installed == true or .status == "running") | .id // .module_id)
        | .[]
    ' 2>/dev/null || echo "")
}

check_module_installed() {
    local module_id="$1"
    if [[ -z "$INSTALLED_MODULES_CACHE" ]]; then
        return 1
    fi
    echo "$INSTALLED_MODULES_CACHE" | grep -qx "$module_id"
}

wait_for_api() {
    local max_wait=60 waited=0
    log_step "等待 EasyServer API 就绪..."
    while [[ $waited -lt $max_wait ]]; do
        if curl -s -o /dev/null -w "%{http_code}" "$API_BASE/api/config" 2>/dev/null | grep -q "200"; then
            log_pass "API 已就绪 (等待 ${waited}s)"
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
    done
    log_fail "API 等待超时 (${max_wait}s)"
    return 1
}

install_module() {
    local module_id="$1"
    local config="${2:-{}}"
    local description="${3:-$module_id}"

    echo -e "  ${BOLD}[$description]${NC} 安装中..."

    # 幂等检查：已安装则跳过
    if check_module_installed "$module_id"; then
        log_warn "$module_id 已安装，跳过"
        return 0
    fi

    local result
    if result=$(api_call POST "$API_BASE/api/modules/install" \
        "{\"module_id\":\"$module_id\",\"config\":$config}"); then
        # 安装成功后刷新缓存
        refresh_installed_cache
        local success
        success=$(echo "$result" | jq -r '.success // false' 2>/dev/null || echo "")
        if [[ "$success" == "true" ]]; then
            log_pass "$module_id 安装成功"
        else
            local msg
            msg=$(echo "$result" | jq -r '.error // .message // "未知错误"' 2>/dev/null || echo "未知错误")
            log_fail "$module_id 安装失败: $msg"
            FAIL_COUNT=$((FAIL_COUNT + 1))
        fi
    else
        log_fail "$module_id API 调用失败"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

# ==================== 初始化状态文件（断点续部署）====================
# 如果状态文件不存在，初始化它；如果存在，说明上次部署中断，继续从断点执行
if [ ! -f "$STATE_FILE" ]; then
    touch "$STATE_FILE"
fi

# ==================== 开始部署 ====================
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       EasyServer 一键自动化部署          ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  域名:     ${CYAN}${DOMAIN}${NC}"
echo -e "  邮箱:     ${CYAN}${EMAIL}${NC}"
echo -e "  端口:     ${CYAN}${PORT}${NC}"
echo -e "  HTTPS端口:${CYAN}${HTTPS_PORT}${NC}"
echo -e "  项目目录: ${CYAN}${PROJECT_ROOT}${NC}"
if [ "$NON_INTERACTIVE" = "true" ]; then
    echo -e "  模式:     ${CYAN}非交互模式${NC}"
fi
echo ""

# ==================== Step 1: 环境检查 ====================
STEP_ID="step1_env_check"
if is_step_done "$STEP_ID"; then
    log_warn "Step 1 已完成，跳过"
else
    log_step "Step 1/9: 环境检查"

    ENV_OK=true
    for cmd in docker curl jq; do
        if command -v "$cmd" &>/dev/null; then
            log_pass "$cmd 已安装 ($(command -v $cmd))"
        else
            log_fail "$cmd 未安装"
            ENV_OK=false
        fi
    done

    if [[ "$ENV_OK" != "true" ]]; then
        echo ""
        log_fail "缺少必要工具，请先安装后重试"
        exit 1
    fi

    # 检查 Docker 是否运行
    if docker info &>/dev/null; then
        log_pass "Docker 守护进程运行中"
    else
        log_fail "Docker 守护进程未运行"
        exit 1
    fi

    # 网络环境检测：443 端口是否被运营商封锁
    log_info "检测网络环境..."
    check_port_blocked
    log_info "HTTPS 端口: $HTTPS_PORT"

    mark_step "$STEP_ID"
fi

# ==================== Step 2: 等待 API ====================
STEP_ID="step2_wait_api"
if is_step_done "$STEP_ID"; then
    log_warn "Step 2 已完成，跳过"
else
    wait_for_api || { log_fail "EasyServer API 不可用，请确认服务已启动"; exit 1; }

    # 首次加载已安装模块缓存
    refresh_installed_cache

    mark_step "$STEP_ID"
fi

# ==================== Step 3: 创建 Docker 网络 ====================
STEP_ID="step3_docker_network"
if is_step_done "$STEP_ID"; then
    log_warn "Step 3 已完成，跳过"
else
    log_step "Step 2/9: 创建 Docker 网络"

    NETWORK_NAME="easyserver-proxy"
    if docker network ls --format '{{.Name}}' 2>/dev/null | grep -qx "$NETWORK_NAME"; then
        log_warn "网络 $NETWORK_NAME 已存在，跳过创建"
    else
        if docker network create "$NETWORK_NAME" &>/dev/null; then
            log_pass "网络 $NETWORK_NAME 创建成功"
        else
            log_fail "网络 $NETWORK_NAME 创建失败"
            FAIL_COUNT=$((FAIL_COUNT + 1))
        fi
    fi

    mark_step "$STEP_ID"
fi

# ==================== Step 4: 更新全局配置 ====================
STEP_ID="step4_global_config"
if is_step_done "$STEP_ID"; then
    log_warn "Step 4 已完成，跳过"
else
    log_step "Step 3/9: 更新全局配置"

    CONFIG_DATA="{
        \"domain\": \"${DOMAIN}\",
        \"access_mode\": \"domain\",
        \"https_port\": ${HTTPS_PORT},
        \"http_port\": 80,
        \"ssl_email\": \"${EMAIL}\",
        \"dns_provider\": \"aliyun\"
    }"

    if api_call PUT "$API_BASE/api/config" "$CONFIG_DATA" >/dev/null 2>&1; then
        log_pass "全局配置已更新"
    else
        log_fail "全局配置更新失败"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi

    mark_step "$STEP_ID"
fi

# ==================== Step 5: 安装模块 ====================
STEP_ID="step5_install_modules"
if is_step_done "$STEP_ID"; then
    log_warn "Step 5 已完成，跳过"
else
    log_step "Step 4/9: 安装模块（按依赖顺序）"
    echo ""

    # 生成随机密钥
    NOTES_SECRET=$(openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | od -An -tx1 | tr -d ' \n')

    # 按依赖顺序安装
    install_module "nginx"            "{}"                                                          "Nginx 反向代理"
    install_module "acme"             "{\"ACME_ALI_KEY\":\"${ALI_KEY}\",\"ACME_ALI_SECRET\":\"${ALI_SECRET}\",\"ACME_DOMAIN\":\"${DOMAIN}\"}" "ACME SSL 证书"
    install_module "ddns-go"          "{}"                                                          "DDNS-Go 动态DNS"
    install_module "uptime-kuma"      "{}"                                                          "Uptime Kuma 监控"
    install_module "notediscovery"    "{\"NOTEDISCOVERY_PASSWORD\":\"${PASSWORD}\",\"NOTEDISCOVERY_SECRET_KEY\":\"${NOTES_SECRET}\"}" "NoteDiscovery 笔记"
    install_module "joplin"           "{\"JOPLIN_DB_PASSWORD\":\"${PASSWORD}\",\"JOPLIN_DB_USER\":\"joplin\",\"JOPLIN_DB_NAME\":\"joplin\"}" "Joplin 笔记"
    install_module "jellyfin"         "{}"                                                          "Jellyfin 媒体"
    install_module "calibre-web"      "{}"                                                          "Calibre-Web 电子书"
    install_module "filebrowser"      "{}"                                                          "FileBrowser 文件管理"
    install_module "cloudflare-tunnel" "{\"CF_TUNNEL_TOKEN\":\"${CF_TOKEN}\"}"                       "Cloudflare Tunnel"

    echo ""

    mark_step "$STEP_ID"
fi

# ==================== Step 6: 生成 Nginx 配置 ====================
STEP_ID="step6_nginx_generate"
if is_step_done "$STEP_ID"; then
    log_warn "Step 6 已完成，跳过"
else
    log_step "Step 5/9: 生成 Nginx 配置"

    if api_call POST "$API_BASE/api/nginx/generate" >/dev/null 2>&1; then
        log_pass "Nginx 配置已生成"
    else
        log_fail "Nginx 配置生成失败"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi

    mark_step "$STEP_ID"
fi

# ==================== Step 7: 重载 Nginx ====================
STEP_ID="step7_nginx_reload"
if is_step_done "$STEP_ID"; then
    log_warn "Step 7 已完成，跳过"
else
    log_step "Step 6/9: 重载 Nginx"

    if docker exec easyserver-nginx nginx -s reload 2>/dev/null; then
        log_pass "Nginx 已重载"
    else
        log_warn "Nginx 重载失败（容器可能未运行或尚未启动）"
    fi

    mark_step "$STEP_ID"
fi

# ==================== Step 8: 标记部署完成 ====================
STEP_ID="step8_setup_complete"
if is_step_done "$STEP_ID"; then
    log_warn "Step 8 已完成，跳过"
else
    log_step "Step 7/9: 标记部署完成"

    if api_call POST "$API_BASE/api/config/setup/complete" >/dev/null 2>&1; then
        log_pass "部署已标记完成"
    else
        log_fail "标记部署完成失败"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi

    mark_step "$STEP_ID"
fi

# ==================== Step 9: 健康检查 ====================
STEP_ID="step9_healthcheck"
if is_step_done "$STEP_ID"; then
    log_warn "Step 9 已完成，跳过"
else
    log_step "Step 8/9: 运行健康检查"

    if [[ -f "$PROJECT_ROOT/scripts/healthcheck.sh" ]]; then
        bash "$PROJECT_ROOT/scripts/healthcheck.sh" "$PORT" 2>/dev/null || true
    else
        log_warn "healthcheck.sh 不存在，跳过健康检查"
    fi

    mark_step "$STEP_ID"
fi

# ==================== 输出服务访问地址 ====================
log_step "Step 9/9: 服务访问地址"
echo ""
echo -e "  ${BOLD}┌──────────────────────────────────────────────────────────┐${NC}"
echo -e "  ${BOLD}│              服务访问地址列表                            │${NC}"
echo -e "  ${BOLD}├──────────────────────────────────────────────────────────┤${NC}"
echo -e "  │  ${CYAN}Uptime Kuma${NC}      https://status.${DOMAIN}:${HTTPS_PORT}     │"
echo -e "  │  ${CYAN}NoteDiscovery${NC}    https://notes.${DOMAIN}:${HTTPS_PORT}    │"
echo -e "  │  ${CYAN}Joplin${NC}           https://joplin.${DOMAIN}:${HTTPS_PORT}   │"
echo -e "  │  ${CYAN}Jellyfin${NC}         https://media.${DOMAIN}:${HTTPS_PORT}    │"
echo -e "  │  ${CYAN}Calibre-Web${NC}      https://books.${DOMAIN}:${HTTPS_PORT}    │"
echo -e "  │  ${CYAN}FileBrowser${NC}      https://files.${DOMAIN}:${HTTPS_PORT}    │"
echo -e "  ${BOLD}├──────────────────────────────────────────────────────────┤${NC}"
echo -e "  │  ${CYAN}EasyServer 面板${NC}  http://127.0.0.1:${PORT}          │"
echo -e "  │  ${CYAN}EasyServer HTTPS${NC} https://panel.${DOMAIN}:${HTTPS_PORT} │"
echo -e "  ${BOLD}└──────────────────────────────────────────────────────────┘${NC}"
echo ""

# ==================== 部署总结 ====================
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
if [[ $FAIL_COUNT -gt 0 ]]; then
    echo -e "${BOLD}║  ${YELLOW}部署完成，但有 ${FAIL_COUNT} 个步骤失败${BOLD}               ║${NC}"
    echo -e "${BOLD}║  可重新运行脚本，已完成的步骤将自动跳过   ║${NC}"
else
    echo -e "${BOLD}║  ${GREEN}所有步骤执行成功！${BOLD}                       ║${NC}"
    # 全部成功，清理状态文件
    rm -f "$STATE_FILE"
fi
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
