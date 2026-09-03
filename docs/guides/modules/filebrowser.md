# FileBrowser 文件管理 · 运行指南

> 基于 2026-09-04 WSL Ubuntu 24.04 实测（QA 报告 R11）。实测结论与上游描述不一致处，以实测为准并已标注。

## 1. 概述

FileBrowser 是轻量级 Web 文件管理器，支持上传、下载、在线预览、分享链接与多用户管理，管理指定目录内的文件。

| 项 | 值 |
|------|------|
| 镜像 | `filebrowser/filebrowser:v2.31.2` |
| 分类 | files |
| 网络模式 | bridge（端口映射） |
| 端口 | 宿主 `FILEBROWSER_PORT`（默认 8081）→ 容器 80 |
| 资源限制 | 内存 256m / CPU 1.0 |
| 容器名 | `easyserver-filebrowser` |
| 内置 healthcheck | 有（compose 定义，实测生效，本套 13 模块中少数自带） |

## 2. 前置条件

- 核心引擎运行中；无硬依赖模块（soft_depends_on: nginx、acme，仅影响子域名反代访问）
- **端口检查**：8081 需可用。实测环境 8081 被 Windows 侧进程占用（WSL2 mirrored），安装时改用 `FILEBROWSER_PORT=18081`
- **数据目录属主（重要）**：实测发现首次安装必 crash 的根因是挂载卷目录属主问题（见 3.2），建议安装前预置目录属主

## 3. 安装

### 3.1 配置字段

| 字段 | 说明 | 默认值 | 必填 |
|------|------|--------|:---:|
| `FILEBROWSER_PORT` | 服务端口（宿主侧） | 8081 | 是 |
| `FILEBROWSER_DATA_PATH` | 管理的文件目录 | `./data/filebrowser/files` | 是 |

### 3.2 安装路径与实测行为

**面板/API 安装**：应用商店 → FileBrowser → 安装（或 `POST /api/modules/install {"module_id":"filebrowser","config":{"FILEBROWSER_PORT":18081,"FILEBROWSER_DATA_PATH":"/data/filebrowser/files"}}`）。

**实测警告：首次安装容器必 crash loop**。根因：引擎以 root 创建数据卷目录（`/data/filebrowser-db` 为 root:root 755），而 compose 强制容器以 `user: 1000:1000` 运行 → 容器内无写权限 → `open /db/filebrowser.db: permission denied` 反复重启（缺陷 E）。**install 仍报 success**（引擎无健康门控）。

**实测修复步骤**（安装后立即执行）：

```bash
# 修正数据卷属主（<DATA_DIR> 默认安装为容器内路径映射 /data，按安装指南 4.2 自定义 DATA_DIR 的用户请替换）
sudo chown -R 1000:1000 <DATA_DIR>/filebrowser-db <DATA_DIR>/filebrowser
# 重启容器
sudo docker restart easyserver-filebrowser
```

重启后容器进入 healthy 状态，全功能可用。另一种思路是安装前预创建目录并 chown，效果相同。

## 4. 启动与验证

```bash
# 容器状态（compose 自带 healthcheck，修复后应显示 healthy）
sudo docker ps --filter name=easyserver-filebrowser
# 实测输出：easyserver-filebrowser  Up 6 seconds (healthy)

# 引擎侧健康检查 URL（module.yaml）
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18081/
# 实测输出：200

# 官方健康端点
curl -s http://127.0.0.1:18081/health
# 实测输出：{"status":"OK"}
```

**初始账号（实测与上游一致）**：用户名 `admin`、密码 `admin`。**首次登录后立即修改密码**。

## 5. 访问方式

- **直连**：`http://<服务器IP>:<FILEBROWSER_PORT>`（默认 8081；换端口按实际值）
- **nginx 反代子域名**：域名反代/混合路由模式下 `https://files.你的域名:8443`（`access.subdomain: files`）
- **Cloudflare Tunnel**：Tunnel 模式下在「服务发布」中发布后经 `https://files.你的域名` 免端口访问

## 6. 数据与备份

| 路径 | 内容 |
|------|------|
| `<DATA_DIR>/filebrowser/files/`（即 `FILEBROWSER_DATA_PATH`） | 被管理的文件目录（核心数据，必备份） |
| `<DATA_DIR>/filebrowser-db/` | 数据库 `filebrowser.db`（账号、设置、分享链接） |

备份方法：直接打包上述两个目录即可（数据库建议先 `docker stop` 或使用 SQLite 在线备份工具保证一致性）。

## 7. 卸载

- 面板卸载或 `POST /api/modules/uninstall`；`remove_data: true` 时实测返回 `data_removed:true, removed_paths:["/app/data/filebrowser-db","/app/data/filebrowser"]`
- **实测注意**：`removed_paths` 显示的是**容器内路径前缀**（`/app/data/...`），宿主真实路径为 `<DATA_DIR>/...`（缺陷 F）；且实测卸载后宿主两目录**仍残留**（属主已是 1000，可直接删除）（缺陷 G）
- **实测警告（缺陷 D）**：卸载会**自动删除 `filebrowser/filebrowser:v2.31.2` 镜像**，重装需重新拉取

## 8. FAQ

**Q：上传大文件失败？**
检查 nginx 的 `client_max_body_size` 配置，确保大于文件大小（走子域名反代时）。

**Q：如何修改管理的文件目录？**
在模块配置中修改「管理的文件目录」（`FILEBROWSER_DATA_PATH`），重启服务生效。

**Q：忘记密码怎么办？**
删除数据库后重启恢复默认账户：删除 `<DATA_DIR>/filebrowser-db/` 下内容后 `docker restart easyserver-filebrowser`（会重置为 admin/admin，注意备份后再操作）。

**Q：安装后容器反复重启（crash loop）？**
实测最常见根因即 3.2 的数据卷属主问题，`docker logs easyserver-filebrowser` 见 `permission denied` 即确认，按 3.2 chown 修复。

## 9. 实测排错

实测环境：WSL2 mirrored（8081 被占，改 18081）。关键证据摘录：

```
# 修复前：crash loop 日志
easyserver-filebrowser | open /db/filebrowser.db: permission denied
easyserver-filebrowser | Warning: filebrowser.db can't be found. Initialing in /db/   ×5 循环
# 属主证据
$ ls -ld /data/filebrowser-db → drwxr-xr-x root root
# 修复
$ sudo chown -R 1000:1000 /data/filebrowser-db /data/filebrowser && docker restart easyserver-filebrowser
# 修复后
$ docker ps --filter name=filebrowser → Up 6 seconds (healthy)
$ curl -s http://127.0.0.1:18081/health → {"status":"OK"}
# uninstall
{"success":true,...,"removed_paths":["/app/data/filebrowser-db","/app/data/filebrowser"]}
$ ls /data/ → filebrowser filebrowser-db（残留）
```
