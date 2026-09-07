# Uptime Kuma 监控 · 运行指南

> 基于 2026-09-04 WSL Ubuntu 24.04 实测（QA 报告 R17）。实测为 13 个模块中唯一六阶段 API 全流程一次通过、无人工干预的模块（PASS）。

## 1. 概述

Uptime Kuma 是开源自托管监控工具，支持 HTTP(s)、TCP、Ping、DNS、Docker 容器等监控类型，提供公开状态页面与多渠道告警通知。

| 项 | 值 |
|------|------|
| 镜像 | `louislam/uptime-kuma:2`（2.x 系列） |
| 分类 | infra |
| 网络模式 | bridge（端口映射） |
| 端口 | 宿主 `UPTIME_KUMA_PORT`（默认 3001）→ 容器 3001 |
| 资源限制 | 内存 256m / CPU 0.5 |
| 容器名 | `easyserver-uptime-kuma` |
| 内置 healthcheck | 有（compose 定义，实测显示 healthy） |

## 2. 前置条件

- 核心引擎运行中；无硬依赖模块（soft_depends_on: nginx、acme，仅影响子域名反代访问）
- **端口检查**：3001 需可用。实测环境 3001 被 Windows 侧进程占用（WSL2 mirrored），安装时改用 `UPTIME_KUMA_PORT=13001`
- 数据目录为普通目录挂载，无 filebrowser 式属主问题、无单文件挂载陷阱

## 3. 安装

### 3.1 配置字段

| 字段 | 说明 | 默认值 | 必填 |
|------|------|--------|:---:|
| `UPTIME_KUMA_PORT` | 服务端口（宿主侧） | 3001 | 是 |

### 3.2 安装路径与实测行为

**面板/API 安装**：应用商店 → Uptime Kuma → 安装（或 `POST /api/modules/install {"module_id":"uptime-kuma","config":{"UPTIME_KUMA_PORT":13001}}`）。

实测安装约 5 秒完成（镜像本地命中），一次成功无任何人工干预；容器状态 `Up (healthy)`（compose 自带 healthcheck）。上游 2.x 首次启动会进入数据库选择向导（默认 SQLite，直接确认即可）。

## 4. 启动与验证

```bash
# 容器状态（实测：Up 11 seconds (healthy)）
sudo docker ps --filter name=easyserver-uptime-kuma

# 引擎侧健康检查 URL（module.yaml）
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:13001/api/status-page/monitoring
# 实测输出：200

# 首页（2.x 首启重定向到数据库选择向导，实测行为）
curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}' http://127.0.0.1:13001/
# 实测输出：302 -> http://127.0.0.1:13001/setup-database
```

**初始账号**：无预置账号。首次访问按向导创建管理员账户（自设邮箱与密码），随后添加监控目标。

## 5. 访问方式

- **直连**：`http://<服务器IP>:<UPTIME_KUMA_PORT>`（默认 3001）
- **nginx 反代子域名**：域名反代/混合路由模式下 `https://status.你的域名:8443`（`access.subdomain: status`）
- **Cloudflare Tunnel**：Tunnel 模式下在「服务发布」中发布后经 `https://status.你的域名` 免端口访问

## 6. 数据与备份

| 路径 | 内容 |
|------|------|
| `<DATA_DIR>/uptime-kuma/data/` | 全部数据：SQLite 数据库（kuma.db）、监控配置、历史数据、上传文件 |

备份方法：打包该目录即可。生产环境建议停容器后备份或使用 SQLite 在线备份（`kuma.db` 为活动写入的数据库）。

## 7. 卸载

- 面板卸载或 `POST /api/modules/uninstall`；实测返回 `data_removed:true, removed_paths:["/app/data/uptime-kuma"]`（容器内路径前缀，宿主真实路径 `<DATA_DIR>/uptime-kuma`，缺陷 F 族）
- **实测注意**：卸载后宿主 `<DATA_DIR>/uptime-kuma` 目录残留，可手动删除
- **实测警告（缺陷 D 第 6 例）**：卸载会**自动删除 `louislam/uptime-kuma:2` 镜像**，重装需重新拉取

## 8. FAQ

**Q：监控显示离线但服务正常？**
检查监控目标的 URL 和端口是否正确，确认从容器内网络可达（bridge 网络容器访问宿主服务用宿主 IP 而非 127.0.0.1）。

**Q：如何配置通知？**
设置页面 → 通知渠道，支持邮件、Webhook、Telegram、微信等。

**Q：状态页面如何公开分享？**
设置中创建状态页面，获得公开链接（`/status/<页面名>`），可嵌入任意网页。

**Q：首次访问跳到 /setup-database 是什么？**
2.x 首次启动的数据库选择向导，单机使用选默认 SQLite 即可。

## 9. 实测排错

实测环境：WSL2 mirrored（3001 被占，改 13001）。关键证据摘录：

```
# install 一次通过（~5s，镜像本地命中）
["安装任务已创建...","正在拉取镜像...","镜像就绪，正在启动容器...","安装完成"]
# 健康
$ docker ps --filter name=kuma → easyserver-uptime-kuma Up 11 seconds (healthy)
$ curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}' http://127.0.0.1:13001/
302 -> http://127.0.0.1:13001/setup-database
$ curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:13001/api/status-page/monitoring → 200
# logs 首启输出（正常）
Server Type: HTTP / Data Dir: ./data/ / db-config.json is not found（首启预期）
# uninstall
{"success":true,...,"removed_paths":["/app/data/uptime-kuma"]}
```

> 本模块是 13 个模块中唯一"镜像就绪 + compose 配置正确 + 自带 healthcheck"三者齐备的正面样本；WSL mirrored 环境改端口为常态，本模块配置键真实渲染，换端口顺畅。
