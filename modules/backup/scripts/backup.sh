#!/bin/sh
set -e

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
echo "=== 备份开始: $TIMESTAMP ==="

# 排除规则
EXCLUDE_ARGS="--exclude=data/jellyfin/cache --exclude=data/jellyfin/transcodes --exclude=*.log --exclude=backups --exclude=*.tmp"

# 配置文件挂载守卫（C1）：/config/.env 由 docker-compose.yml 的 `${DATA_DIR}/.env:/config/.env:ro` 提供，
# 与权威写入源（ConfigManager.env_file = DATA_DIR/.env）同源。
# 若该文件缺失（宿主 DATA_DIR/.env 不存在时 Docker 会在挂载源自动创建同名目录，使 /config/.env 变成目录），
# restic 会静默漏备 .env —— 灾备恢复出的配置缺失，且无任何报错。
# 策略：缺失时显式告警到日志，但**不中断**整库备份（数据保护优先级高于单个配置文件）。
BACKUP_TARGETS="/data"
if [ -f /config/.env ]; then
    BACKUP_TARGETS="/data /config/.env"
else
    echo "⚠ /config/.env 不存在（或不是普通文件），本次备份未包含 .env 配置"
    echo "  请核对宿主 \${DATA_DIR}/.env 是否存在，以及 modules/backup/docker-compose.yml 的"
    echo "  \${DATA_DIR}/.env:/config/.env:ro 挂载是否生效（容器需 recreate 才会应用新挂载）"
fi

# 本地增量备份
echo "执行 restic 增量备份... (目标: $BACKUP_TARGETS)"
restic backup $BACKUP_TARGETS $EXCLUDE_ARGS --tag "auto-$TIMESTAMP" || {
    echo "❌ 备份失败"
    exit 1
}
echo "✅ 本地备份完成"

# 清理过期快照
# ⚠ 安全加固（勿回退）：原实现为 `restic forget --keep-within "${BACKUP_RETAIN_DAYS}d" --prune`。
#   该写法在「备份中断时长 > 保留天数」时会让全部历史快照同时超期，一次执行即把整库
#   永久清空且不可逆（本仓库曾出现 15 个快照 / 8.9G 数据全部超出 7 天保留期的险情）。
#   现改为：① 分级保留，保底留住最新 1 份 + 每月 1 份；② forget 与 prune 彻底分离；
#   ③ prune 默认关闭——它会永久删除数据，必须显式设 BACKUP_PRUNE_ENABLED=1 才执行。
echo "清理 ${BACKUP_RETAIN_DAYS} 天前的快照（保底保留最新 1 份 + 每月 1 份）..."
restic forget \
    --keep-within "${BACKUP_RETAIN_DAYS}d" \
    --keep-last 1 \
    --keep-monthly 1 \
    2>/dev/null || echo "⚠ forget 跳过"

if [ "${BACKUP_PRUNE_ENABLED:-0}" = "1" ]; then
    echo "执行 prune（永久回收已 forget 快照独占的数据，不可逆）..."
    restic prune 2>/dev/null || echo "⚠ prune 跳过"
else
    echo "BACKUP_PRUNE_ENABLED != 1，跳过 prune（数据仍完整保留在仓库中，可日后手动执行）"
fi

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
