# 数据备份 · 运行指南

> 基于 2026-09-04 WSL Ubuntu 24.04 实测（QA 报告 R15）。实测结论与上游描述不一致处，以实测为准并已标注。
> **重要预警：本模块为 build 型（镜像本地构建），实测面板/API 安装路径结构性失败（缺陷 N）**，需按 3.2 降级路径手动 build + 启动；备份引擎本身（restic 初始化/全量/保留策略/调度）降级路径下实测完整可用。
> **第二预警：`BACKUP_PASSWORD` 必须显式设置**——module.yaml 称"留空自动生成"（缺陷 O），实测该逻辑不存在且 compose 层硬性必填，留空必失败。

## 1. 概述

数据备份模块基于 restic 实现增量备份：备份所有服务数据（`data/` 目录）与配置文件（`.env`），首次运行自动初始化加密仓库并执行全量备份，后续按周期增量备份，超期快照自动清理。**CLI 型模块，无 Web UI、无端口**，通过容器日志与 restic 命令交互。

| 项 | 值 |
|------|------|
| 镜像 | `easyserver-backup:latest`（**本地 build 产物**，基于 alpine + apk restic，非拉取镜像） |
| 分类 | infra |
| 网络模式 | bridge，接入外部网络 `easyserver-proxy`（无对外端口） |
| 端口 | 无（CLI 型） |
| 资源限制 | 内存 256M / CPU 0.5 |
| 容器名 | `easyserver-backup` |
| 内置 healthcheck | 无；引擎健康检查方式为 `file_exists /data/backups`（module.yaml） |

备份内容与排除规则（module.yaml usage）：备份 `data/` 全目录 + `.env`；排除 `jellyfin/cache`、`jellyfin/transcodes`、`*.log`、临时文件。

## 2. 前置条件

- 核心引擎运行中；无依赖模块
- **`BACKUP_PASSWORD` 必须显式设置**（最关键前置）：compose 中 `RESTIC_PASSWORD=${BACKUP_PASSWORD:?BACKUP_PASSWORD must be set}` 为硬门控，实测留空时 compose 直接报错 `required variable BACKUP_PASSWORD is missing a value`。**restic 仓库密码丢失 = 备份不可恢复**，请妥善保管（可安装后查看项目根目录 `.env`）
- build 基础镜像 alpine 需可用（实测已由预拉取池就绪）
- 磁盘余量：仓库位于 `<DATA_DIR>/backups/`，与被备份数据同盘，首次全量需一份数据量级的空间

## 3. 安装

### 3.1 配置字段

| 字段 | 说明 | 默认值 | 必填 |
|------|------|--------|:---:|
| `BACKUP_SCHEDULE` | 备份周期（cron） | `0 2 * * *`（每天凌晨2点） | 否 |
| `BACKUP_RETAIN_DAYS` | 本地保留天数 | 7 | 否 |
| `BACKUP_CLOUD_PROVIDER` | 云端存储 | none（**暂未集成，仅 none 可选**） | 否 |
| `BACKUP_PASSWORD` | 备份加密密码（restic 仓库） | 空 | **实测必填**（见下） |

> 缺陷 O（语义三处矛盾，实测记录）：module.yaml 注释"留空自动生成"+ 未标 `required` → 引擎前置校验放行；compose `:?` 语法实际必填且无自动生成逻辑。三处行为不一致，**用户视角结论：当作必填项处理**。

### 3.2 安装路径与实测行为（面板安装当前不可用）

**面板/API 安装（实测失败）**：`POST /api/modules/install {"module_id":"backup",...}` 即使不带密码也能通过前置校验进入 running，随后 **pull 阶段即失败**：引擎对 compose 含 `build:` 的服务仍逐镜像 `docker pull`，本地构建镜像名 `easyserver-backup:latest` 被 mirror 白名单拒绝（`🚫 这镜像不在白名单`），重试 3 次后终态 `failed(pull)`——根本未走到 compose 层的密码校验。这是 build 型模块的结构性缺陷（缺陷 N，backup/nextcloud 双实证），面板安装 backup 当前必失败。

**实测可行的降级路径（手动 build + up）**：

```bash
cd <项目根目录>/modules/backup   # 或运行时目录 /easyserver_data/modules/backup

# 1. 构建镜像（alpine + apk restic，实测约 40 秒）
sg docker -c "docker compose -f docker-compose.yml build"

# 2. 启动（必须显式传入密码；DATA_DIR/PROJECT_ROOT 引擎运行时已注入 .env，
#    手动执行时按需补充这两个变量）
sg docker -c "BACKUP_PASSWORD=<你的备份加密密码> \
  DATA_DIR=<数据目录> PROJECT_ROOT=<项目根目录> \
  docker compose -f docker-compose.yml up -d"
```

实测该路径成功：容器 Up，entrypoint 自动初始化 restic 仓库并完成首次全量备份。

## 4. 启动与验证

本模块无 HTTP 端点，验证方式为文件存在性 + restic 快照检查：

```bash
# 容器状态
sudo docker ps --filter name=easyserver-backup    # 实测：Up

# 引擎侧健康检查（module.yaml：file_exists /data/backups）
ls -la <DATA_DIR>/backups/
# 实测输出：restic-repo（drwx------ root root，700 权限）

# 首次备份快照验证（容器内 restic 命令）
sg docker -c "docker exec easyserver-backup restic snapshots"
# 实测输出：ca6f2f7f  paths=/config/.env /data  tags=auto-20260903_170606（含 7 天保留策略输出）

# 运行日志（首次全量 + 调度器启动）
sudo docker logs easyserver-backup
# 实测输出：=== 备份完成 ... ===  定时备份间隔: 7200s ... 调度器已启动
```

> **调度疑点（缺陷 R，P3）**：配置"每天凌晨2点"（cron `0 2 * * *`）时，实测日志报告"定时备份间隔： 7200s"——疑似 cron 表达式被简化为固定 2 小时轮询，与用户配置意图不符（未读源码定论，QA 标记为疑点）。依赖精确调度时间的用户请以日志实际行为为准并关注修复。

## 5. 访问方式

- **无 Web UI、无端口**（`access.port: 0`）：所有操作通过容器命令完成
- 快照查询：`docker exec easyserver-backup restic snapshots`
- 快照恢复：`docker exec easyserver-backup restic restore <快照ID> --target <目标目录>`（module.yaml faq：也可用管理面板"恢复"按钮选择快照）
- 手动触发一次备份：`docker exec easyserver-backup restic backup /data /config/.env`（继承容器内 RESTIC_* 环境变量）

## 6. 数据与备份

| 路径 | 内容 |
|------|------|
| `<DATA_DIR>/backups/restic-repo/` | restic 加密仓库（全部快照，700 root 属主） |

本模块自身即备份设施，采用"元备份"视角管理：

- **仓库目录就是全部备份产物**，恢复依赖 `BACKUP_PASSWORD`——密码与仓库需分开保管（密码丢失仓库作废）
- 建议对 `restic-repo/` 做异地副本（rsync 到其他机器/磁盘），形成二级备份
- 保留策略：按 `BACKUP_RETAIN_DAYS`（默认 7 天）自动清理过期快照，实测策略输出正常
- 注意：仓库与被备份数据同盘（`<DATA_DIR>/backups`），磁盘级故障时两者同损，异地副本是唯一兜底

## 7. 卸载

- 面板卸载或 `POST /api/modules/uninstall`；实测返回 `success` + `data_removed:true` + **`removed_paths:[]`**（缺陷 C 族：与 data_removed 语义矛盾）
- **实测确认**：容器已删；`<DATA_DIR>/backups/restic-repo` **保留**（备份产物不被卸载删除——该场景下保留属合理语义，但引擎未如实返回 skipped_paths）
- **实测警告（缺陷 D 第 4 例）**：卸载会**自动删除 `easyserver-backup:latest` 镜像**（本地 build 约 40s 的产物）——重装需重新 build（成本尚低，但需知晓）
- 另注意（缺陷 Q）：卸载/停止/日志 API 按 id 直操作均可用，但 `GET /api/services` 列表**不含手动启动的 backup 容器**（installed_modules 过滤）——API 可见性语义不一致，属已知现象

## 8. FAQ

**Q：面板安装一直失败（failed/pull）？**
实测已知问题：build 型模块走 API install 结构性失败（pull 阶段被 mirror 白名单拒绝，缺陷 N）。按 3.2 降级路径手动 build + up，等待上游修复（检测 `build:` 跳过 pull）。

**Q：BACKUP_PASSWORD 留空可以吗？**
不可以。module.yaml"留空自动生成"无实现（缺陷 O），compose `:?` 硬门控必填。留空时 compose 直接报 `required variable BACKUP_PASSWORD is missing a value`；API 路径则更晚在 pull 阶段失败。

**Q：首次备份需要多长时间？**
取决于数据量。module.yaml 给出参考：7.8GB Jellyfin 数据首次约 10-30 分钟（排除缓存后），后续增量 1-5 分钟。

**Q：如何恢复备份？**
`docker exec easyserver-backup restic restore <快照ID> --target <目标目录>`；或用管理面板"恢复"按钮选择快照（module.yaml faq）。

**Q：实际备份频率和配置不一致？**
见第 4 节调度疑点（缺陷 R）：配置"每天凌晨2点"实测日志报告 7200s（2h）间隔。请以日志为准并关注上游修复。

## 9. 实测排错

实测环境：WSL2 Ubuntu 24.04，docker-ce 29.7.2。关键证据摘录（QA 报告 R15）：

```
# 负面 install 终态（API 路径，未传密码）
failed | pull | 镜像拉取失败（backup） | Image easyserver-backup:latest error from registry:
🚫 👀-> https://github.com/DaoCloud/public-image-mirror/issues/2328 🔗 这镜像不在白名单
# compose 必填校验（宿主侧断言）
$ docker compose -f modules/backup/docker-compose.yml config（无 BACKUP_PASSWORD）
error while interpolating services.backup.environment.[]: required variable BACKUP_PASSWORD is missing
# 首次备份（entrypoint 自动，降级路径）
清理 7 天前的快照... keep 1 snapshots: ca6f2f7f ... Paths /config/.env /data
=== 备份完成: Thu Sep 3 17:06:07 UTC 2026 ===  定时备份间隔: 7200s
# 产物
$ ls -la /data/backups/ → restic-repo (drwx------ root root)
$ docker exec easyserver-backup restic snapshots → ca6f2f7f 2026-09-03 17:06 /config/.env /data
# uninstall
{"success":true,...,"data_removed":true,"removed_paths":[]}
$ docker ps -a → 无 backup 容器；docker images → easyserver-backup 已删；/data/backups/restic-repo 保留
```
