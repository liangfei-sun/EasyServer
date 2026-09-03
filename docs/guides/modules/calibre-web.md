# Calibre-Web 电子书 · 运行指南

> 基于 2026-09-04 WSL Ubuntu 24.04 实测（QA 报告 R16）。实测结论与上游描述不一致处，以实测为准并已标注。
> **重要预警：实测确认面板安装路径当前不可用（镜像 tag 不可拉取 + 引擎无本地 fallback 双重叠加，缺陷 S/N）**，需按 3.2 降级路径手动启动；服务本身功能完整可用。

## 1. 概述

Calibre-Web 是在线电子书管理系统，支持在线阅读、书库管理、格式转换、OPDS 订阅与多用户权限。

| 项 | 值 |
|------|------|
| 镜像 | `linuxserver/calibre-web:0.6.24-r0-ls316`（module.yaml 声明；**实测该 tag 不可拉取，latest 可用**） |
| 分类 | media |
| 网络模式 | bridge（端口映射） |
| 端口 | 宿主 `CALIBRE_WEB_PORT`（默认 8083）→ 容器 8083 |
| 资源限制 | 内存 512m / CPU 1.0 |
| 容器名 | `easyserver-calibre-web` |
| 内置 healthcheck | 无（引擎靠模块健康检查 URL 探测） |

## 2. 前置条件

- 核心引擎运行中；无硬依赖模块（soft_depends_on: nginx、acme）
- **端口检查**：8083 需可用。实测环境 8083 被 Windows 侧进程占用（WSL2 mirrored），改用 `CALIBRE_WEB_PORT=18083`
- **书库数据**：需要 Calibre 数据库文件（`metadata.db`）或首次运行向导中指定书库路径

## 3. 安装

### 3.1 配置字段

| 字段 | 说明 | 默认值 | 必填 |
|------|------|--------|:---:|
| `CALIBRE_WEB_PORT` | 服务端口（宿主侧） | 8083 | 是 |
| `CALIBRE_WEB_PUID` | 用户 ID | 1000 | 是 |
| `CALIBRE_WEB_PGID` | 用户组 ID | 1000 | 是 |

### 3.2 安装路径与实测行为（面板安装当前不可用）

**面板/API 安装（实测失败）**：`POST /api/modules/install {"module_id":"calibre-web",...}` 实测终态 `failed(pull)`——即使本地已有目标 tag 镜像，引擎仍强制查 registry，module.yaml 声明的 tag `0.6.24-r0-ls316` 被镜像链路拒绝（`denied`，单次尝试约 90 秒 × 3 次 mirror 串行重试，约 4.5 分钟空转后失败）。两个缺陷叠加（S：tag 不可拉，latest 秒拉成功；N：引擎 pull 无本地 fallback）。

**实测可行的降级路径（手动 compose）**：

```bash
cd <项目根目录>/modules/calibre-web   # 或运行时目录 /easyserver_data/modules/calibre-web

# 方式 A：改用 latest tag（编辑 docker-compose.yml 的 image 行为 linuxserver/calibre-web:latest）
# 方式 B：本地已有 latest 时打 tag 后仍走原 compose（uninstall 会删该 tag 镜像，不推荐）
docker pull linuxserver/calibre-web:latest
# 编辑 compose image 行后：
sg docker -c "docker compose -f docker-compose.yml up -d" \
  # 环境变量按需注入：CALIBRE_WEB_PORT=18083 CALIBRE_WEB_PUID=1000 CALIBRE_WEB_PGID=1000
```

实测方式 A 成功：容器 Up，日志 `First time run, creating app.db...` + `[ls.io-init] done.` 初始化正常。

## 4. 启动与验证

```bash
# 容器状态
sudo docker ps --filter name=easyserver-calibre-web    # 实测：Up

# 引擎侧健康检查 URL（module.yaml）
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18083/
# 实测输出：302（重定向到 /login）

# 登录页可达
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18083/login
# 实测输出：200
```

**初始账号（实测登录成功，与上游一致）**：用户名 `admin`、密码 `admin123`。首次登录自动进入「Database Configuration」首次运行向导（实测 `/admin/dbconfig` 200），指定书库路径后即可使用。**登录后立即修改密码**。

## 5. 访问方式

- **直连**：`http://<服务器IP>:<CALIBRE_WEB_PORT>`（默认 8083）
- **nginx 反代子域名**：域名反代/混合路由模式下 `https://books.你的域名:8443`（`access.subdomain: books`）
- **Cloudflare Tunnel**：Tunnel 模式下发布后经 `https://books.你的域名` 免端口访问
- **OPDS 订阅**（阅读器接入）：地址 `https://books.你的域名:8443/opds`，账号为 Calibre-Web 内创建的用户

## 6. 数据与备份

| 路径 | 内容 |
|------|------|
| `<DATA_DIR>/calibre-web/config/` | 应用配置与数据库 `app.db`（账号、设置） |
| `<DATA_DIR>/calibre-web/books/` | 书库目录（电子书文件 + `metadata.db`） |

备份方法：打包上述两个目录；`metadata.db` 为活动写入的 SQLite，建议停容器后备份。批量导入可将电子书直接放入 books 目录后在界面扫描。

## 7. 卸载

- 面板卸载或 `POST /api/modules/uninstall`；实测返回 `removed_paths:["/app/data/calibre-web"]`（容器内前缀，缺陷 F 族），宿主 `<DATA_DIR>/calibre-web` **残留**（root 属主，需 sudo 清理）
- **实测警告（缺陷 D 第 5 例）**：卸载会**自动删除匹配的镜像 tag**（实测手动 tag 的 `0.6.24-r0-ls316` 被删，`latest` 幸存）——build/tag 变通安装时注意重拉成本

## 8. FAQ

**Q：面板安装一直失败（failed/pull）？**
实测已知问题：module.yaml 声明的 tag `0.6.24-r0-ls316` 当前不可拉取（latest 可用），且引擎 pull 无本地 fallback。按 3.2 降级路径手动启动，等待上游修复 tag。

**Q：登录后显示无书库？**
需先在首次运行向导中配置书库路径（`/books`），或上传 Calibre 数据库文件（`metadata.db`）。

**Q：忘记密码怎么办？**
删除 `<DATA_DIR>/calibre-web/config/app.db` 后重启容器，恢复默认 admin/admin123（先备份）。

**Q：容器反复重启或无法初始化？**
查看 `docker logs easyserver-calibre-web`；确认 `PUID/PGID` 与数据目录属主匹配（默认 1000:1000）。

## 9. 实测排错

实测环境：WSL2 mirrored（8083 被占，改 18083）。关键证据摘录：

```
# API install 终态（tag 不可拉 + 无本地 fallback）
failed | pull   （3 次 attempt 各 ~90s：denied → 退避 2/4s → 重试）
# tag 对照实验
$ docker pull linuxserver/calibre-web:latest        → Downloaded newer image ✅
$ docker pull linuxserver/calibre-web:0.6.24-r0-ls316 → error from registry: denied ❌（本地已 tag 亦然）
# 降级启动（latest）
$ curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18083/ → 302
POST /login (admin/admin123) → 302 → /admin/dbconfig 200
# 初始化日志
First time run, creating app.db... / [ls.io-init] done.
# uninstall
{"success":true,...,"removed_paths":["/app/data/calibre-web"]}
$ docker images → 0.6.24-r0-ls316 tag 已消失；/data/calibre-web 残留
```
