<!--
EasyServer 推广稿 · 掘金快速上手
- 改编母稿：docs/guides/INSTALL_GUIDE.md + QA 实测缺陷 Top5（test-matrix / env-baseline / 模块指南 R10-R22）
- 事实基准：2026-09-04 WSL2 Ubuntu 24.04 完整实测
- 掘金方言：标准 GFM，代码块带语言标注；发布前删除本注释块，替换 IMAGE_PLACEHOLDER-*
- 发布操作（图床替换/自查表/参数表）：见 docs/publish/PUBLISH_CHECKLIST.md
-->

# 手把手从零开始：WSL2 + Docker 部署开源家庭服务器 EasyServer，附实测避坑 Top5

> 一套模块化的自建家庭服务器方案，核心引擎 538 MB，应用商店内置 13 个服务模块，Web 面板可视化管理。本文基于 2026-09-04 WSL2 Ubuntu 24.04 完整实测：前置知识 → 环境准备 → 五步跑通 → 避坑 Top5（全部来自实测缺陷账）。命令可直接复制，WSL2 与原生 Linux 差异处已标注。

## 前置知识

动手前建议对齐这几个概念（已会的直接跳到「环境准备」）：

- **WSL2**：Windows 上的轻量级 Linux 子系统。默认无 systemd（影响 Docker 服务启动方式）、mirrored 网络模式下与 Windows 共享端口视图（影响端口排查）。
- **Docker Compose**：用一份 `docker-compose.yml` 声明多容器服务。本文所有部署动作都是 `build`（构建镜像）+ `up -d`（后台启动）两板斧。
- **registry mirror（镜像加速）**：Docker Hub 在部分网络环境下 DNS 污染/限速（实测 25-40 KB/s），配置镜像加速后走代理源拉取。
- **健康检查（healthcheck）**：容器是否"真活着"的判据。`docker compose ps` 里 `Up (healthy)` 才算数，光 `Up` 不保险。

**环境说明**：本文数据来自 WSL2 + Ubuntu 24.04 实测（docker-ce 29.7.2 · Compose v5.5.0），原生 Linux 服务器流程一致，差异处单独标注。

---

## 环境准备：安装 Docker

### 1. 添加 Docker 官方 apt 源

```bash
sudo apt-get remove -y docker.io docker-doc docker-compose podman-docker containerd runc

sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
| sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

### 2. 安装（实测：apt 必须强制 IPv4）

WSL2 环境下 apt 走 IPv6 链路会 TLS 握手失败（`Could not handshake`），实测解法是所有 apt 命令加 `-o Acquire::ForceIPv4=true`：

```bash
sudo apt-get -o Acquire::ForceIPv4=true install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 3. 配置镜像加速（实测必要）

Docker Hub 直连被 DNS 污染，`docker pull` 超时。以下三个 mirror 实测 `/v2/` 探活可用：

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

### 4. 启动服务 + 用户组

```bash
# WSL2（无 systemd；每次 WSL 启动后需手动执行）
sudo service docker start
sudo service docker status   # "Docker is running"

# 原生 Linux / 云服务器
sudo systemctl enable --now docker

# 用户组（对新登录会话生效；当前会话可用 sg docker -c "..." 过渡）
sudo usermod -aG docker $USER

# 验证
sudo docker version && sudo docker compose version
sudo docker run --rm hello-world   # 输出 "Hello from Docker!" 即成功
```

---

## 快速上手：五步跑通

### Step 1：获取代码

```bash
git clone https://github.com/liangfei-sun/EasyServer.git ~/easyserver
cd ~/easyserver
```

### Step 2：创建 .env（必做，漏掉 up 直接失败）

```bash
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，改两处数据目录为**宿主机真实路径**（默认值是容器内路径，不改会把数据挂到系统根目录）：

```bash
PROJECT_ROOT=/home/<user>/easyserver_data
DATA_DIR=/home/<user>/easyserver_data/data
```

再补一条固定的 JWT 密钥（不预设则容器每次重启换密钥，所有登录失效）：

```bash
echo "JWT_SECRET=$(openssl rand -hex 32)" >> .env
```

### Step 3：构建镜像（给足时间预期）

```bash
docker compose build
```

多阶段构建（python:3.11-slim 后端 + node:20-alpine 前端）。**首次构建实测约 31 分钟**，其中 node 基础层拉取约 29.6 分钟（mirror 限速 25-40 KB/s）；产物镜像约 538 MB。之后构建命中缓存，速度起飞。

> 构建中途 apt 报 `Connection reset by peer` / exit 100：直接重跑 `docker compose build`，已拉取层命中缓存，实测重试即过。

### Step 4：启动

```bash
docker compose up -d
```

entrypoint 自动初始化（建网络、铺 13 个模块的 compose 模板），健康检查通过后容器变 `Up (healthy)`。

### Step 5：初始化 + 验证

```bash
# 验证三连
docker compose ps                      # easyserver-core 应为 Up (healthy)
curl http://localhost:8900/api/health  # {"status":"ok","service":"easyserver-core"}

# 端口被占时（宿主 8900 硬编码，用 override 换 8901）
cat > docker-compose.override.yml <<'EOF'
services:
  easyserver-core:
    ports: !override
      - "127.0.0.1:8901:8000"
EOF
docker compose up -d   # 重建后访问 http://localhost:8901
```

浏览器打开 `http://localhost:8900`（或 8901）进入初始化向导：填主域名 → 填 SSL 邮箱 → 设管理员密码（**单管理员密码认证，无用户名、无默认密码**；Token 实测有效期约 7 天）。完成后面板「应用商店」按需安装模块。

![占位：docker compose ps 容器状态](IMAGE_PLACEHOLDER-compose-ps)

![占位：管理面板初始化向导](IMAGE_PLACEHOLDER-setup-wizard)

---

## 避坑 Top5（全部来自实测缺陷账，非理论推演）

### 坑 1：镜像拉取 600s 超时——先预拉再安装

- **现象**：mirror 限速（实测 25-40 KB/s）下，大镜像（Jellyfin、Frigate、Nextcloud build 等）在安装流程中拉取可能触发约 600s 量级的超时失败。
- **根因**：安装流程内嵌的拉取对慢速链路不友好；超时后任务记为失败。
- **解法**：安装前手动 `docker pull <镜像名>` 预热，本地命中后安装流程直接跳过拉取（实测预拉取生效后，ddns-go 安装仅 3.3s、uptime-kuma 5s 完成）。

```bash
# 例：装 uptime-kuma 前先预热
docker pull louislam/uptime-kuma:2
```

### 坑 2：单文件挂载陷阱——配置文件"变"目录，保存必败

- **现象**：ddns-go 界面正常但配置永远保存不了（日志 `read /root/.ddns_go_config.yaml: is a directory`）；NoteDiscovery 更惨——首次安装 `up` 直接失败（`not a directory` 挂载错误）。
- **根因**：compose 将宿主配置文件按**单文件方式挂载**，引擎不预创建该文件 → Docker 对不存在的源自动创建**同名目录** → 文件挂载变成目录挂载。
- **解法**：安装前预创建真文件：

```bash
sudo mkdir -p <DATA_DIR>/ddns-go/config
sudo touch <DATA_DIR>/ddns-go/config/.ddns_go_config.yaml   # 必须是文件，不能是目录
# 中招后：卸载模块 → sudo rm -rf <DATA_DIR>/ddns-go → 预创建文件 → 重装
```

> NoteDiscovery 还需合法的默认配置内容（空文件会让应用启动即崩），从镜像内提取默认 config.yaml 再放置——细节见仓库 `docs/guides/modules/notediscovery.md`。

### 坑 3：Jellyfin 在 WSL2 host 模式 SIGSEGV 崩溃循环

- **现象**：默认 host 网络模式下容器 `Restarting (139)` 刷屏（SIGSEGV）。
- **根因**：WSL2 mirrored 网络下 .NET 的 host 网络枚举兼容性问题（实测复现，缺陷 W1）。
- **解法**：WSL2 用户改 bridge 模式启动，实测稳定运行（`Startup complete 0:00:17`）：

```bash
cd ~/easyserver/modules/jellyfin
docker pull jellyfin/jellyfin:latest
sg docker -c "JELLYFIN_NETWORK_MODE=bridge DATA_DIR=<数据目录> docker compose -f docker-compose.yml up -d"
```

> 注意：该模块 bridge 模式 compose 暂无端口映射，验证走容器 IP 直连或补 ports 段；`JELLYFIN_PORT` 配置键当前不生效（实测确认），别指望它换端口。

### 坑 4：build 型模块面板安装结构性失败——手动 build 降级

- **现象**：Nextcloud、backup、calibre-web 等面板安装报 `failed(pull)`，重试无效。
- **根因**：引擎对 compose 含 `build:` 的服务仍逐镜像去 registry 拉取，本地构建镜像名被 mirror 白名单拒绝，无本地 fallback（缺陷 N，实测多例实证）。
- **解法**：绕过面板，手动 build + up（实测均通）：

```bash
# Nextcloud（构建约 5 分钟，产物 2.78GB；初始化实测约 40s）
cd ~/easyserver/modules/nextcloud
sg docker -c "docker compose -f docker-compose.yml build"
sg docker -c "NEXTCLOUD_ADMIN_USER=<用户名> NEXTCLOUD_ADMIN_PASSWORD=<密码> \
  NEXTCLOUD_TRUSTED_DOMAINS=<你的域名或IP> DATA_DIR=<数据目录> \
  docker compose -f docker-compose.yml up -d"
```

> Nextcloud 有个独立必踩项：`NEXTCLOUD_TRUSTED_DOMAINS` 默认值是写死的个人域名（缺陷 V），**必须显式传你的域名/IP**，否则访问报 Untrusted domain。

### 坑 5：.env 必做步骤——不做 up 起不来 / 数据挂错位 / 登录反复失效

- **现象**：`docker compose up -d` 报 `env file not found`；或数据出现在系统根目录 `/data`；或容器重启后所有登录失效。
- **根因**：手动安装不会自动创建宿主 `.env`；`.env.example` 默认路径是容器内路径但被用作宿主挂载源；`JWT_SECRET` 缺失则每次重启重新生成。
- **解法**：即 Step 2 的三板斧，一步不能少——`cp .env.example .env` → `chmod 600` → 改 `PROJECT_ROOT`/`DATA_DIR` 为宿主真实路径 → `openssl rand -hex 32` 预设 `JWT_SECRET`。

---

## 装第一个模块：推荐路线

- **Uptime Kuma（监控）**：13 个模块中唯一六阶段一次通过的正面样本，预拉镜像后安装约 5s，自带 healthcheck。
- **FileBrowser（文件管理）**：首装可能 crash loop，根因是数据卷目录属主为 root 而容器以 1000:1000 运行，一条命令修复（实测有效）：

```bash
sudo chown -R 1000:1000 <DATA_DIR>/filebrowser-db <DATA_DIR>/filebrowser
sudo docker restart easyserver-filebrowser
```

- **Frigate（AI 监控）**：ghcr.io 镜像直连健康，面板安装实测可用；无摄像头也全功能可用；多摄像头用户建议给 compose 补 `shm_size: "128mb"`（默认 64MB 会触发 SHM 不足警告）。

**通用建议**：每个模块装完先 `docker compose ps` 看健康状态再开始使用——实测引擎对安装"成功"无健康门控，install 返回 success 不等于容器健康。

---

## 小结

- 五步主线：**clone → .env → build → up → 向导**，核心 10 分钟内可跑通（不含首次构建 31 分钟的镜像拉取等待）。
- 避坑 Top5 全部来自 2026-09-04 WSL2 实测缺陷账：**预拉镜像、单文件挂载预创建、Jellyfin 上 bridge、build 型模块手动 build、.env 三板斧**。
- 更多细节（13 个模块逐个实测、网络五种访问模式配置）见仓库 `docs/guides/`，每篇标注实测环境与缺陷编号。

- 仓库：[https://github.com/liangfei-sun/EasyServer](https://github.com/liangfei-sun/EasyServer)（开源项目 EasyServer，MIT 协议，v0.3.0）
- 觉得有用点个赞，踩到本文之外的坑欢迎评论区贴日志，一起补全避坑清单。

---

> **标签建议**：`Docker`、`Linux`、`运维`、`WSL`（掘金标签以发布页可选为准，建议 3-5 个）
