<!--
EasyServer 推广稿 · CSDN 安装教程
- 改编母稿：docs/guides/INSTALL_GUIDE.md，事实基准：2026-09-04 WSL2 + Ubuntu 24.04 完整实测
- 发布操作（图床替换/自查表/参数表）：见 docs/publish/PUBLISH_CHECKLIST.md
- 发布前：删除本注释块；确认所有 IMAGE_PLACEHOLDER-* 已替换为图床外链
-->

# Windows 上自建家庭服务器：WSL2 + Docker 从零部署开源项目 EasyServer，全流程保姆级教程（附踩坑实录）

> **摘要**：不用公网服务器、不装虚拟机，用 Windows 自带的 WSL2 加 Docker，就能跑起一套模块化的开源自建家庭服务器。本文基于 2026-09-04 WSL2 + Ubuntu 24.04 的完整实测：从 Docker 安装、镜像加速、首次构建（实测约 31 分钟）、`.env` 配置，到初始化向导与端口冲突排查，所有命令、版本号与耗时均来自真实部署验证，非纸上谈兵。

<!-- CSDN 编辑器自带"自动生成目录"功能，发布时可直接使用；下方目录为手写备份 -->

## 目录

- 一、这个项目是什么
- 二、前置条件与平台差异
- 三、安装 Docker（含两个实测网络坑）
- 四、获取代码
- 五、构建与启动（含 .env 必做步骤）
- 六、初始化向导与登录
- 七、端口冲突排查（WSL2 专项）
- 八、部署验证
- 九、常见问题排查表
- 十、写在最后

---

## 一、这个项目是什么

[开源项目 EasyServer（MIT）](https://github.com/liangfei-sun/EasyServer)是一个个人服务器一站式部署方案：模块化架构 + Web 可视化管理 + 一键安装。简单说，它把常被人安利的那些自建服务统一装进一个"应用商店"式的管理面板里，目前内置 **13 个模块、5 个分类**：

- **文件**：Nextcloud 私有云盘、FileBrowser 网页文件管理、Calibre-Web 电子书
- **媒体**：Jellyfin 影音库、Frigate AI 视频监控
- **笔记**：Joplin 笔记同步、NoteDiscovery
- **基础设施**：Nginx 反代、Uptime Kuma 监控、数据备份（restic）
- **网络**：DDNS-Go 动态域名、ACME 证书续签、Cloudflare Tunnel 内网穿透

技术栈是 Python 3.11 + FastAPI + Vue 3，全部跑在 Docker 容器里。核心引擎本体是一个自包含镜像，实测约 **538 MB**，首次部署很轻。

> 💡 **提示**：项目当前版本 v0.3.0，采用 MIT 协议，完整文档在仓库 `docs/` 目录下（安装指南、网络配置指南、13 个模块的逐个实测运行指南）。

---

## 二、前置条件与平台差异

| 项目 | 要求 |
|------|------|
| 平台 | 原生 Linux（Ubuntu 24.04 实测）或 Windows 上的 WSL2 |
| 权限 | 当前用户属于 `sudo` 组 |
| 网络 | 可访问 archive.ubuntu.com、download.docker.com、Docker Hub（或其镜像加速站） |
| 磁盘 | 建议预留 3 GB 以上（镜像 538 MB + 基础层 + 数据卷） |

**WSL2 与原生 Linux 的四个关键差异**（实测整理，建议先看再动手）：

| 事项 | WSL2 | 原生 Linux / 云服务器 |
|------|------|----------------------|
| Docker 服务启动 | 默认无 systemd，用 `sudo service docker start` | `sudo systemctl enable --now docker` |
| 开机自启 | 默认不自启，每次 WSL 启动后手动启动服务 | systemd 自启 |
| 端口视图 | mirrored 模式下与 Windows 共享端口视图，Windows 侧占用会导致绑定失败且 WSL 内查不到 | 正常，`ss`/`lsof` 可查 |
| 端口排查 | 需 `netstat.exe`（见第七节） | 常规工具即可 |

---

## 三、安装 Docker（含两个实测网络坑）

> 已有 Docker（版本 ≥ 24）可跳到 3.3 检查镜像加速配置；`docker compose version` 确认 Compose v2 插件可用即可。

### 3.1 移除冲突包并添加官方源

```bash
sudo apt-get remove -y docker.io docker-doc docker-compose podman-docker containerd runc

sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# 添加 Docker 官方 GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 添加 apt 源（自动适配发行版代号）
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
| sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

未安装的包会提示跳过或 `Unable to locate package`，属正常现象。

### 3.2 实测坑一：apt 强制 IPv4

**实测现象**：`apt-get update` 访问 `download.docker.com` 报 TLS 握手失败，且解析到 IPv6 地址：

```
W: Failed to fetch https://download.docker.com/linux/ubuntu/dists/noble/InRelease
   Could not handshake: Error in the pull function. [IP: 2600:9000:... 443]
```

curl 直连同一地址正常，问题出在 apt/GnuTLS 的 IPv6 链路。**解法：apt 命令统一追加 `-o Acquire::ForceIPv4=true`**：

```bash
sudo apt-get -o Acquire::ForceIPv4=true update
sudo apt-get -o Acquire::ForceIPv4=true install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

> 永久生效可写入 `/etc/apt/apt.conf.d/99force-ipv4`：`Acquire::ForceIPv4 "true";`

实测安装版本：docker-ce **29.7.2**、containerd v2.3.4、Compose **v5.5.0**。

### 3.3 实测坑二：Docker Hub DNS 污染，配置镜像加速

**实测现象**：直接 `docker pull` 时，Docker Hub 的 `registry-1.docker.io` 被 DNS 污染（解析到错误 IPv6 地址），连接超时且重试无效。

**解法**：写入 `/etc/docker/daemon.json` 配置可用的 registry mirror（以下三个地址实测 `/v2/` 探活可用）：

```bash
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.m.daocloud.io",
    "https://dockerproxy.net"
  ]
}
EOF
```

配置后重启 Docker 生效，用 `docker info | grep -A4 "Registry Mirrors"` 确认。

> ⚠️ **注意**：镜像加速站可用性随时间变化，若全部失效请搜索当前可用的镜像源替换。实测限速约 **25-40 KB/s** 属常见情况，拉取大镜像需要耐心（这正是后文"预拉取"和 600s 拉取超时的伏笔）。

### 3.4 启动 Docker 服务

**WSL2（默认无 systemd）**：`systemctl` 会报 `System has not been booted with systemd as init system (PID 1). Can't operate.`，改用 service 方式，**每次 WSL 启动后需手动执行一次**：

```bash
sudo service docker start
sudo service docker status   # 应显示 "Docker is running"
```

**原生 Linux / 云服务器**：

```bash
sudo systemctl enable --now docker
systemctl is-active docker   # 应为 active
```

**可选**：WSL 用户也可在 `/etc/wsl.conf` 中启用 systemd 后使用 systemctl（修改后需在 Windows 侧执行 `wsl.exe --shutdown` 重进生效）：

```ini
[boot]
systemd=true
```

### 3.5 配置 docker 用户组并验证

```bash
sudo usermod -aG docker $USER
```

> ⚠️ **注意**：`usermod` 只对新登录会话生效。当前已打开的 shell 里 `groups` 看不到 docker 组，两种处理：`sg docker -c "docker version"` 临时以 docker 组执行；或关闭终端重开会话。

```bash
sudo docker version        # Client 与 Server 均应输出版本
sudo docker compose version
sudo docker run --rm hello-world   # 输出 "Hello from Docker!" 即成功
```

![占位：Docker 版本与 hello-world 验证截图](IMAGE_PLACEHOLDER-docker-version)

---

## 四、获取代码

```bash
git clone https://github.com/liangfei-sun/EasyServer.git ~/easyserver
cd ~/easyserver
```

> 💡 **提示**：README 中的克隆地址为 SSH 形式（`git@github.com:...`），需先在 GitHub 配置 SSH key；未配置时请使用上方 HTTPS 地址，功能完全一致。

---

## 五、构建与启动（含 .env 必做步骤）

### 5.1 构建镜像：先给一个真实的时间预期

```bash
docker compose build
```

构建为多阶段构建：`python:3.11-slim` 构建后端 + `node:20-alpine` 编译前端。**实测耗时（重点）**：

| 阶段 | 实测耗时 |
|------|---------|
| 首次构建总计 | **约 31 分钟** |
| 其中 node 基础层拉取 | 约 29.6 分钟（mirror 限速 25-40 KB/s） |
| 产物镜像 | `easyserver/core` 约 538 MB |

基础层拉取成功后，后续构建命中缓存，速度大幅提升；进度条长时间停在拉取层属正常现象。

> ❗ **避坑**：首次构建曾因 Dockerfile 内 apt 访问 `download.docker.com` 被间歇重置而失败（exit 100，`Connection reset by peer`）。**直接重新执行 `docker compose build` 即成功**——已拉取层命中缓存，重试成本很低。别慌，先重试。

![占位：首次构建完成输出](IMAGE_PLACEHOLDER-build-log)

### 5.2 创建 .env（必做步骤，漏了直接起不来）

**手动安装方式下，宿主机的 `.env` 不会被自动创建**，而 `docker-compose.yml` 声明了 `env_file: .env`，缺失时 `docker compose up -d` 直接失败（`env file not found`）：

```bash
cp .env.example .env
chmod 600 .env
```

**修正数据目录路径（重要）**：`.env.example` 默认的 `DATA_DIR=/data`、`PROJECT_ROOT=/easyserver_data` 是容器内路径，但这两个变量同时被 compose 用作**宿主机卷挂载源**。保持默认会把数据目录挂载到系统根目录 `/data` 与 `/easyserver_data`。建议改为真实宿主机路径：

```bash
# 编辑 .env 修改以下两项
PROJECT_ROOT=/home/<user>/easyserver_data
DATA_DIR=/home/<user>/easyserver_data/data
```

**预设 JWT_SECRET（建议）**：未预设时容器每次重启都会生成新的随机密钥，导致所有已登录用户的 Token 失效：

```bash
echo "JWT_SECRET=$(openssl rand -hex 32)" >> .env
```

### 5.3 启动

```bash
docker compose up -d
```

首次启动时 entrypoint 自动完成初始化（实测确认）：生成运行时配置、创建 Docker 网络、从镜像内置模板初始化 13 个模块的 compose 目录。健康检查通过后容器状态变为 `Up (healthy)`。

---

## 六、初始化向导与登录

浏览器打开 `http://localhost:8900`，首次访问会进入极简初始化向导，共三步：

1. **填写主域名**（如 `example.com`，无域名可填占位值，后续在网络配置中修改）
2. **填写 SSL 邮箱**（用于 Let's Encrypt 证书通知）
3. **设置管理员密码**——这是系统唯一的登录凭据

> 💡 **提示**（实测确认）：系统**没有用户名概念，也没有默认密码**——采用单管理员密码认证，密码在向导中自行设置。JWT Token 实测有效期约 **7 天**，过期后重新登录即可。

![管理面板初始化向导](../../images/setup-wizard.png)

*图：初始化向导——填主域名、SSL 邮箱、设管理员密码三步即完成。*

喜欢用 API 的朋友，向导也有等价的 REST 接口（完整 Swagger UI 在 `/docs`）：

```bash
# 完成初始化（写入域名、SSL 邮箱并设置管理密码）
curl -s -X POST http://localhost:8900/api/config/setup \
  -H 'Content-Type: application/json' \
  -d '{"domain":"example.com","ssl_email":"admin@example.com","admin_password":"<你的管理密码>"}'

# 登录换取 JWT Token（实测 body 只需密码，无用户名字段）
curl -s -X POST http://localhost:8900/api/config/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"password":"<你的管理密码>"}'
```

认证行为实测要点：`/api/health`、`/docs`、前端面板公开可达；`/api/config`、`/api/modules`、`/api/services` 均需携带 `Authorization: Bearer <token>`。

---

## 七、端口冲突排查（WSL2 专项）

`docker-compose.yml` 的端口映射为 `${BIND_ADDRESS:-127.0.0.1}:8900:8000`：宿主侧默认只绑 `127.0.0.1:8900`（面板默认仅本机可访问，安全），**宿主端口 8900 为硬编码值，无法通过环境变量修改**。

### 7.1 端口被占用：用 override 换端口（推荐 8901）

创建 `docker-compose.override.yml`（与主 compose 同目录，compose 自动合并），用 `!override` 标签整体替换端口映射：

```yaml
services:
  easyserver-core:
    ports: !override
      - "127.0.0.1:8901:8000"
```

然后 `docker compose up -d` 重建容器，改用 `http://localhost:8901` 访问。实测此方式有效（QA 环境全程使用 8901）。

### 7.2 WSL2 mirrored 模式专项：WSL 里查不到的端口占用

**实测现象**：WSL2 mirrored 模式下，Windows 宿主侧进程（如 IDE 的端口监听）占用 `127.0.0.1:8900` 会导致容器端口绑定失败（`address already in use`）；此时在 **WSL 内**用 `ss` / `lsof` **查不到任何占用**，极具迷惑性。

**排查方式**：在 **Windows 侧**（PowerShell/CMD）或 WSL 内调用 Windows 工具：

```bash
/mnt/c/Windows/System32/netstat.exe -ano | findstr 8900
```

若有输出，最后一列为 PID，在 Windows 侧用 `tasklist /fi "PID eq <PID>"` 定位进程（Windows 侧进程请勿强行杀掉），解决方式同 7.1 换端口。

### 7.3 port-check 接口

```bash
curl -s http://localhost:8900/api/services/port-check
```

返回 `{"has_conflict":false,"conflicts":[],...}` 并列出全部注册模块的端口清单。实测注意：**即使尚未安装任何模块，该接口也会列出全部注册模块端口**（实测 10 个）——这是"系统规划的端口全景"，不是已安装清单，解读时注意区分。

---

## 八、部署验证

```bash
# 1. 容器状态
docker compose ps          # easyserver-core 应为 Up (healthy)

# 2. 健康检查接口（公开，无需认证）
curl http://localhost:8900/api/health
# 预期返回：{"status":"ok","service":"easyserver-core"}

# 3. 面板访问
# 浏览器打开 http://localhost:8900，完成第六节的初始化向导
```

三项全部通过即部署成功。此后可在面板「应用商店」按需安装服务模块（初始不安装任何模块）。

![占位：健康检查与容器状态验证](IMAGE_PLACEHOLDER-health-check)

---

## 九、常见问题排查表

| 现象 | 原因 | 解决方式 |
|------|------|----------|
| `apt-get update` 报 `Could not handshake` | apt 走 IPv6 链路 TLS 握手失败 | apt 命令加 `-o Acquire::ForceIPv4=true`（见 3.2） |
| `docker pull` 报 `i/o timeout` / `dial tcp` 错误 IP | Docker Hub DNS 污染 | 按 3.3 配置 daemon.json mirror 后重启 Docker |
| `systemctl` 报 `System has not been booted with systemd` | WSL 未启用 systemd | 用 `sudo service docker start`（见 3.4） |
| `docker compose up -d` 报 `env file not found` | 宿主机 `.env` 未创建 | `cp .env.example .env && chmod 600 .env`（见 5.2） |
| 数据出现在系统根目录 `/data`、`/easyserver_data` | `.env` 中路径保持容器内默认值 | 按 5.2 改为宿主机真实路径 |
| 重启容器后所有登录失效 | 未预设 `JWT_SECRET`，每次重启重新生成 | 按 5.2 预设固定密钥 |
| 端口绑定失败但 WSL 内 `ss`/`lsof` 查无占用 | mirrored 模式下 Windows 侧占用端口 | `netstat.exe -ano \| findstr 8900` 排查，override 换 8901（见第七节） |
| `docker compose build` 中途 apt 报 `Connection reset by peer` / exit 100 | 构建内网络间歇故障 | **直接重试**，已拉取层命中缓存（见 5.1） |
| 模块安装约 600s 后拉取超时失败（`failed(pull)`） | mirror 限速下安装流程内嵌拉取超时 | 安装前先 `docker pull <镜像名>` 预热（本地命中后拉取环节秒级完成；引擎仍会执行 pull），细节见仓库 `docs/guides/modules/` 对应篇 |
| 当前用户无法直接执行 `docker` 命令 | 用户组未在当前会话刷新 | `sg docker -c "<命令>"` 或重新登录（见 3.5） |
| 登录接口返回 401 | 密码错误或 setup 未完成 | 确认已完成初始化向导；密码无找回与重置机制（截至 v0.3.0 官方文档未提供重置流程），务必妥善保管，如确认丢失可在项目 issue 求助 |
| WSL 重启后面板无法访问 | Docker 服务未随 WSL 启动 | `sudo service docker start` 后 `docker compose up -d` |

---

## 十、写在最后

这套流程走下来，WSL2 环境真正需要"额外功课"的只有四件事：**apt 强制 IPv4、Docker 镜像加速、每次启动手动起 Docker 服务、mirrored 模式的端口排查**。其余部分与原生 Linux 部署完全一致。

代码更新后重建镜像：

```bash
docker compose build && docker compose up -d
```

> ❗ **down 提醒**：`docker compose down` 会删除容器并触发配置重新初始化（管理密码等 setup 配置会丢）。跨 down 保留核心配置，可在 override 中加命名卷 `easyserver-app-data:/app/data`（实测有效，详见仓库 `docs/guides/INSTALL_GUIDE.md` 第 9 节；`/app/.env` 与模块级配置不在此列，down 后重新登录/配置即可）；日常启停用 `stop`/`restart` 最稳妥。

装好核心之后，下一步就是把服务装起来、把网络访问配出去——这部分（域名反代 / IPv6 直连 / Cloudflare Tunnel / 智能混合路由五种方式怎么选）我在下一篇网络配置教程里展开，欢迎关注。

- 仓库地址：[https://github.com/liangfei-sun/EasyServer](https://github.com/liangfei-sun/EasyServer)（开源项目 EasyServer，MIT 协议）
- 本文所有数据基于 2026-09-04 WSL2 Ubuntu 24.04 实测，环境不同可能有差异，欢迎评论区交流你的实测结果。

**互动一下**：你的家庭服务器都跑了哪些服务？是云服务器党、NAS 党还是 WSL 折腾党？评论区聊聊，遇到部署问题也可以贴报错信息，看到都会回。觉得有用的话，**点赞 + 收藏**防止迷路，**关注**看后续网络配置篇。

---

> **标签建议**：`docker` `linux` `运维` `nginx`（可加：`wsl` `家庭服务器`）
