#!/usr/bin/env bash
#
# EasyServer Health Check Script
# Usage: ./healthcheck.sh [port]
#   port: optional, default 8900

set -euo pipefail

# ---------- configuration ----------
PORT="${1:-8900}"
BASE_URL="http://127.0.0.1:${PORT}"
CONTAINER_NAME="easyserver-core"
NETWORK_NAME="easyserver-proxy"
DATA_DIR="$(cd "$(dirname "$0")/.." && pwd)/data"

# ---------- colors ----------
GREEN='\033[0;32m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ---------- counters ----------
PASSED=0
TOTAL=0

# ---------- helpers ----------
pass() {
    PASSED=$((PASSED + 1))
    TOTAL=$((TOTAL + 1))
    printf "  ${GREEN}[✓]${NC} %s: %s\n" "$1" "$2"
}

fail() {
    TOTAL=$((TOTAL + 1))
    printf "  ${RED}[✗]${NC} %s: %s\n" "$1" "$2"
}

# ---------- header ----------
echo ""
printf "${BOLD}EasyServer Health Check${NC}\n"
echo "========================"

# ---------- 1. Container Status ----------
if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER_NAME"; then
    pass "Container Status" "running"
else
    fail "Container Status" "container '$CONTAINER_NAME' not running"
fi

# ---------- 2. API Health ----------
HEALTH_RESP=$(curl -sf "${BASE_URL}/api/health" 2>/dev/null || echo "")
if [ -n "$HEALTH_RESP" ]; then
    STATUS=$(echo "$HEALTH_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
    if [ "$STATUS" = "ok" ] || echo "$HEALTH_RESP" | grep -q '"ok"\|"healthy"'; then
        pass "API Health" "ok"
    else
        pass "API Health" "responding (status: ${STATUS:-unknown})"
    fi
else
    fail "API Health" "no response from /api/health"
fi

# ---------- 3. Services API ----------
SERVICES_RESP=$(curl -sf "${BASE_URL}/api/services" 2>/dev/null || echo "")
if [ -n "$SERVICES_RESP" ] && echo "$SERVICES_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0)" 2>/dev/null; then
    SVC_COUNT=$(echo "$SERVICES_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
if isinstance(d, list):
    print(len(d))
elif isinstance(d, dict):
    # try common keys
    for k in ('services', 'data', 'items', 'results'):
        if k in d and isinstance(d[k], list):
            print(len(d[k]))
            break
    else:
        print('?')
" 2>/dev/null || echo "?")
    pass "Services API" "${SVC_COUNT} services found"
else
    fail "Services API" "invalid or no JSON response"
fi

# ---------- 4. Modules API ----------
MODULES_RESP=$(curl -sf "${BASE_URL}/api/modules" 2>/dev/null || echo "")
if [ -n "$MODULES_RESP" ] && echo "$MODULES_RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0)" 2>/dev/null; then
    MOD_COUNT=$(echo "$MODULES_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
if isinstance(d, list):
    print(len(d))
elif isinstance(d, dict):
    for k in ('modules', 'data', 'items', 'results'):
        if k in d and isinstance(d[k], list):
            print(len(d[k]))
            break
    else:
        print('?')
" 2>/dev/null || echo "?")
    pass "Modules API" "${MOD_COUNT} modules available"
else
    fail "Modules API" "invalid or no JSON response"
fi

# ---------- 5. Config API ----------
CONFIG_RESP=$(curl -sf "${BASE_URL}/api/config" 2>/dev/null || echo "")
if [ -n "$CONFIG_RESP" ] && echo "$CONFIG_RESP" | python3 -c "import sys,json; json.load(sys.stdin); exit(0)" 2>/dev/null; then
    pass "Config API" "readable"
else
    fail "Config API" "cannot read config"
fi

# ---------- 6. Config Write ----------
# Send a minimal PUT request; use the current config with a no-op field to avoid side effects
CONFIG_WRITE_RESP=$(curl -sf -X PUT "${BASE_URL}/api/config" \
    -H "Content-Type: application/json" \
    -d "$CONFIG_RESP" 2>/dev/null || echo "")
WRITE_STATUS=$?
if [ $WRITE_STATUS -eq 0 ] && [ -n "$CONFIG_WRITE_RESP" ]; then
    pass "Config Write" "success"
elif [ $WRITE_STATUS -eq 0 ]; then
    # curl returned 0 but empty body — some APIs return 204 No Content on success
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "${BASE_URL}/api/config" \
        -H "Content-Type: application/json" \
        -d "$CONFIG_RESP" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "204" ] || [ "$HTTP_CODE" = "200" ]; then
        pass "Config Write" "success"
    else
        fail "Config Write" "HTTP ${HTTP_CODE}"
    fi
else
    fail "Config Write" "request failed"
fi

# ---------- 7. Frontend ----------
FRONTEND_RESP=$(curl -sf "${BASE_URL}/" 2>/dev/null || echo "")
if echo "$FRONTEND_RESP" | grep -qi '<html\|<!doctype html\|<div id="app"'; then
    pass "Frontend" "accessible"
else
    fail "Frontend" "no HTML response from /"
fi

# ---------- 8. Docker Network ----------
if docker network ls --format '{{.Name}}' 2>/dev/null | grep -qx "$NETWORK_NAME"; then
    pass "Docker Network" "${NETWORK_NAME} exists"
else
    fail "Docker Network" "${NETWORK_NAME} not found"
fi

# ---------- 9. Data Directory ----------
if [ -d "$DATA_DIR" ] && [ -w "$DATA_DIR" ]; then
    pass "Data Directory" "writable"
else
    fail "Data Directory" "$DATA_DIR not writable or missing"
fi

# ---------- 10. 外网可达性验证 ----------
echo ""
echo "📡 外网可达性检查"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_DOMAIN=$(grep "^DOMAIN=" "$SCRIPT_DIR/../.env" 2>/dev/null | cut -d= -f2 | tr -d "'" | tr -d '"')
ENV_HTTPS_PORT=$(grep "^HTTPS_PORT=" "$SCRIPT_DIR/../.env" 2>/dev/null | cut -d= -f2 | tr -d "'" | tr -d '"')
ENV_HTTPS_PORT=${ENV_HTTPS_PORT:-8443}

if [ -n "$ENV_DOMAIN" ]; then
    # DNS 解析检查
    RESOLVED_IP=$(dig +short "$ENV_DOMAIN" 2>/dev/null | head -1)
    if [ -n "$RESOLVED_IP" ]; then
        echo "  ✅ DNS 解析: $ENV_DOMAIN → $RESOLVED_IP"
    else
        echo "  ❌ DNS 解析: $ENV_DOMAIN 无记录"
    fi

    # HTTPS 握手检查
    if curl -sk --max-time 5 "https://$ENV_DOMAIN:$ENV_HTTPS_PORT/" -o /dev/null -w "%{http_code}" 2>/dev/null | grep -q "200\|301\|302"; then
        echo "  ✅ HTTPS 访问: https://$ENV_DOMAIN:$ENV_HTTPS_PORT"
    else
        echo "  ⚠ HTTPS 访问失败（可能 DNS 未配置或证书未签发）"
    fi

    # Cloudflare Tunnel 检查
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "cloudflared"; then
        echo "  ✅ Cloudflare Tunnel: 运行中"
    else
        echo "  ⚠ Cloudflare Tunnel: 未运行"
    fi
else
    echo "  ⚠ .env 中未配置 DOMAIN，跳过外网可达性检查"
fi

# ---------- summary ----------
echo "========================"
if [ "$PASSED" -eq "$TOTAL" ]; then
    printf "Result: ${GREEN}${BOLD}ALL CHECKS PASSED${NC} (%d/%d)\n" "$PASSED" "$TOTAL"
else
    printf "Result: ${RED}${BOLD}%d/%d CHECKS PASSED${NC}\n" "$PASSED" "$TOTAL"
fi
echo ""

# ---------- exit code ----------
if [ "$PASSED" -eq "$TOTAL" ]; then
    exit 0
else
    exit 1
fi
