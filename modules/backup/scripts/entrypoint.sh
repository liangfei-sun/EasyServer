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

# 执行首次备份
echo "执行首次备份..."
/scripts/backup.sh || echo "首次备份失败，将在下次计划时间重试"

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
