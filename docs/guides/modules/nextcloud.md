# Nextcloud 私有云盘 · 运行指南

> 基于 2026-09-04 WSL Ubuntu 24.04 实测（QA 报告 R20）。实测结论与上游描述不一致处，以实测为准并已标注。
> **重要预警：本模块为 build 型（基于官方镜像扩展构建，含 ffmpeg），实测面板/API 安装路径结构性失败（缺陷 N）**，需按 3.2 降级路径手动 build + 启动；初始化与服务核心功能实测全通，且初始化速度（约 40s）远快于文档预期（1-3min）。
> **第二预警：`NEXTCLOUD_TRUSTED_DOMAINS` 默认值为写死的个人域名（缺陷 V）**——安装时必须显式传入你的域名/IP，否则本地访问会被拒。

## 1. 概述

Nextcloud 是开源私有云盘：多端文件同步、在线预览（图片/视频/PDF/Office）、外链分享、WebDAV 挂载、手机相册备份与应用生态。本模块为**单容器 SQLite** 方案（自用场景定位），基于官方镜像通过 Dockerfile 扩展安装 ffmpeg（解决官方镜像视频缩略图/预览缺失）。

| 项 | 值 |
|------|------|
| 镜像 | `nextcloud-nextcloud:latest`（**本地 build 产物**，约 2.78GB；基础镜像 `nextcloud:stable` 约 2.21GB） |
| 分类 | files |
| 网络模式 | bridge（端口映射）；双网络：`easyserver-nextcloud-internal` + 外部 `easyserver-proxy` |
| 端口 | 宿主 `NEXTCLOUD_PORT`（默认 8888）→ 容器 80 |
| 资源限制 | 内存 1g / CPU 2.0 |
| 容器名 | `easyserver-nextcloud` |
| 内置 healthcheck | 无（引擎靠模块健康检查 URL `/status.php` 探测） |

## 2. 前置条件

- 核心引擎运行中；无硬依赖模块（soft_depends_on: nginx、acme）
- **管理员凭据**：`NEXTCLOUD_ADMIN_USER`（默认 admin）与 `NEXTCLOUD_ADMIN_PASSWORD`（module.yaml 标 auto_generate"留空自动生成"——同族缺陷 O 模式，未见生成逻辑实现证据，**建议显式设置**；仅首次初始化生效，写入 `.env` 后可查看）
- **信任域必须显式传入（缺陷 V）**：`NEXTCLOUD_TRUSTED_DOMAINS` 默认值为 `cloud.lfblog.top`（模块作者个人域名，写死在模板中）——默认值即不可用，本地 IP/localhost 访问会报 Untrusted domain。**安装时改为你的域名或 IP**（多个用空格分隔，IP 直连需追加服务器 IP）
- **端口检查**：8888 需可用。实测环境 8888 被 Windows 侧占用（WSL2 mirrored），改用 `NEXTCLOUD_PORT=18888`
- build 时长预期：实测约 5 分钟（apt 源已切阿里云，流畅）

## 3. 安装

### 3.1 配置字段

| 字段 | 说明 | 默认值 | 必填 |
|------|------|--------|:---:|
| `NEXTCLOUD_PORT` | 服务端口（宿主侧） | 8888 | 是 |
| `NEXTCLOUD_ADMIN_USER` | 管理员用户名 | admin | 是 |
| `NEXTCLOUD_ADMIN_PASSWORD` | 管理员密码 | 空 | 是（**建议显式设置**，仅首次初始化生效） |
| `NEXTCLOUD_TRUSTED_DOMAINS` | 访问域名（信任域） | **cloud.lfblog.top（缺陷 V，必须改）** | 是 |

> 管理员凭据与信任域均**仅首次初始化时生效**（config.php 生成后不再读取环境变量）。安装后想改信任域，需编辑 `<DATA_DIR>/nextcloud/html/config/config.php` 的 `trusted_domains` 数组后重启容器（module.yaml faq）。

### 3.2 安装路径与实测行为（面板安装当前不可用）

**面板/API 安装（实测失败）**：未重复执行——build 型模块走 API install 结构性失败（缺陷 N，QA 已 3 例实证：引擎对 compose `build:` 服务仍逐镜像 pull，`nextcloud-nextcloud` 本地镜像名被 mirror 白名单拒绝），面板安装当前必失败。

**实测可行的降级路径（手动 build + up）**：

```bash
cd <项目根目录>/modules/nextcloud   # 或运行时目录 /easyserver_data/modules/nextcloud

# 1. 构建镜像（FROM nextcloud:stable + apt 阿里源 + ffmpeg，实测约 5 分钟，产物 2.78GB）
sg docker -c "docker compose -f docker-compose.yml build"

# 2. 启动（务必显式传入信任域与管理员凭据）
sg docker -c "NEXTCLOUD_PORT=18888 \
  NEXTCLOUD_ADMIN_USER=<你的管理员用户名> NEXTCLOUD_ADMIN_PASSWORD=<你的管理员密码> \
  NEXTCLOUD_TRUSTED_DOMAINS=<你的域名或IP> DATA_DIR=<数据目录> \
  docker compose -f docker-compose.yml up -d"
```

实测该路径成功：构建约 5 分钟，容器 Up，首次初始化约 40 秒完成（见第 4 节）。

## 4. 启动与验证

```bash
# 容器状态
sudo docker ps --filter name=easyserver-nextcloud    # 实测：Up

# 引擎侧健康检查 URL（module.yaml）——up 后约 40s 初始化完成
curl -s http://127.0.0.1:18888/status.php
# 实测输出：{"installed":true,"maintenance":false,"needsDbUpgrade":false,
#           "version":"34.0.3.2","productname":"Nextcloud",...}

# 根路径重定向（实测）
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18888/
# 实测输出：302（重定向到 /login）
```

**首次初始化实测约 40 秒**（环境变量式自动初始化：SQLITE_DATABASE + ADMIN_USER/PASSWORD 按官方镜像语义生效）——**快于上游文档预期的 1-3 分钟**。若刚 up 就探测 /status.php 可能短暂 503，属初始化进行中，稍候重试即可。

**初始账号**：安装配置中设置的管理员用户名/密码（教程占位符 `<你的管理员用户名>` / `<你的管理员密码>`）。首次登录后在「设置 → 安全管理」中检查密码与邮件通知（可选）。

## 5. 访问方式

- **直连**：`http://<服务器IP>:<NEXTCLOUD_PORT>`（默认 8888）——信任域需包含该 IP（缺陷 V 处置）
- **nginx 反代子域名**：域名反代/混合路由模式下 `https://cloud.你的域名:8443`（`access.subdomain: cloud`，已内置 `proxy_buffering off` 与不限上传体积）
- **Cloudflare Tunnel**：Tunnel 模式下发布后经 `https://cloud.你的域名` 免端口访问（路由示例：`cloud.你的域名 → http://127.0.0.1:8888`）
- **WebDAV**：`https://cloud.你的域名:8443/remote.php/dav`，可挂载为本地磁盘（module.yaml usage）

## 6. 数据与备份

| 路径 | 内容 |
|------|------|
| `<DATA_DIR>/nextcloud/html/` | 程序与配置（含 `config/config.php`） |
| `<DATA_DIR>/nextcloud/data/` | 用户文件（与程序分离，便于单独备份/迁移） |
| （SQLite 数据库） | 位于配置目录内，无独立数据库容器 |

备份方法（module.yaml faq）：进入维护模式后备份 `data/nextcloud/` 目录，完成再关闭——

```bash
sudo docker exec -it easyserver-nextcloud php occ maintenance:mode --on
# 打包 <DATA_DIR>/nextcloud/ ...
sudo docker exec -it easyserver-nextcloud php occ maintenance:mode --off
```

该目录已纳入 EasyServer backup 模块的备份范围。

## 7. 卸载

- 面板卸载或 `POST /api/modules/uninstall`（`remove_data: true`）；实测 200 success，`easyserver-nextcloud-internal` 网络已删，宿主 `<DATA_DIR>/nextcloud` **残留**（缺陷 F 族，需 sudo 清理）
- **实测警告（缺陷 D 第 10 例）**：卸载会**自动删除 build 产物镜像 `nextcloud-nextcloud:latest`（2.78GB）**——手动 build 成果被撤销，弱网用户重装需重新 build + apt 下载；基础镜像 `nextcloud:stable` 幸存（不在 uninstall 引用范围），build cache 仍在（重 build 会快）
- 重装提醒：数据目录若被手动清理，管理员凭据与信任域将重新初始化

## 8. FAQ

**Q：面板安装一直失败？**
实测已知问题：build 型模块走 API install 结构性失败（缺陷 N）。按 3.2 降级路径手动 build + up。

**Q：访问报 Untrusted domain（不受信任的域名）？**
两种情况：① 安装时未显式传 `NEXTCLOUD_TRUSTED_DOMAINS`（默认值是写死的个人域名，缺陷 V）；② 安装后更换访问域名。处置：编辑 `<DATA_DIR>/nextcloud/html/config/config.php` 的 `trusted_domains` 数组后重启容器（module.yaml faq）；hybrid/IP 直连模式下也可在安装配置的「访问域名」中追加服务器 IP。

**Q：忘记管理员密码？**
`docker exec -it easyserver-nextcloud php occ user:resetpassword admin`（module.yaml faq，按实际用户名替换 admin）。

**Q：视频无法预览/没有缩略图？**
两步排查（module.yaml faq）：① 确认容器内已装 ffmpeg（`docker exec easyserver-nextcloud ffmpeg -version`），缺失时 `docker compose -f modules/nextcloud/docker-compose.yml up -d --build` 重建；② Nextcloud 新版默认未启用视频预览生成器，需用 `occ config:system:set enabledPreviewProviders` 写入（完整命令见 module.yaml usage，含 OC\Preview\Movie 等，配置随数据卷持久化）。mkv 等编码浏览器无法直接播放属浏览器限制，可下载后本地播放。

**Q：上传大文件失败？**
Nginx 反代已默认不限（`client_max_body_size 0`），容器内 PHP 上传限制默认 10G（`PHP_UPLOAD_LIMIT=10G`）；更大文件调整 compose 中该变量后重建（module.yaml faq）。

**Q：如何升级 Nextcloud？**
`docker compose -f modules/nextcloud/docker-compose.yml build --pull && docker compose -f modules/nextcloud/docker-compose.yml up -d`——升级前务必先备份（module.yaml faq）。

## 9. 实测排错

实测环境：WSL2 mirrored（8888 被占，改 18888）、docker-ce 29.7.2。关键证据摘录（QA 报告 R20）：

```
# build（宿主，apt 阿里源，约 5 分钟）
#7 unpacking to docker.io/library/nextcloud-nextcloud:latest 2.9s done
Image nextcloud-nextcloud:latest Built    （2.78GB）
# 首次初始化（up 后约 40s，快于文档预期 1-3min）
$ curl http://127.0.0.1:18888/status.php
{"installed":true,"maintenance":false,"needsDbUpgrade":false,"version":"34.0.3.2",
 "productname":"Nextcloud",...}
# 根路径
$ curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18888/ → 302 → /login
# UI 登录验证说明：curl 模拟登录受 CSRF requesttoken 限制未走通（303 回 login），
# 核心判定以 status.php 为准（QA 任务指定验证点）
# uninstall 后镜像盘点（build 产物被删，缺陷 D 第 10 例）
$ docker images | grep nextcloud → 仅 nextcloud:stable（nextcloud-nextcloud:latest 已被引擎删除）
```
