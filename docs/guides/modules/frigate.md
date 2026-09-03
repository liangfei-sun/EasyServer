# Frigate NVR 监控 · 运行指南

> 基于 2026-09-04 WSL Ubuntu 24.04 实测（QA 报告 R21，无摄像头降级场景）。实测结论与上游描述不一致处，以实测为准并已标注。
> **实测正面样本：面板/API 安装路径完全可用**——镜像来自 ghcr.io（直连，不经 Docker Hub mirror 白名单），API install 一次成功；config 端口键真实渲染，换端口顺畅。
> **第二预警：compose 未设 `shm_size`（缺陷 X）**——实测日志命中 SHM 64MB 过小警告，多摄像头场景会进程崩溃/录像异常，建议手动补配。

## 1. 概述

Frigate 是开源 AI 视频监控系统：接入 IP 摄像头或旧手机（IP Webcam），支持人形/车辆检测、时间线录像回放与 Home Assistant 联动。**无摄像头/无检测硬件时 UI 与 API 完全可用**（实测容错设计好），可先安装后接摄像头。

| 项 | 值 |
|------|------|
| 镜像 | `ghcr.io/blakeblackshear/frigate:stable`（约 7.48GB；**实测 ghcr 直连拉取健康**） |
| 分类 | infra |
| 网络模式 | bridge（端口映射） |
| 端口 | 宿主 `FRIGATE_PORT`（默认 5000）→ 容器 5000；宿主 `FRIGATE_RTSP_PORT`（默认 8554）→ 容器 8554 |
| 资源限制 | 内存 2g / CPU 2.0 |
| 容器名 | `easyserver-frigate` |
| 内置 healthcheck | 无（引擎靠模块健康检查 URL `/api/version` 探测） |

> 端口加注：上游 README 模块表写的 `8971` 与 module.yaml 实际默认 `5000` 不符，以实测为准（本表及全文端口信息均基于 module.yaml 与实测）。

## 2. 前置条件

- 核心引擎运行中；无硬依赖模块（soft_depends_on: nginx、acme）
- **无摄像头也可安装**：实测无摄像头/无检测硬件时 API/UI 全部可用（降级验证通过），可先装后配
- **接入摄像头时**：准备 RTSP 流地址（如旧手机安装 IP Webcam 应用），编辑 `<DATA_DIR>/frigate/config/config.yml` 添加摄像头后重启容器生效（module.yaml usage，配置示例见该文件）
- **端口检查**：5000/8554 需可用。实测环境 5000 被 Windows 侧占用（WSL2 mirrored），改用 `FRIGATE_PORT=15000 / FRIGATE_RTSP_PORT=18554`——config 端口键真实渲染，换端口顺畅（实测确认）
- **SHM 建议（缺陷 X）**：Frigate 官方推荐 shm ≥128MB（多摄像头更高），compose 模板未设（Docker 默认 64MB）。多摄像头用户建议编辑 compose 为服务加 `shm_size: "128mb"`（QA 建议的修复方向）

## 3. 安装

### 3.1 配置字段

| 字段 | 说明 | 默认值 | 必填 |
|------|------|--------|:---:|
| `FRIGATE_PORT` | Web UI 端口 | 5000 | 是 |
| `FRIGATE_RTSP_PORT` | RTSP 流端口 | 8554 | 是 |

> 实测确认两个端口键均真实渲染进 compose（与 jellyfin 的假配置形成对照），换端口无需改文件。

### 3.2 安装路径（面板安装实测可用，正面样本）

**面板/API 安装（实测成功）**：`POST /api/modules/install` 实测 **success**——ghcr 镜像在本地命中后 pull 直连秒过（ghcr.io 不经 Docker Hub mirror 白名单，不受 denied 问题影响）。面板安装 frigate 为 13 模块中少数全流程可用路径。

```bash
# 面板安装，或等价 API 调用（示例端口 8901 为 QA 实测环境经 docker-compose.override.yml 修改后的端口，默认安装请使用 8900）：
curl -s -X POST -H "Authorization: Bearer <你的管理Token>" -H 'Content-Type: application/json' \
  -d '{"module_id":"frigate","config":{"FRIGATE_PORT":15000,"FRIGATE_RTSP_PORT":18554}}' \
  http://localhost:8901/api/modules/install
# 实测输出：success（ghcr 镜像本地命中，pull 直连秒过）
```

**手动路径（等价可用）**：

```bash
cd <PROJECT_ROOT>/modules/frigate   # <PROJECT_ROOT> 默认安装为容器内路径映射 /easyserver_data，按安装指南 4.2 自定义 PROJECT_ROOT 的用户请替换
docker pull ghcr.io/blakeblackshear/frigate:stable
sg docker -c "FRIGATE_PORT=15000 FRIGATE_RTSP_PORT=18554 DATA_DIR=<数据目录> \
  docker compose -f docker-compose.yml up -d"
```

## 4. 启动与验证

```bash
# 容器状态
sudo docker ps --filter name=easyserver-frigate
# 实测输出：Up (health: starting)

# 引擎侧健康检查 URL（module.yaml）
curl http://127.0.0.1:15000/api/version
# 实测输出：0.17.2-3d4dd3a   (HTTP 200)

# Web UI 降级验证（无摄像头）
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:15000/
# 实测输出：200（<title>Frigate</title>，无摄像头配置下 UI 正常渲染）

# 启动日志
sudo docker logs easyserver-frigate
# 实测输出：peewee_migrate 建表（DB 迁移正常）→ FastAPI 启动 → go2rtc healthcheck 启动
# ⚠️ 同时命中 SHM 警告（缺陷 X）：
# WARNING : The current SHM size of 64.0MB is too small, recommend increasing it to at least 114MB.
```

**初始账号**：无预置账号。Frigate 默认无认证（上游设计），通过 nginx 反代/Tunnel 暴露公网时建议配合访问层鉴权（module.yaml faq 亦建议设置强密码）。

## 5. 访问方式

- **直连**：`http://<服务器IP>:<FRIGATE_PORT>`（默认 5000）；RTSP 流经 `<FRIGATE_RTSP_PORT>`（默认 8554）
- **nginx 反代子域名**：域名反代/混合路由模式下 `https://frigate.你的域名:8443`（`access.subdomain: frigate`，已内置 `proxy_buffering off` 与不限上传体积）
- **Cloudflare Tunnel**：Tunnel 模式下发布后经 `https://frigate.你的域名` 免端口访问

## 6. 数据与备份

| 路径 | 内容 |
|------|------|
| `<DATA_DIR>/frigate/config/` | 摄像头配置（`config.yml`）与运行配置 |
| `<DATA_DIR>/frigate/storage/` | 录像与事件截图（容器内挂载为 `/media/frigate`，体积随摄像头数量/码率增长） |

备份方法：`config/config.yml` 必备（摄像头配置入口）；`storage/` 按需（体积大，通常可接受重建）。挂载均为目录（无单文件陷阱，实测确认）。若部署了 backup 模块，自动纳入 `data/` 备份范围。

## 7. 卸载

- 面板卸载或 `POST /api/modules/uninstall`（`remove_data: true`）；实测返回 `{"success":true,...,"data_removed":true,"removed_paths":["/app/data/frigate"]}`，宿主 `<DATA_DIR>/frigate` **残留**（需 sudo 清理）
- **实测警告（缺陷 D 第 11 例）**：卸载会**自动删除 ghcr 镜像（7.48GB）**——**13 个模块中重拉成本最高的一个**（ghcr 虽直连但体积大），重装前请评估网络条件；必要时 `docker tag` 另存副本

## 8. FAQ

**Q：日志报 SHM size 64.0MB is too small？**
实测命中（缺陷 X）：compose 未设 `shm_size`（Docker 默认 64MB），Frigate 官方推荐 ≥128MB（实测警告建议至少 114MB）。单摄像头/试用可暂时忽略；多摄像头场景会进程崩溃/录像异常，建议编辑 compose 为服务加 `shm_size: "128mb"` 后重建（QA 建议的修复方向，改动后表现未实测）。

**Q：无摄像头能装吗？**
能。实测无摄像头/无检测硬件时 UI 与 API 完全可用（Frigate 容错设计好），UI 正常渲染、`/api/version` 正常响应；之后随时编辑 `config.yml` 接入摄像头。

**Q：手机摄像头画面卡顿或断连？**
确保手机和服务器在同一局域网，检查 RTSP 流地址是否正确，尝试降低分辨率（module.yaml faq）。

**Q：CPU 占用过高？**
降低检测分辨率至 720p，减少跟踪的物体类型，或考虑购买 Coral TPU（module.yaml faq）。

**Q：如何通过外网查看监控？**
Frigate 已配置 Nginx 反代，通过域名访问即可；建议设置强密码（module.yaml faq）。监控画面经公网传输，务必走 HTTPS（反代/Tunnel 自带）并收紧访问层权限。

## 9. 实测排错

实测环境：WSL2 mirrored（5000 被占，改 15000/18554）、无摄像头降级场景。关键证据摘录（QA 报告 R21）：

```
# API install（正面样本：ghcr 直连）
success — ghcr 镜像本地命中，pull 直连秒过（ghcr 不经 docker hub mirror 白名单）
# 镜像与 digest
ghcr.io/blakeblackshear/frigate:stable（7.48GB）
digest sha256:d4351369984d4a9e2a49ac59736f6490856a7ea11f7790040746d21496967010
# 健康检查
$ curl http://127.0.0.1:15000/api/version → 0.17.2-3d4dd3a   (200)
$ curl -o /dev/null -w '%{http_code}' http://127.0.0.1:15000/ → 200   <title>Frigate</title>
# 启动日志（SHM 警告为唯一异常）
$ docker logs easyserver-frigate
WARNING : The current SHM size of 64.0MB is too small, recommend increasing it to at least 114MB.
INFO    : Starting FastAPI app
# uninstall
{"success":true,...,"data_removed":true,"removed_paths":["/app/data/frigate"]}
（ghcr 镜像被自动删——缺陷 D 第 11 例；/data/frigate 残留）
```
