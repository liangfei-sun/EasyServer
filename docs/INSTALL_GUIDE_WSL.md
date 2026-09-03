# EasyServer WSL 安装指南（Ubuntu 24.04）

> 本文档基于 WSL2 + Ubuntu 24.04 (Noble) 的**真实部署实测**编写，覆盖 Docker 安装、镜像构建、配置启动全流程，并记录实测中遇到的典型问题与解决方式。适用于在 Windows 上通过 WSL 运行 EasyServer 的场景。
>
> 实测环境版本：docker-ce 29.7.2、Docker Compose v5.5.0、分支 `feature/wsl-install-test`（commit `8116713`）。

---

## 1. 前置条件

| 项目 | 要求 |
|------|------|
| Windows | Windows 10 2004+ / Windows 11，已启用 WSL2 |
| 发行版 | Ubuntu 24.04 (Noble)，其他版本未实测 |
| 权限 | 当前用户属于 `sudo` 组，可执行系统级命令 |
| 网络 | 可访问 `archive.ubuntu.com`、`download.docker.com`、Docker Hub（或其镜像站） |

确认 WSL 版本：

```bash
wsl.exe -l -v   # 在 Windows 侧执行，VERSION 应为 2
```

---

## 2. 安装 Docker

### 2.1 移除冲突包（如存在）

```bash
sudo apt-get remove -y docker.io docker-doc docker-compose podman-docker containerd runc
```

> 未安装的包会提示跳过；若提示 `Unable to locate package` 可忽略，用 `dpkg -l <包名>` 确认无残留即可。

### 2.2 安装依赖并添加官方 apt 源

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# 添加 Docker 官方 GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 添加 apt 源（noble）
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
| sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

### 2.3 网络问题：apt 强制 IPv4（实测必要）

**实测现象**：`apt-get update` 访问 `download.docker.com` 时报 TLS 握手失败：

```
W: Failed to fetch https://download.docker.com/linux/ubuntu/dists/noble/InRelease
   Could not handshake: Error in the pull function. [IP: 2600:9000:... 443]
```

curl 直连同一地址正常，问题出在 apt/GnuTLS 走 IPv6 的链路上。**解决方式：对 apt 命令统一追加 `-o Acquire::ForceIPv4=true`**：

```bash
sudo apt-get -o Acquire::ForceIPv4=true update
```

> 若希望永久生效，可写入 `/etc/apt/apt.conf.d/99force-ipv4`：`Acquire::ForceIPv4 "true";`

### 2.4 安装 Docker Engine

```bash
sudo apt-get -o Acquire::ForceIPv4=true install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

实测安装版本：docker-ce `29.7.2`、containerd `v2.3.4`、runc `1.4.3`、Compose `v5.5.0`。

### 2.5 配置镜像加速（实测必要）

**实测现象**：直接 `docker pull` 时 Docker Hub 的 `registry-1.docker.io` 被 DNS 污染（解析到错误 IPv6 地址），连接超时，重试无效。

**解决方式**：在 `/etc/docker/daemon.json` 配置可用的 registry mirror（以下三个地址实测可用，`/v2/` 探活正常）：

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

配置后重启 Docker 生效（见 2.6），可用 `docker info | grep -A4 "Registry Mirrors"` 确认。

> 镜像加速站可用性随时间变化，若全部失效可搜索当前可用的镜像源替换。

### 2.6 启动 Docker 服务

**WSL 默认未启用 systemd**（PID 1 不是 systemd），`systemctl` 会报错：

```
System has not been booted with systemd as init system (PID 1). Can't operate.
```

**方式一（默认）**：用 `service` 启动，每次 WSL 启动后需手动执行一次：

```bash
sudo service docker start
sudo service docker status   # 应显示 "Docker is running"
```

**方式二（可选）**：在 `/etc/wsl.conf` 中启用 systemd，之后可正常使用 `systemctl enable --now docker`：

```ini
[boot]
systemd=true
```

修改后需在 Windows 侧执行 `wsl.exe --shutdown` 并重新进入 WSL 生效。启用 systemd 属可选方案，未启用时方式一完全够用。

### 2.7 配置 docker 用户组

```bash
sudo usermod -aG docker $USER
```

**注意**：`usermod` 只对新登录会话生效。当前已打开的 shell 中用户组不会刷新（`groups` 看不到 docker），有两种处理方式：

```bash
# 方式一：当前会话临时以 docker 组身份执行命令
sg docker -c "docker version"

# 方式二：关闭终端重新打开 WSL 会话，之后直接使用 docker 命令
docker version
```

### 2.8 安装验证

```bash
sudo docker version        # Client 与 Server 均应正常输出版本
sudo docker compose version
sudo docker run --rm hello-world
```

`hello-world` 输出 `Hello from Docker!` 即安装成功。

---

## 3. 获取代码

```bash
mkdir -p ~/projects
git clone https://github.com/liangfei-sun/EasyServer.git ~/projects/easyserver
cd ~/projects/easyserver
```

> **说明**：项目 README 中的克隆地址为 SSH 形式（`git@github.com:...`），需先在 GitHub 配置 SSH key。未配置 SSH key 时请使用上方的 HTTPS 地址，功能完全一致。

---

## 4. 构建镜像

```bash
docker compose build
```

### 4.1 耗时预期

构建为多阶段构建：`python:3.11-slim` 构建后端 + `node:20-alpine` 编译前端（Vue）。**实测总耗时约 31 分钟**，其中绝大部分消耗在拉取 node 基础镜像层（约 29.6 分钟，镜像加速站限速约 25-40 KB/s）。构建完成产物 `easyserver/core` 镜像约 **538 MB**。

> 首次构建请耐心等待，进度条长时间停留在拉取层属正常现象。基础层拉取成功后，后续构建会命中缓存，速度大幅提升。

### 4.2 构建失败先重试（实测经验）

**实测现象**：首次构建失败，原因为 Dockerfile 内部的 apt 步骤访问 `download.docker.com` 时连接被间歇重置：

```
E: Package 'docker-ce-cli' has no installation candidate   (exit 100)
# 上游表现为 Connection reset by peer
```

**该问题为网络间歇性故障，直接重新执行 `docker compose build` 重试即可成功**（已拉取的层会命中缓存，重试成本很低）。多次失败再考虑更换网络环境或检查镜像加速配置。

### 4.3 基础镜像注意事项（附带提示）

`python:3.11-slim` 基础镜像目前已切换至 Debian trixie，而项目 Dockerfile 中硬编码的是 bookworm 的 apt 源。**实测当前不构成致命问题**（构建可成功），但若未来构建时出现 apt 源 404 类错误，可关注 Dockerfile 中基础镜像与 apt 源版本的匹配。

---

## 5. 配置与启动

### 5.1 创建 .env（必做步骤）

**手动安装方式下，宿主机的 `.env` 不会被自动创建**，而 `docker-compose.yml` 中声明了 `env_file: .env`，缺失时 `docker compose up -d` 直接失败（`env file not found`）：

```bash
cp .env.example .env
chmod 600 .env
```

> **注意**：README 中"`.env` 由 entrypoint 自动生成"仅指**容器内**的 `.env`（挂载卷内的运行时配置）。宿主机项目根目录下的 `.env`（compose 的 env_file）只有 `scripts/install.sh` 安装方式会自动创建，手动安装必须自行复制。

### 5.2 修正数据目录路径（重要）

`.env.example` 中以下默认值为**容器内路径**，设计上由 entrypoint 在容器内自动设置。但这两个变量同时被 `docker-compose.yml` 用作**宿主机卷挂载源**：

```yaml
volumes:
  - ${DATA_DIR:-./data}:/data
  - ${PROJECT_ROOT:-./easyserver-data}:/easyserver_data
```

若保持默认值，数据目录会被挂载到 **WSL 根目录下的 `/data` 和 `/easyserver_data`**（而非项目目录内）。建议在 `.env` 中改为真实的宿主机路径：

```bash
# 编辑 .env，修改以下两项
PROJECT_ROOT=/home/<user>/easyserver_data
DATA_DIR=/home/<user>/easyserver_data/data
```

修改后启动，所有数据（含 modules 目录）都会落在你指定的宿主机路径内，便于备份与管理。

### 5.3 预设 JWT_SECRET（建议）

`.env` 中未预设 `JWT_SECRET` 时，容器每次重启都会生成新的随机密钥，导致**所有已登录用户的 Token 失效**（需重新登录）。建议首次配置时即预设固定值：

```bash
# 生成强随机密钥并追加到 .env
echo "JWT_SECRET=$(openssl rand -hex 32)" >> .env
```

### 5.4 启动

```bash
docker compose up -d
docker compose ps   # STATUS 应为 Up (healthy)
```

首次启动时 entrypoint 会自动完成初始化（实测确认）：在挂载卷内生成运行时 `.env`、创建/复用 `easyserver-proxy` Docker 网络、从镜像内置模板初始化 modules 目录（实测 14 个模块）、Uvicorn 监听 `0.0.0.0:8000`。健康检查（`GET /api/health`）通过后容器状态变为 `healthy`。

### 5.5 端口冲突排查（WSL mirrored 网络模式专项）

`docker-compose.yml` 的端口映射为 `${BIND_ADDRESS:-127.0.0.1}:8900:8000`，宿主侧端口 `8900` 为**硬编码值，无法通过环境变量修改**。

**实测现象**：WSL 使用 mirrored 网络模式时，Windows 宿主侧进程（如 IDE 的端口转发）占用 `127.0.0.1:8900` 会导致容器端口绑定失败；此时在 **WSL 内**用 `ss` / `lsof` **查不到任何占用**，极具迷惑性。

**排查方式**：在 **Windows 侧**（PowerShell/CMD）执行：

```powershell
netstat.exe -ano | findstr 8900
```

若有输出，记下最后一列 PID，用 `tasklist /fi "PID eq <PID>"` 定位进程。

**解决方式**：更换宿主端口。由于 `8900` 为硬编码，需二选一：

- 创建 `docker-compose.override.yml` 覆盖端口映射（推荐，不动原始文件）：

  ```yaml
  services:
    easyserver-core:
      ports: !override
        - "127.0.0.1:19000:8000"
  ```

- 或直接修改 `docker-compose.yml` 中的 `8900` 为其他端口。

修改后重新 `docker compose up -d`。

---

## 6. 验证

```bash
# 1. 容器状态
docker compose ps          # easyserver-core 应为 Up (healthy)

# 2. 健康检查接口
curl http://localhost:8900/api/health
# 预期返回：{"status":"ok","service":"easyserver-core"}

# 3. 面板访问
# 浏览器打开 http://localhost:8900，按向导完成初始化（设置管理员密码等）
```

三项全部通过即部署成功。此后可在面板「应用商店」按需安装服务模块。

---

## 7. 常见问题排查表

| 现象 | 原因 | 解决方式 |
|------|------|----------|
| `apt-get update` 报 `Could not handshake` | apt 走 IPv6 链路 TLS 握手失败 | apt 命令加 `-o Acquire::ForceIPv4=true` |
| `docker pull` 报 `i/o timeout` / `dial tcp` 错误 IP | Docker Hub DNS 污染 | 按 2.5 配置 `daemon.json` mirror 后重启 Docker |
| `systemctl` 报 `System has not been booted with systemd` | WSL 未启用 systemd | 用 `sudo service docker start`，或按 2.6 方式二启用 systemd |
| `docker compose up -d` 报 `env file not found` | 宿主机 `.env` 未创建 | `cp .env.example .env && chmod 600 .env`（见 5.1） |
| 数据出现在 WSL 根目录 `/data`、`/easyserver_data` | `.env` 中路径保持容器内默认值 | 按 5.2 改为宿主机真实路径 |
| 端口绑定失败但 WSL 内 `ss`/`lsof` 查无占用 | mirrored 模式下 Windows 侧占用端口 | Windows 侧 `netstat.exe -ano \| findstr 8900` 排查，换端口（见 5.5） |
| 重启容器后所有登录失效 | 未预设 `JWT_SECRET`，每次重启重新生成 | 按 5.3 在 `.env` 预设固定密钥 |
| `docker compose build` 中途 apt 报 `Connection reset by peer` / exit 100 | 构建内网络间歇故障 | **直接重试** `docker compose build`，已拉取层会命中缓存 |
| 当前用户无法直接执行 `docker` 命令 | 用户组未在当前会话刷新 | `sg docker -c "<命令>"` 或重新登录会话（见 2.7） |

---

## 8. 清理与重启

```bash
# 停止并移除容器与网络（保留镜像与数据卷）
docker compose down

# 重新启动
docker compose up -d

# 如需重建镜像（代码更新后）
docker compose build && docker compose up -d
```

**WSL 重启后**：若未启用 systemd，Docker 服务不会自动启动，需先执行：

```bash
sudo service docker start
```

再进入项目目录执行 `docker compose up -d`（容器配置了 `restart: unless-stopped`，在 Docker 服务恢复后通常也会随之自动启动，可用 `docker compose ps` 确认）。
