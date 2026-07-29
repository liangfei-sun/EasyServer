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

# 云端同步
case "$BACKUP_CLOUD_PROVIDER" in
    aliyun-oss)
        if [ -n "$BACKUP_CLOUD_BUCKET" ] && [ -n "$BACKUP_CLOUD_KEY" ]; then
            echo "同步到阿里云 OSS: $BACKUP_CLOUD_BUCKET"
            # 使用 ossutil 或 rclone 同步（需额外安装）
            which ossutil64 >/dev/null 2>&1 && \
                ossutil64 cp -r /backups/restic-repo "oss://$BACKUP_CLOUD_BUCKET/easyserver-backup/" \
                -i "$BACKUP_CLOUD_KEY" -k "$BACKUP_CLOUD_SECRET" -e "oss-cn-hangzhou.aliyuncs.com" || \
                echo "⚠ ossutil 未安装，云端同步跳过"
        fi
        ;;
    baidu-netdisk)
        echo "⚠ 百度网盘同步需要额外配置 BaiduPCS-Go"
        ;;
    none|"")
        echo "云端存储未配置，仅保留本地备份"
        ;;
esac

echo "=== 备份完成: $(date) ==="
