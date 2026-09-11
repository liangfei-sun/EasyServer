#!/usr/bin/env bash
set -euo pipefail

echo "=== EasyServer 备份服务启动 ==="

# 初始化 restic 仓库（如果不存在）
if [ ! -d "$RESTIC_REPOSITORY" ] || [ -z "$(ls -A $RESTIC_REPOSITORY 2>/dev/null)" ]; then
    echo "初始化 restic 仓库..."
    restic init || { echo "仓库初始化失败"; exit 1; }
    echo "仓库初始化完成"
fi

# 解析 cron 表达式为秒数（支持标准5段格式）
parse_cron_to_seconds() {
    local schedule="$1"
    # 读取分钟和小时字段
    local minute=$(echo "$schedule" | awk '{print $1}')
    local hour=$(echo "$schedule" | awk '{print $2}')
    
    # 处理简单情况：每天固定时间
    if [[ "$minute" =~ ^[0-9]+$ ]] && [[ "$hour" =~ ^[0-9]+$ ]]; then
        # 计算距午夜秒数
        echo $(( (hour * 3600) + (minute * 60) ))
        return
    fi
    
    # 默认每24小时
    echo 86400
}

CRON_SCHEDULE="${BACKUP_SCHEDULE:-0 2 * * *}"
echo "备份周期: $CRON_SCHEDULE"

# 启动前置检查：仓库可访问性（纯只读探测，绝不写入）
# ⚠ 安全加固（勿回退）：原实现在每次启动时无条件执行 /scripts/backup.sh，会立即
#   触发 restic backup 写仓库并连带执行快照清理；若密码错误/仓库损坏，则每次重启都
#   白跑一次失败流程，容器看似 Up 却从未备份成功（曾造成 39 天静默无备份）。
#   现改为：先用只读的 `restic snapshots --no-lock` 探测仓库是否可用，不可用时
#   只启动调度器、绝不触发任何写入，并把原因打印到容器日志便于排查。
if ! restic snapshots --no-lock >/dev/null 2>&1; then
    echo "⚠ 仓库不可访问（密码错误、仓库损坏或路径不存在）: $RESTIC_REPOSITORY"
    echo "⚠ 已跳过首次备份，仅启动调度器；请核对 BACKUP_PASSWORD 是否与该仓库匹配"
elif [ "${SKIP_INITIAL_BACKUP:-0}" = "1" ]; then
    echo "SKIP_INITIAL_BACKUP=1，跳过启动时的首次备份（仅启动调度器）"
else
    # 执行首次备份
    echo "执行首次备份..."
    /scripts/backup.sh || echo "首次备份失败，将在下次计划时间重试"
fi

# 计算下次备份等待时间
target_seconds=$(parse_cron_to_seconds "$CRON_SCHEDULE")
echo "定时备份间隔: ${target_seconds}s"

# 使用 sleep 循环替代 crond（避免 Docker setpgid 问题）
echo "备份调度器已启动，等待下次执行..."
while true; do
    # 计算距下次目标时间的等待秒数
    current_seconds=$(date +%s)
    today_start=$(date -d "today 00:00:00" +%s 2>/dev/null || date -j -f "%H:%M:%S" "00:00:00" +%s 2>/dev/null || echo $current_seconds)
    target_time=$(( today_start + target_seconds ))
    
    # 如果今天的目标时间已过，等到明天
    if [ $current_seconds -ge $target_time ]; then
        wait_seconds=$(( target_time + 86400 - current_seconds ))
    else
        wait_seconds=$(( target_time - current_seconds ))
    fi
    
    echo "下次备份将在 ${wait_seconds}s 后执行 ($(date -d "+${wait_seconds} seconds" 2>/dev/null || echo '稍后'))"
    sleep $wait_seconds
    
    echo "=== 定时备份触发: $(date) ==="
    /scripts/backup.sh || echo "备份失败，将在下次计划时间重试"
done
