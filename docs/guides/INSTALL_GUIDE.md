# EasyServer 安装指南

> 本指南基于 **WSL2 + Ubuntu 24.04 (Noble) 完整实测**编写，适用于原生 Linux 服务器与 WSL 环境，平台差异处均已标注。所有命令、版本号与系统行为均来自真实部署验证。
>
> 实测版本：docker-ce 29.7.2 · Docker Compose v5.5.0 · 镜像 `easyserver/core` 约 538 MB · 模块注册表共 **13 个模块**（5 个分类）。
>
> 基线版本 v0.3.0（commit 8116713）；上游升级端口参数化/模块数变化后本文数据需复核。

---

## 目录

- [1. 前置条件](#1-前置条件)
- [2. 安装 Docker](#2-安装-docker)
- [3. 获取代码](#3-获取代码)
- [4. 构建与启动](#4-构建与启动)
- [5. 初始化向导](#5-初始化向导)
- [6. 端口冲突排查](#6-端口冲突排查)
- [7. 验证](#7-验证)
- [8. 常见问题排查表](#8-常见问题排查表)

---

## 1. 前置条件

| 项目 | 要求 |
|------|------|
| 平台 | 原生 Linux（Ubuntu 24.04 实测）或 Windows 上的 WSL2 |
| 权限 | 当前用户属于 `sudo` 组 |
| 网络 | 可访问 `archive.ubuntu.com`、`download.docker.com`、Docker Hub（或其镜像加速站） |
| 磁盘 | 建议预留 3 GB 以上（镜像 538 MB + 基础层 + 数据卷） |

### 平台差异速览

| 事项 | WSL2 | 原生 Linux / 云服务器 |
|------|------|----------------------|
| Docker 服务启动 | 默认无 systemd，用 `sudo service docker start` | `sudo systemctl enable --now docker` |
| 开机自启 | 默认不自启，每次 WSL 启动后手动启动服务 | systemd 自启 |
| 端口视图 | mirrored 模式下与 Windows 共享端口视图，Windows 侧占用会导致绑定失败且 WSL 内查不到 | 正常，`ss`/`lsof` 可查 |
| 端口排查 | 需 `netstat.exe`（见第 6 节） | 常规工具即可 |

---

## 2. 安装 Docker

> 已有 Docker（版本 ≥ 24）可跳到 2.5 检查镜像加速配置；`docker compose version` 确认 Compose v2 插件可用即可。

### 2.1 移除冲突包（如存在）

```bash
sudo apt-get remove -y docker.io docker-doc docker-compose podman-docker containerd runc
```

未安装的包会提示跳过或 `Unable to locate package`，属正常现象，用 `dpkg -l <包名>` 确认无已安装残留即可。

### 2.2 安装依赖并添加官方 apt 源

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# 添加 Docker 官方 GPG key（指纹应为 9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88）
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 添加 apt 源（自动适配发行版代号）
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
| sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

### 2.3 网络问题一：apt 强制 IPv4（实测必要）

**实测现象**：`apt-get update` 访问 `download.docker.com` 报 TLS 握手失败，且解析到 IPv6 地址：

```
W: Failed to fetch https://download.docker.com/linux/ubuntu/dists/noble/InRelease
   Could not handshake: Error in the pull function. [IP: 2600:9000:... 443]
```

curl 直连同一地址正常，问题出在 apt/GnuTLS 的 IPv6 链路。**解决：apt 命令统一追加 `-o Acquire::ForceIPv4=true`**：

```bash
sudo apt-get -o Acquire::ForceIPv4=true update
```

> 永久生效可写入 `/etc/apt/apt.conf.d/99force-ipv4`：`Acquire::ForceIPv4 "true";`

### 2.4 安装 Docker Engine

```bash
sudo apt-get -o Acquire::ForceIPv4=true install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

实测安装版本：docker-ce `29.7.2`、containerd `v2.3.4`、runc `1.4.3`、Compose `v5.5.0`。

### 2.5 网络问题二：配置镜像加速（实测必要）

**实测现象**：直接 `docker pull` 时 Docker Hub 的 `registry-1.docker.io` 被 DNS 污染（解析到错误 IPv6 地址），连接超时，重试无效。

**解决**：写入 `/etc/docker/daemon.json` 配置可用的 registry mirror（以下三个地址实测 `/v2/` 探活可用）：

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

> 镜像加速站可用性随时间变化，若全部失效请搜索当前可用的镜像源替换。实测限速约 25-40 KB/s 属常见情况，拉取大镜像需要耐心（见 4.1 耗时预期）。

### 2.6 启动 Docker 服务

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

### 2.7 配置 docker 用户组

```bash
sudo usermod -aG docker $USER
```

**注意**：`usermod` 只对新登录会话生效。当前已打开的 shell 中 `groups` 看不到 docker 组，两种处理方式：

```bash
# 方式一：当前会话临时以 docker 组身份执行
sg docker -c "docker version"

# 方式二：关闭终端重新打开 WSL/SSH 会话，之后直接使用 docker 命令
docker version
```

### 2.8 安装验证

```bash
sudo docker version        # Client 与 Server 均应输出版本
sudo docker compose version
sudo docker run --rm hello-world   # 输出 "Hello from Docker!" 即成功
```

---

## 3. 获取代码

```bash
git clone https://github.com/liangfei-sun/EasyServer.git ~/easyserver
cd ~/easyserver
```

> **说明**：README 中的克隆地址为 SSH 形式（`git@github.com:...`），需先在 GitHub 配置 SSH key；未配置时请使用上方 HTTPS 地址，功能完全一致。

---

## 4. 构建与启动

### 4.1 构建镜像

```bash
docker compose build
```

构建为多阶段构建：`python:3.11-slim` 构建后端 + `node:20-alpine` 编译前端（Vue）。**耗时预期（实测）**：

| 阶段 | 实测耗时 |
|------|---------|
| 首次构建总计 | 约 31 分钟 |
| 其中 node 基础层拉取 | 约 29.6 分钟（mirror 限速 25-40 KB/s） |
| 产物镜像 | `easyserver/core` 约 538 MB |

> 基础层拉取成功后，后续构建命中缓存，速度大幅提升。进度条长时间停留在拉取层属正常现象。

**构建失败先重试（实测经验）**：首次构建曾因 Dockerfile 内 apt 访问 `download.docker.com` 被间歇重置而失败（`docker-ce-cli has no installation candidate`，exit 100，上游表现为 `Connection reset by peer`）。**直接重新执行 `docker compose build` 即成功**，已拉取层命中缓存，重试成本低。

**附带提示**：`python:3.11-slim` 基础镜像已基于 Debian trixie，而 Dockerfile 硬编码 bookworm apt 源，实测当前不构成致命问题；若未来构建出现 apt 源 404 类错误，可关注此处。

### 4.2 创建 .env（必做步骤）

**手动安装方式下，宿主机的 `.env` 不会被自动创建**，而 `docker-compose.yml` 声明了 `env_file: .env`，缺失时 `docker compose up -d` 直接失败（`env file not found`）：

```bash
cp .env.example .env
chmod 600 .env
```

> **注意**：README 中"`.env` 由 entrypoint 自动生成"仅指**容器内**挂载卷中的运行时配置。宿主机项目根目录下的 `.env`（compose 的 env_file）只有 `scripts/install.sh` 方式会自动创建，手动安装必须自行复制。上游 `docs/quick-start.md` 中"无需手动创建"的表述针对脚本安装路径，不适用于手动安装路径。

**修正数据目录路径（重要）**：`.env.example` 默认的 `DATA_DIR=/data`、`PROJECT_ROOT=/easyserver_data` 是**容器内路径**（由 entrypoint 在容器内设置），但这两个变量同时被 compose 用作**宿主机卷挂载源**。保持默认会把数据目录挂载到系统根目录 `/data` 与 `/easyserver_data`。建议改为真实宿主机路径：

```bash
# 编辑 .env 修改以下两项
PROJECT_ROOT=/home/<user>/easyserver_data
DATA_DIR=/home/<user>/easyserver_data/data
```

**预设 JWT_SECRET（建议）**：未预设时容器每次重启都会生成新的随机密钥，导致所有已登录用户的 Token 失效：

```bash
echo "JWT_SECRET=$(openssl rand -hex 32)" >> .env
```

### 4.3 启动

```bash
docker compose up -d
```

首次启动时 entrypoint 自动完成初始化（实测确认）：在挂载卷内生成运行时 `.env`、创建/复用 `easyserver-proxy` Docker 网络、从镜像内置模板初始化 modules 目录（**13 个模块**的 compose 模板）、Uvicorn 监听 `0.0.0.0:8000`。健康检查（`GET /api/health`）通过后容器状态变为 `Up (healthy)`。

---

## 5. 初始化向导

首次访问管理面板会进入极简初始化向导，实测流程与行为如下。

### 5.1 向导内容

1. **填写主域名**（如 `example.com`，无域名可填占位值，后续在网络配置中修改）
2. **填写 SSL 邮箱**（用于 Let's Encrypt 证书通知）
3. **设置管理员密码**——这是系统唯一的登录凭据

### 5.2 实测 API 流程（等价于 UI 向导）

```bash
# 1. 完成初始化（写入域名、SSL 邮箱并设置管理密码）
curl -s -X POST http://localhost:8900/api/config/setup \
  -H 'Content-Type: application/json' \
  -d '{"domain":"example.com","ssl_email":"admin@example.com","admin_password":"<你的管理密码>"}'

# 2. 登录换取 JWT Token（实测 body 只需密码，无用户名字段）
curl -s -X POST http://localhost:8900/api/config/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"password":"<你的管理密码>"}'
# 返回：{"token":"eyJ...","success":true}
```

**默认账号说明（实测）**：系统**没有用户名概念，也没有默认密码**——采用单管理员密码认证，密码在初始化向导（或 `POST /api/config/setup`）中自行设置。JWT Token 实测有效期约 7 天，过期后重新登录获取。

### 5.3 认证行为矩阵（实测）

| 端点 | 未认证 | 带 `Authorization: Bearer <token>` | 说明 |
|------|:---:|:---:|------|
| `GET /api/health` | 200 | 200 | 公开健康检查 |
| `/docs`、`/openapi.json` | 200 | 200 | Swagger UI 公开可达 |
| `GET /`（前端面板） | 200 | 200 | 公开 |
| `GET /api/config` | 401 | 200 | 需 JWT |
| `GET /api/modules` | 401 | 200 | 需 JWT |
| `GET /api/services` | 401 | 200 | 需 JWT |

> 除白名单接口（`/api/health`、登录、setup）外，所有 API 调用（含读操作）均需携带 Bearer Token。

---

## 6. 端口冲突排查

`docker-compose.yml` 的端口映射为 `${BIND_ADDRESS:-127.0.0.1}:8900:8000`：宿主侧默认绑定 `127.0.0.1:8900`，**宿主端口 `8900` 为硬编码值，无法通过环境变量修改**。

### 6.1 端口被占用时：用 override 换端口（推荐 8901）

创建 `docker-compose.override.yml`（与主 compose 同目录，compose 自动合并），用 `!override` 标签整体替换端口映射：

```yaml
services:
  easyserver-core:
    ports: !override
      - "127.0.0.1:8901:8000"
```

然后 `docker compose up -d` 重建容器，改用 `http://localhost:8901` 访问。实测此方式有效（QA 环境全程使用 8901）。

> 也可直接修改 `docker-compose.yml` 中的 `8900`，但 override 文件不改动上游文件，更新代码时不易冲突。

### 6.2 WSL2 mirrored 网络模式专项排查

**实测现象**：WSL2 mirrored 模式下，Windows 宿主侧进程（如 IDE 的端口监听）占用 `127.0.0.1:8900` 会导致容器端口绑定失败（`address already in use`）；此时在 **WSL 内**用 `ss` / `lsof` **查不到任何占用**，极具迷惑性。

**排查方式**：在 **Windows 侧**（PowerShell/CMD）或 WSL 内调用 Windows 工具：

```bash
/mnt/c/Windows/System32/netstat.exe -ano | findstr 8900
```

若有输出，最后一列为 PID，在 Windows 侧用 `tasklist /fi "PID eq <PID>"` 定位进程。解决方式同 6.1 换端口（Windows 侧进程请勿强行杀掉）。

### 6.3 port-check 接口（实测行为说明）

```bash
# 该接口需认证：先登录换取 TOKEN（sed 提取），再携带 Bearer 头调用
TOKEN=$(curl -s -X POST http://localhost:8900/api/config/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"password":"<你的管理密码>"}' | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8900/api/services/port-check
```

返回 `{"has_conflict":false,"conflicts":[],...}` 并**列出全部注册模块的端口清单**。实测注意：**即使尚未安装任何模块（空安装态），该接口也会列出全部注册模块端口**（实测 10 个），这是当前实现行为，并非已安装清单，解读时注意区分。

---

## 7. 验证

```bash
# 1. 容器状态
docker compose ps          # easyserver-core 应为 Up (healthy)

# 2. 健康检查接口（公开，无需认证）
curl http://localhost:8900/api/health
# 预期返回：{"status":"ok","service":"easyserver-core"}

# 3. 面板访问
# 浏览器打开 http://localhost:8900，完成第 5 节的初始化向导
```

三项全部通过即部署成功。此后可在面板「应用商店」按需安装服务模块（初始不安装任何模块）。各模块的安装前置与实测行为，详见 `docs/guides/modules/<模块名>.md`（共 13 篇）。

---

## 8. 常见问题排查表

| 现象 | 原因 | 解决方式 |
|------|------|----------|
| `apt-get update` 报 `Could not handshake` | apt 走 IPv6 链路 TLS 握手失败 | apt 命令加 `-o Acquire::ForceIPv4=true`（见 2.3） |
| `docker pull` 报 `i/o timeout` / `dial tcp` 错误 IP | Docker Hub DNS 污染 | 按 2.5 配置 daemon.json mirror 后重启 Docker |
| `systemctl` 报 `System has not been booted with systemd` | WSL 未启用 systemd | 用 `sudo service docker start`（见 2.6） |
| `docker compose up -d` 报 `env file not found` | 宿主机 `.env` 未创建 | `cp .env.example .env && chmod 600 .env`（见 4.2） |
| 数据出现在系统根目录 `/data`、`/easyserver_data` | `.env` 中路径保持容器内默认值 | 按 4.2 改为宿主机真实路径 |
| 重启容器后所有登录失效 | 未预设 `JWT_SECRET`，每次重启重新生成 | 按 4.2 预设固定密钥 |
| 端口绑定失败但 WSL 内 `ss`/`lsof` 查无占用 | mirrored 模式下 Windows 侧占用端口 | `netstat.exe -ano \| findstr 8900` 排查，override 换 8901（见第 6 节） |
| `docker compose build` 中途 apt 报 `Connection reset by peer` / exit 100 | 构建内网络间歇故障 | **直接重试**，已拉取层命中缓存（见 4.1） |
| 模块安装约 600s 后拉取超时失败（`failed(pull)`） | mirror 限速下安装流程内嵌拉取超时 | 安装前先 `docker pull <镜像名>` 预热（引擎仍会执行 pull，本地命中后秒级完成；被镜像源拒绝的精确 tag 预拉取无法绕过） |
| 当前用户无法直接执行 `docker` 命令 | 用户组未在当前会话刷新 | `sg docker -c "<命令>"` 或重新登录（见 2.7） |
| 登录接口返回 401 | 密码错误或 setup 未完成 | 确认已完成初始化向导；密码无找回与重置机制（截至 v0.3.0 官方文档未提供重置流程），务必妥善保管，如确认丢失可在项目 issue 求助 |
| 容器内运行 healthcheck.sh 报 401 / exit 127 | 已知脚本缺陷：API 检查项无认证头（setup 完成后必报 401）；DOMAIN 非空时依赖的 `dig` 不存在导致 `set -e` 崩溃 | 以 `/api/health` 与 compose ps 的 healthy 状态为准，脚本输出暂不作为判据 |
| WSL 重启后面板无法访问 | Docker 服务未随 WSL 启动 | `sudo service docker start` 后 `docker compose up -d` |

---

## 9. 清理与重启

```bash
# 停止并移除容器与网络（保留镜像与数据卷）
docker compose down

# 重新启动
docker compose up -d

# 代码更新后重建镜像
docker compose build && docker compose up -d
```

WSL 环境重启后需先 `sudo service docker start`（未启用 systemd 时）；容器配置了 `restart: unless-stopped`，Docker 服务恢复后通常会随之自动启动，用 `docker compose ps` 确认。
