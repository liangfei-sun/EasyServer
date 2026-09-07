# DDNS-Go 动态域名 · 运行指南

> 基于 2026-09-04 WSL Ubuntu 24.04 实测（QA 报告 R12）。实测结论与上游描述不一致处，以实测为准并已标注。
> **重要预警：实测确认本模块存在单文件挂载陷阱（缺陷 H），默认安装后配置无法保存，DDNS 核心功能不可用**——详见 3.2，修复后可用。

## 1. 概述

DDNS-Go 自动检测服务器公网 IP 变化并更新 DNS 解析记录，支持阿里云、Cloudflare、DNSPod 等服务商，IPv4/IPv6 双栈。适用于家庭宽带等动态 IP 场景。

| 项 | 值 |
|------|------|
| 镜像 | `jeessy/ddns-go:v6.7.0` |
| 分类 | infra |
| 网络模式 | `host`（直接使用宿主网络） |
| 端口 | 9876（固定，web 配置界面） |
| 资源限制 | 内存 64m / CPU 0.25 |
| 容器名 | `easyserver-ddns-go` |
| 内置 healthcheck | 无 |

## 2. 前置条件

- 核心引擎运行中；无依赖模块
- **DNS 服务商凭据自备**（安装后在 Web 界面配置）：阿里云 AccessKey、Cloudflare API Token 等。实测 QA 过程仅验证到启动与配置界面层（凭据为空），DDNS 功能性验证需你自备凭据后进行
- 端口 9876 宿主侧可用（host 模式直接占用宿主端口）

## 3. 安装

### 3.1 配置字段

| 字段 | 说明 | 默认值 | 必填 |
|------|------|--------|:---:|
| `DDNS_GO_CHECK_INTERVAL` | IP 检测间隔（秒） | 600 | 是 |
| `DDNS_GO_CACHE_TIMES` | 缓存检测次数（每 N 次才对比一次 DNS 记录） | 12 | 是 |

### 3.2 安装路径与实测行为（单文件挂载陷阱）

**面板/API 安装**：应用商店 → DDNS-Go → 安装（或 `POST /api/modules/install {"module_id":"ddns-go","config":{...}}`）。实测安装 3.3 秒完成（镜像本地命中），容器持续运行**不 crash**，Web 界面正常可达。

**但实测确认配置保存必败（缺陷 H，P1）**：compose 将配置文件以**单文件方式挂载**：

```
${DATA_DIR}/ddns-go/config/.ddns_go_config.yaml : /root/.ddns_go_config.yaml
```

引擎不会预创建该宿主文件，Docker 检测到源不存在时会自动创建一个**同名目录**（而非文件）。容器日志实测报错：

```
Exception: read /root/.ddns_go_config.yaml: is a directory
```

应用捕获异常后继续存活并监听 9876，界面看起来一切正常，**但配置永远保存不了（写路径是目录）→ DDNS 功能不可用**，且 UI 上无从得知原因（容器无 healthcheck、引擎 install 恒 success，缺陷 I）。

**实测修复方式**（安装前预创建真文件；命令中 `<DATA_DIR>` 默认安装为容器内路径映射 `/data`，按安装指南第 3 步（3b）自定义 DATA_DIR 的用户请替换）：

```bash
sudo mkdir -p <DATA_DIR>/ddns-go/config
sudo touch <DATA_DIR>/ddns-go/config/.ddns_go_config.yaml    # 先建真文件再安装/重装
```

若已中招：卸载模块 → `sudo rm -rf <DATA_DIR>/ddns-go`（root 属主需 sudo）→ 按上式预创建文件 → 重新安装。

## 4. 启动与验证

```bash
# 容器状态
sudo docker ps --filter name=easyserver-ddns-go    # 实测：Up（持续运行）

# 引擎侧健康检查 URL（module.yaml，host 模式固定 9876）
curl -sL -o /dev/null -w '%{url_effective} %{http_code}' http://127.0.0.1:9876/
# 实测输出：http://127.0.0.1:9876/login 200（<title>DDNS-GO</title>）
```

**初始账号**：首次进入会要求设置 Web 界面登录密码（ddns-go 自身机制）；DNS 服务商密钥在配置界面内填写（自备凭据，本指南验证到界面层）。

## 5. 访问方式

- **直连**：`http://<服务器IP>:9876`（host 模式，配置界面）
- **nginx 反代子域名**：不适用（`is_proxy: false`、无 subdomain；管理界面建议仅本机/内网访问）
- **Cloudflare Tunnel**：不适用（管理界面走直连即可）

## 6. 数据与备份

| 路径 | 内容 |
|------|------|
| `<DATA_DIR>/ddns-go/config/.ddns_go_config.yaml` | 配置文件（DNS 凭据、域名列表；注意须为**文件**不能是目录） |

备份方法：打包该文件即可（**含 DNS 服务商密钥，注意保密**）。按 3.2 修复后配置才能正常落盘，落盘成功后建议立即备份一份。

## 7. 卸载

- 面板卸载或 `POST /api/modules/uninstall`；实测返回 `data_removed:true, removed_paths:["/app/data/ddns-go"]`
- **实测注意**：宿主 `<DATA_DIR>/ddns-go`（默认 `/data/ddns-go`）为 **root:root 属主残留**，普通用户无法自行删除，需 `sudo rm -rf`（缺陷 J）
- **实测警告（缺陷 D）**：卸载会**自动删除 `jeessy/ddns-go:v6.7.0` 镜像**，重装需重新拉取

## 8. FAQ

**Q：IP 变化了但 DNS 没有更新？**
先确认 3.2 的陷阱已修复（`<DATA_DIR>/ddns-go/config/.ddns_go_config.yaml` 必须是文件而非目录，日志无 `is a directory` 报错）；再检查 DNS 服务商 API 密钥是否正确、查看 DDNS-Go 日志。

**Q：配置页面无法访问？**
确认 9876 端口未被占用（host 模式），检查防火墙。WSL2 mirrored 环境注意 Windows 侧占用需用 netstat.exe 排查。

**Q：界面正常但配置保存不了/不生效？**
典型即单文件挂载陷阱：容器日志出现 `read /root/.ddns_go_config.yaml: is a directory`。按 3.2 修复后重装。

**Q：为什么安装秒完成？**
镜像本地已存在时（预拉取或重装）install 跳过拉取直接启动，实测 3.3s。

## 9. 实测排错

实测环境：WSL Ubuntu 24.04，凭据为空（仅验证启动+界面）。关键证据摘录：

```
# install（预拉取命中）
["安装任务已创建，正在准备...","正在拉取镜像...","镜像就绪，正在启动容器...","安装完成"]  (3.3s)
# 陷阱实锤（宿主侧）
$ ls -ld /data/ddns-go/config/.ddns_go_config.yaml
drwxr-xr-x 2 root root ... .ddns_go_config.yaml   ← 目录！
# 容器侧
$ docker exec easyserver-ddns-go ls -ld /root/.ddns_go_config.yaml
drwxr-xr-x 2 root root ...   ← 目录！
# 运行日志
2026/09/04 00:51:02 Exception: read /root/.ddns_go_config.yaml: is a directory
2026/09/04 00:51:02 Listen on :9876
# uninstall 与残留
{"success":true,...,"removed_paths":["/app/data/ddns-go"]}
$ ls -ld /data/ddns-go → drwxr-xr-x 3 root root（需 sudo 清理）
```
