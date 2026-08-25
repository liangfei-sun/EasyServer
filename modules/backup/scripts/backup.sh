#!/bin/sh
set -e

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
echo "=== 备份开始: $TIMESTAMP ==="

# 排除规则
EXCLUDE_ARGS="--exclude=data/jellyfin/cache --exclude=data/jellyfin/transcodes --exclude=*.log --exclude=backups --exclude=*.tmp"

# 本地增量备份
echo "执行 restic 增量备份..."
restic backup /data /config/.env $EXCLUDE_ARGS --tag "auto-$TIMESTAMP" || {
    echo "❌ 备份失败"
    exit 1
}
echo "✅ 本地备份完成"

# 清理过期快照
echo "清理 ${BACKUP_RETAIN_DAYS} 天前的快照..."
restic forget --keep-within "${BACKUP_RETAIN_DAYS}d" --prune 2>/dev/null || echo "⚠ 清理跳过"

# 云端同步（当前未支持，需要额外安装 ossutil/rclone）
case "$BACKUP_CLOUD_PROVIDER" in
    aliyun-oss|baidu-netdisk)
        echo "⚠ 云端备份（$BACKUP_CLOUD_PROVIDER）暂未集成，仅保留本地备份"
        echo "  如需云端备份，请手动配置 rclone 或 ossutil 后修改此脚本"
        ;;
    none|"")
        echo "云端存储未配置，仅保留本地备份"
        ;;
esac

echo "=== 备份完成: $(date) ==="
