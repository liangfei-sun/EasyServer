# NoteDiscovery 笔记 · 运行指南

> 基于 2026-09-04 WSL Ubuntu 24.04 实测（QA 报告 R19）。实测结论与上游描述不一致处，以实测为准并已标注。
> **重要预警：实测确认本模块存在单文件挂载陷阱第 2 例（缺陷 U，P1）：首装 `up` 必败，且 `touch` 空配置文件后应用仍崩溃——当前版本按上游默认流程无法直接使用**，本文如实记录已验证的边界。

## 1. 概述

NoteDiscovery 是基于 Markdown 的在线笔记管理工具，支持实时预览编辑、全文搜索、附件管理与密码认证。

| 项 | 值 |
|------|------|
| 镜像 | `ghcr.io/gamosoft/notediscovery:latest`（ghcr 直连链路，不受 Docker Hub mirror 白名单影响） |
| 分类 | notes |
| 网络模式 | bridge（端口映射） |
| 端口 | 宿主 `NOTEDISCOVERY_PORT`（默认 8000）→ 容器 8000 |
| 资源限制 | 内存 256m / CPU 1.0 |
| 容器名 | `easyserver-notediscovery` |
| 内置 healthcheck | 无 |

## 2. 前置条件

- 核心引擎运行中；无硬依赖模块（soft_depends_on: nginx、acme）
- **端口检查**：8000 需可用。实测环境 8000 被 Windows 侧进程占用（WSL2 mirrored），改用 `NOTEDISCOVERY_PORT=18000`
- **认证凭据**：`NOTEDISCOVERY_PASSWORD`（登录密码）与 `NOTEDISCOVERY_SECRET_KEY`（会话密钥）按 module.yaml 声明"留空自动生成"，**实测 API/compose 层均无自动生成逻辑**（与 backup 缺陷 O 同族）；且 compose 内置了上游遗留的默认密码值——**安装时务必显式传入这两项**

## 3. 安装

### 3.1 配置字段

| 字段 | 说明 | 默认值 | 必填 |
|------|------|--------|:---:|
| `NOTEDISCOVERY_PORT` | 服务端口（宿主侧） | 8000 | 是 |
| `NOTEDISCOVERY_AUTH_ENABLED` | 启用登录认证 | true | 否 |
| `NOTEDISCOVERY_PASSWORD` | 登录密码（声明留空自动生成，实测无生成逻辑） | 空 | 否 |
| `NOTEDISCOVERY_SECRET_KEY` | 会话密钥（同上） | 空 | 否 |

### 3.2 安装路径与实测行为（首装必败）

**面板/API 安装（实测失败）**：首次安装终态 `failed(up)`，错误信息可诊断性好：

```
error mounting "/data/notediscovery/config.yaml" ... not a directory:
Are you trying to mount a directory onto a file (or vice-versa)?
```

根因（缺陷 U）：compose 将 `${DATA_DIR}/notediscovery/config.yaml` 以**单文件方式挂载**到容器 `/app/config.yaml`，引擎不预创建该文件 → Docker 自动创建**同名目录** → 挂载冲突，`up` 直接失败（比 ddns-go 陷阱更彻底——容器都起不来）。

**实测变通与边界**（命令中 `<DATA_DIR>` 默认安装为容器内路径映射 `/data`，按安装指南 4.2 自定义 DATA_DIR 的用户请替换）：

```bash
# 变通：预创建空配置文件后重装（install 可 success）
sudo mkdir -p <DATA_DIR>/notediscovery
sudo touch <DATA_DIR>/notediscovery/config.yaml
```

实测 touch 空文件后 install 成功、容器 `Up (health: starting)`，**但应用随即崩溃**——空 config.yaml 解析为 None，Python 启动即抛 `TypeError: 'NoneType' object is not subscriptable`（`config['app']['version']`）。

**实测结论**：`touch 空文件`不够，容器内 `/app/config.yaml` 需要**上游应用要求的合法配置结构**。正确做法是从容器镜像内提取默认配置模板：

```bash
# 从镜像中取出合法默认配置（容器可临时启动一次 export，或用 docker create + docker cp）
sg docker -c "docker create --name nd-tmp ghcr.io/gamosoft/notediscovery:latest"
sg docker -c "docker cp nd-tmp:/app/config.yaml /tmp/config.yaml"
sg docker -c "docker rm nd-tmp"
sudo cp /tmp/config.yaml <DATA_DIR>/notediscovery/config.yaml   # 覆盖空文件后再安装/启动
```

> 以上提取命令为按缺陷修复方向整理的操作路径，其中"install 前预创建文件可行"为实测结论；从镜像提取默认配置的命令未在 QA 中执行，如失败请以容器内实际路径为准排查。

## 4. 启动与验证

修复配置后：

```bash
sudo docker ps --filter name=easyserver-notediscovery    # 预期 Up

# 引擎侧健康检查 URL（module.yaml）
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18000/
# 实测（空配置崩溃态）输出：000（无响应）；配置合法后预期 200
```

**初始账号**：启用认证时使用安装时设置的 `NOTEDISCOVERY_PASSWORD` 登录（无默认账号）。QA 实测因需合法 config 模板未完成功能层验证（不死等原则），登录后功能以应用实际表现为准。

## 5. 访问方式

- **直连**：`http://<服务器IP>:<NOTEDISCOVERY_PORT>`（默认 8000）
- **nginx 反代子域名**：域名反代/混合路由模式下 `https://notes.你的域名:8443`（`access.subdomain: notes`）
- **Cloudflare Tunnel**：Tunnel 模式下发布后经 `https://notes.你的域名` 免端口访问

## 6. 数据与备份

| 路径 | 内容 |
|------|------|
| `<DATA_DIR>/notediscovery/data/` | 笔记文件（纯 Markdown，可直接备份） |
| `<DATA_DIR>/notediscovery/config.yaml` | 应用配置（**必须是文件**，含认证配置） |

备份方法：打包 data 目录与 config.yaml 即可。

## 7. 卸载

- 面板卸载或 `POST /api/modules/uninstall`；实测返回 `removed_paths:["/app/data/notediscovery"]`（容器内前缀，缺陷 F 族），宿主 `<DATA_DIR>/notediscovery`（含 data/ 子目录）**残留**
- **实测警告（缺陷 D 第 9 例）**：卸载会**自动删除 ghcr 镜像**（272MB，ghcr 同样被波及），重装需重新拉取

## 8. FAQ

**Q：面板安装报 `not a directory` 挂载错误？**
单文件挂载陷阱：预创建 `<DATA_DIR>/notediscovery/config.yaml` 真文件后重装（见 3.2）。

**Q：预创建空文件后安装成功但服务无响应？**
空配置导致应用启动即崩（实测 `TypeError: 'NoneType' object is not subscriptable`）。需放入合法默认配置（镜像内自带 config.yaml，按 3.2 提取），`docker logs easyserver-notediscovery` 确认无 Python 崩溃栈。

**Q：忘记密码怎么办？**
上游口径：在模块配置中重新设置密码，重启服务生效。

**Q：笔记数据在哪？如何备份？**
`<DATA_DIR>/notediscovery/data/`，均为 Markdown 文件，随时打包备份。

## 9. 实测排错

实测环境：WSL2 mirrored（8000 被占，改 18000）。关键证据摘录：

```
# 首次 install 失败（up 阶段）
Error response from daemon: failed to create task for container: ...
error mounting "/data/notediscovery/config.yaml" to rootfs at "/app/config.yaml":
mount src=/data/notediscovery/config.yaml ... not a directory: Are you trying to
mount a directory onto a file (or vice-versa)?
# touch 变通后 install success，应用崩溃
$ docker logs easyserver-notediscovery
  File "/app/backend/main.py", line 94, in <module>
    config['app']['version'] = version
TypeError: 'NoneType' object is not subscriptable
# uninstall
{"success":true,...,"removed_paths":["/app/data/notediscovery"]}
```

> 正面记录：ghcr.io 拉取链路健康（272MB 手动拉取成功，直连不经 Docker Hub mirror 白名单）；install 对 required 字段缺失返回 400 语义正确（传错键名 `NOTE_DISCOVERY_PORT` 时报 `"字段「服务端口」为必填项"`）。
