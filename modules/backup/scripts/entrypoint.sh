#!/bin/sh
set -e

echo "=== EasyServer 备份模块启动 ==="

# 初始化 restic 仓库
if [ ! -d "$RESTIC_REPOSITORY" ]; then
    echo "初始化 restic 仓库..."
    restic init || { echo "❌ 仓库初始化失败"; exit 1; }
    echo "✅ 仓库初始化完成"
fi

# 安装 crond（如果未安装）
which crond >/dev/null 2>&1 || {
    apk add --no-cache dcron 2>/dev/null || apt-get update && apt-get install -y cron 2>/dev/null
}

# 创建 cron 任务
echo "$BACKUP_SCHEDULE /scripts/backup.sh >> /var/log/backup.log 2>&1" > /etc/crontabs/root 2>/dev/null || \
echo "$BACKUP_SCHEDULE /scripts/backup.sh >> /var/log/backup.log 2>&1" | crontab -

echo "✅ 备份计划已设置: $BACKUP_SCHEDULE"

# 启动时立即执行一次备份
echo "执行首次备份..."
/scripts/backup.sh

# 启动 cron 守护进程
echo "启动 cron 守护进程..."
exec crond -f -l 2 2>/dev/null || exec cron -f
