# Jellyfin 媒体服务器 · 运行指南

> 基于 2026-09-04 WSL Ubuntu 24.04 实测（QA 报告 R22）。实测结论与上游描述不一致处，以实测为准并已标注。
> **重要预警：本模块是实测问题最多的模块，WSL2 环境下默认配置（host 网络模式）不可用**——SIGSEGV 崩溃循环（缺陷 W1）；bridge 模式可稳定运行但 compose 无端口映射、`JELLYFIN_PORT` 为假配置（缺陷 W2）。**面板安装路径当前也不可用（tag denied + 无本地 fallback，缺陷 S/N）**。请在 WSL2 下直接按 3.2 降级路径以 bridge 模式手动启动。

## 1. 概述

Jellyfin 是开源媒体服务器，管理并串流视频、音乐、图片，支持 Web/移动端/TV 多客户端播放、自动刮削与硬件转码。本模块支持 host/bridge 双网络模式（config 可选），但实测两模式各有缺陷（见上预警）。

| 项 | 值 |
|------|------|
| 镜像 | `jellyfin/jellyfin:10.9.13`（module.yaml 声明；**实测该 tag 不可拉取，latest 可用**） |
| 分类 | media |
| 网络模式 | 默认 `host`（module.yaml 标注"推荐，支持 DLNA 发现"）；可选 bridge（**实测 WSL2 下推荐 bridge**） |
| 端口 | 容器固定 8096；host 模式直接监听宿主 8096；**bridge 模式 compose 无 ports 段（无映射）** |
| 资源限制 | 内存 2g / CPU 2.0 |
| 容器名 | `easyserver-jellyfin` |
| 内置 healthcheck | 无（引擎靠模块健康检查 URL 探测） |

## 2. 前置条件

- 核心引擎运行中；无硬依赖模块（soft_depends_on: nginx、acme）
- **WSL2 环境专项预警（实测）**：host 模式（默认）下 jellyfin 10.9.13 必然 SIGSEGV(139) 崩溃循环——`.NET` 在 WSL2 mirrored 网络下的 host 网络枚举兼容性问题（缺陷 W1）。**WSL2 用户务必选择 bridge 模式**；bridge 模式实测稳定运行（`Startup complete 0:00:17`）
- **端口说明**：host 模式固定监听 8096（实测环境中 8096 被 Windows 侧占用，但 bind 未被阻断——崩溃与端口无关）；bridge 模式无映射，8096 占用与否不影响
- **`JELLYFIN_PORT` 为假配置（缺陷 W2）**：该 config 键不渲染进 compose（host 固定 8096；bridge 无映射），仅用于 healthcheck URL 字符串替换——改它不会改变实际监听端口，反而使 healthcheck 探测一个不存在的端口。**不要依赖此字段换端口**

## 3. 安装

### 3.1 配置字段

| 字段 | 说明 | 默认值 | 必填 |
|------|------|--------|:---:|
| `JELLYFIN_PORT` | 服务端口 | 8096 | 是（**假配置：实际不生效**，缺陷 W2） |
| `JELLYFIN_NETWORK_MODE` | 网络模式（host / bridge） | host | 是（**WSL2 实测建议 bridge**） |

### 3.2 安装路径与实测行为（面板安装当前不可用）

**面板/API 安装（实测失败）**：实测 API install 走至终态 **`failed(pull)`**（hint"镜像不存在或无拉取权限"）——即使本地已有目标 tag 镜像，引擎仍强制查 registry（缺陷 N 第 4 例）；tag `10.9.13` 被 mirror 链路拒绝（缺陷 S）。

**实测可行的降级路径（手动 compose，WSL2 以 bridge 模式启动）**：

```bash
cd <项目根目录>/modules/jellyfin   # 或运行时目录 /easyserver_data/modules/jellyfin

# 1. 拉取可用镜像（latest 约 2.27GB）并打 tag（可选）
docker pull jellyfin/jellyfin:latest
docker tag jellyfin/jellyfin:latest jellyfin/jellyfin:10.9.13
# 注意：uninstall 会自动删 10.9.13 tag 镜像（缺陷 D），直接用 latest 更省事

# 2. 启动（WSL2：bridge 模式）
sg docker -c "JELLYFIN_NETWORK_MODE=bridge DATA_DIR=<数据目录> \
  docker compose -f docker-compose.yml up -d"

# 3. bridge 模式无端口映射，宿主机无法直连——临时以容器 IP 验证（见第 4 节）；
#    需要宿主端口映射的话，编辑 docker-compose.yml 在 services.jellyfin 下补：
#    ports:
#      - "127.0.0.1:8096:8096"
#    （此改动为 QA 建议的修复方向，映射后的表现未实测）
```

实测 bridge 路径成功：容器稳定 Up，`Startup complete 0:00:17`（host 模式对照实验见第 9 节）。

## 4. 启动与验证

```bash
# 容器状态
sudo docker ps --filter name=easyserver-jellyfin
# 实测（bridge）：Up 25 seconds (health: starting)，无重启循环
# 实测（host，不可用）：Restarting (139) Less than a second ago——SIGSEGV 崩溃循环

# 服务日志（bridge 实测）
sudo docker logs easyserver-jellyfin
# 实测输出：[INF] Main: Startup complete 0:00:17.7189226

# 健康检查 URL（module.yaml：/health）——bridge 下以容器 IP 直连（实测可行）
JELLYFIN_IP=$(sg docker -c "docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' easyserver-jellyfin")
curl -s -o /dev/null -w '%{http_code}' http://${JELLYFIN_IP}:8096/health
# 实测输出：200（容器 IP 172.17.0.2 时验证通过）
```

**初始账号**：无预置账号——首次访问 Web 界面进入**初始设置向导**（语言 → 管理员账户创建 → 媒体库配置），账户由你在向导中创建（module.yaml usage）。

## 5. 访问方式

- **直连（host 模式，非 WSL2 环境）**：`http://<服务器IP>:8096`（host 固定 8096，`JELLYFIN_PORT` 不生效）
- **bridge 模式（WSL2 实测路径）**：compose 无 ports 段，**宿主机 `127.0.0.1:8096` 不可达**（缺陷 W2）。可用方式：① 容器 IP 直连 `http://<容器IP>:8096`（实测 200，但容器 IP 重启后可能变化）；② 按 3.2 补 ports 映射后用 `http://<服务器IP>:8096`（未实测）
- **nginx 反代子域名**：域名反代/混合路由模式下 `https://media.你的域名:8443`（`access.subdomain: media`，已内置 `proxy_buffering off` 与不限上传体积）——bridge + nginx 反代是 WSL2 下较完整的组合
- **Cloudflare Tunnel**：Tunnel 模式下发布后经 `https://media.你的域名` 免端口访问

## 6. 数据与备份

| 路径 | 内容 |
|------|------|
| `<DATA_DIR>/jellyfin/config/` | 服务端配置与元数据（账户、媒体库索引） |
| `<DATA_DIR>/jellyfin/cache/` | 缓存（可清理，备份可排除） |
| `<DATA_DIR>/jellyfin/media/` | 媒体文件挂载点（建议媒体放此处或另行挂载） |

备份方法：备份 `config/`（必要）与 `media/`（体积大，按需）；`cache/` 可排除。若部署了 backup 模块，其排除规则已自动跳过 `jellyfin/cache` 与 `jellyfin/transcodes`。

## 7. 卸载

- 面板卸载或 `POST /api/modules/uninstall`；实测均 200 success，宿主 `<DATA_DIR>/jellyfin` **残留**（需 sudo 清理）
- **实测警告（缺陷 D 第 12 例）**：卸载会**自动删除 `jellyfin/jellyfin:10.9.13` tag 镜像**（实测手动 tag 的镜像被删，`latest` 幸存）——重装需重新处理镜像，注意成本

## 8. FAQ

**Q：容器反复重启（Restarting (139)）？**
WSL2 mirrored 环境 host 模式的 SIGSEGV 崩溃循环（缺陷 W1，实测复现：.NET 堆栈 `Jellyfin.Server.Program.StartApp`）。修复：改用 bridge 模式启动（`JELLYFIN_NETWORK_MODE=bridge`），实测稳定。

**Q：bridge 模式下宿主机访问不了 8096？**
实测确认：compose 模板无 ports 段（host 模式专用模板），bridge 下无端口映射（缺陷 W2）。用容器 IP 直连验证服务，或在 compose 补 `ports: ["127.0.0.1:8096:8096"]`（QA 建议的修复方向，未实测），或经 nginx 反代访问。

**Q：修改 JELLYFIN_PORT 端口没变？**
实测确认 `JELLYFIN_PORT` 为假配置（缺陷 W2）：不渲染进 compose，host 模式固定 8096、bridge 无映射，该键仅影响 healthcheck URL 的字符串替换——改端口后 healthcheck 反而探测不存在的端口。当前无法通过配置换端口。

**Q：视频播放卡顿？**
检查网络带宽，尝试降低视频质量或开启硬件转码（module.yaml faq）。WSL2 环境硬件直通能力受限，转码性能请以实测为准。

**Q：如何添加外部字幕？**
将字幕文件与视频放在同一目录，命名相同即可自动识别（module.yaml faq）。

**Q：客户端连接不上服务器？**
确认服务器地址和端口正确，检查防火墙是否开放端口（module.yaml faq）。WSL2 下注意 bridge 无映射问题（见上）。

## 9. 实测排错

实测环境：WSL2 mirrored（8096 被 Windows 侧占用）、docker-ce 29.7.2。host/bridge 对照实验关键证据摘录（QA 报告 R22）：

```
# host 模式（默认配置）崩溃循环
$ docker ps -a → easyserver-jellyfin Restarting (139) Less than a second ago
$ docker logs（tail）
  at Jellyfin.Server.ServerSetupApp.SetupServer.RunAsync()
  at Jellyfin.Server.Program.StartApp(StartupOptions options)
# 崩溃间隙探测（某次存活窗口，bind 未被 Windows 占用阻断）
$ curl 8096/health → 200
# bridge 对照实验
$ JELLYFIN_NETWORK_MODE=bridge compose up -d
easyserver-jellyfin Up 25 seconds (health: starting)
[INF] Main: Startup complete 0:00:17.7189226
# bridge 下服务健康（容器 IP 直连）
$ curl http://172.17.0.2:8096/health → 200
# 镜像层证据
$ docker pull jellyfin/jellyfin:10.9.13 → denied（latest 2.27GB 可用）
API install 终态 → failed(pull)（本地已 tag 仍强拉 registry，缺陷 N 第 4 例）
# uninstall
均 200 success；10.9.13 tag 镜像已删（latest 幸存）；/data/jellyfin 残留
```
