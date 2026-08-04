# 集成 Frigate NVR 监控模块指南

> 本文档以 Frigate（开源 AI 视频监控系统）为例，演示如何为 EasyServer 集成一个新模块。
> 完成本流程后，你将掌握 EasyServer 模块开发的完整范式，可复用于任何 Docker 化服务。

---

## 一、整体思路

EasyServer 的模块系统遵循一个极简约定：**每个模块 = 一个目录 + 两个文件 + 一行注册**。

```
modules/frigate/
├── module.yaml          # 模块元数据：配置项、访问方式、健康检查、文档
└── docker-compose.yml   # Docker 服务定义
```

注册只需在 `modules/_registry.yaml` 的对应分类下添加模块 ID。

---

## 二、前置准备

### 2.1 手机端推流

在旧手机上安装 IP Webcam 类应用（推荐 Android 的 [IP Webcam](https://play.google.com/store/apps/details?id=com.pas.webcam)），获取 RTSP 流地址，例如：

```
rtsp://192.168.1.100:8554/video
```

### 2.2 确认服务器资源

Frigate 进行 AI 检测需要一定资源：
- **CPU 模式**（无 Coral TPU）：建议 4GB+ 内存、2 核+ CPU
- **Coral TPU 模式**：检测性能提升 10 倍以上，USB 版约 ¥200

---

## 三、创建模块目录和文件

### 3.1 创建目录

```bash
mkdir -p modules/frigate
```

### 3.2 编写 `docker-compose.yml`

创建 `modules/frigate/docker-compose.yml`：

```yaml
# EasyServer - Frigate NVR 监控模块

services:
  frigate:
    image: ghcr.io/blakeblackshear/frigate:stable
    container_name: easyserver-frigate
    ports:
      - "${BIND_ADDRESS:-127.0.0.1}:${FRIGATE_PORT:-5000}:5000"   # Web UI
      - "${BIND_ADDRESS:-127.0.0.1}:${FRIGATE_RTSP_PORT:-8554}:8554"  # RTSP 流
    volumes:
      - ${DATA_DIR}/frigate/config:/config
      - ${DATA_DIR}/frigate/storage:/media/frigate
      - /etc/localtime:/etc/localtime:ro
    environment:
      - TZ=Asia/Shanghai
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

**要点说明：**

| 字段 | 说明 |
|------|------|
| `container_name` | 遵循 `easyserver-{模块ID}` 命名规范 |
| `ports` | 使用 `${BIND_ADDRESS:-127.0.0.1}` 绑定地址 + `${XXX_PORT:-默认值}` 端口变量 |
| `volumes` | 使用 `${DATA_DIR}` 指向数据目录，保持与项目一致 |
| `restart` | 统一使用 `unless-stopped` |
| `logging` | 统一配置日志轮转，防止磁盘写满 |

### 3.3 编写 `module.yaml`

创建 `modules/frigate/module.yaml`：

```yaml
id: frigate
name: "Frigate NVR 监控"
version: "1.0"
description: "开源 AI 视频监控系统，支持人形/车辆检测，可接入旧手机摄像头"
category: infra
author: community

depends_on: []
soft_depends_on:
  - nginx
  - acme

config:
  - key: FRIGATE_PORT
    label: "Web UI 端口"
    type: number
    default: 5000
    required: true
  - key: FRIGATE_RTSP_PORT
    label: "RTSP 流端口"
    type: number
    default: 8554
    required: true

access:
  subdomain: frigate
  port: 5000
  protocol: http
  proxy_extra:
    proxy_buffering: "off"
    client_max_body_size: "0"

healthcheck:
  url: "http://127.0.0.1:{FRIGATE_PORT}/api/version"
  interval: 30s
  timeout: 10s
  retries: 3

resources:
  memory_limit: "2g"
  cpu_limit: "2.0"

docs:
  usage: |
    ## Frigate NVR 监控

    开源 AI 视频监控系统，支持人形/车辆/动物检测，可接入 IP 摄像头或旧手机摄像头。

    ### 首次使用
    1. 通过 `https://frigate.你的域名:8443` 访问 Web UI
    2. 在旧手机上安装 IP Webcam 应用，获取 RTSP 流地址
    3. 编辑配置文件 `data/frigate/config/config.yml`，添加摄像头
    4. 重启 Frigate 容器使配置生效

    ### 摄像头配置示例
    编辑 `data/frigate/config/config.yml`：

    ```yaml
    cameras:
      old_phone:
        ffmpeg:
          inputs:
            - path: rtsp://192.168.1.100:8554/video
              roles:
                - detect
                - record
        detect:
          width: 1280
          height: 720
        motion:
          threshold: 25
        objects:
          track:
            - person
            - car
    ```

    ### 常用功能
    - **实时查看**：Web UI 直接查看摄像头画面
    - **AI 检测**：自动识别人形、车辆等目标，减少误报
    - **录像回放**：支持时间线回放和事件截图
    - **MQTT 集成**：可对接 Home Assistant 实现智能联动

    ### 性能优化
    - 无 Coral TPU 时，CPU 模式可处理 2-3 路摄像头
    - 建议将检测分辨率设为 720p，平衡性能与精度
    - 开启 `motion` 检测可减少不必要的 AI 分析

  faq:
    - q: "手机摄像头画面卡顿或断连？"
      a: "确保手机和服务器在同一局域网，检查 RTSP 流地址是否正确，尝试降低分辨率"
    - q: "CPU 占用过高？"
      a: "降低检测分辨率至 720p，减少跟踪的物体类型，或考虑购买 Coral TPU"
    - q: "如何通过外网查看监控？"
      a: "Frigate 已配置 Nginx 反代，通过域名访问即可。建议设置强密码"
    - q: "如何添加多个手机摄像头？"
      a: "在 config.yml 的 cameras 下添加多个配置项，每个手机对应一个 camera"

  links:
    - label: "Frigate 官方文档"
      url: "https://docs.frigate.video/"
    - label: "Frigate GitHub"
      url: "https://github.com/blakeblackshear/frigate"
    - label: "IP Webcam (Android)"
      url: "https://play.google.com/store/apps/details?id=com.pas.webcam"
```

---

## 四、注册模块

编辑 `modules/_registry.yaml`，在 `infra`（基础设施）分类下添加 `frigate`：

```yaml
  - id: infra
    name: "基础设施"
    description: "反向代理、SSL证书、DNS、监控等基础服务"
    modules:
      - nginx
      - acme
      - ddns-go
      - uptime-kuma
      - backup
      - frigate          # <-- 新增这一行
```

---

## 五、验证模块

### 5.1 启动测试

```bash
# 进入项目根目录
cd /home/lf/easyserver

# 启动 Frigate 模块
docker compose -f modules/frigate/docker-compose.yml up -d

# 查看运行状态
docker compose -f modules/frigate/docker-compose.yml ps

# 查看日志
docker compose -f modules/frigate/docker-compose.yml logs -f
```

### 5.2 配置摄像头

编辑初始配置文件 `data/frigate/config/config.yml`（容器首次启动后会自动创建目录）：

```yaml
mqtt:
  enabled: false

cameras:
  test_camera:
    ffmpeg:
      inputs:
        - path: rtsp://你的手机IP:8554/video
          roles:
            - detect
    detect:
      width: 1280
      height: 720
```

重启容器使配置生效：

```bash
docker compose -f modules/frigate/docker-compose.yml restart
```

### 5.3 访问 Web UI

浏览器打开 `http://服务器IP:5000`，确认：
- [ ] Web UI 正常加载
- [ ] 能看到摄像头画面
- [ ] AI 检测框正常显示

---

## 六、模块开发规范总结

### 6.1 必须遵循的约定

| 约定 | 说明 | 示例 |
|------|------|------|
| 容器命名 | `easyserver-{模块ID}` | `easyserver-frigate` |
| 端口变量 | `${MODULE_PORT:-默认值}` | `${FRIGATE_PORT:-5000}` |
| 绑定地址 | `${BIND_ADDRESS:-127.0.0.1}:端口` | 不直接暴露到公网 |
| 数据目录 | `${DATA_DIR}/{模块ID}/` | `${DATA_DIR}/frigate/config` |
| 时区 | `TZ=Asia/Shanghai` | 统一环境变量 |
| 重启策略 | `restart: unless-stopped` | 统一重启策略 |
| 日志轮转 | `json-file` + `max-size` | 防止磁盘写满 |

### 6.2 `module.yaml` 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 模块唯一标识，与目录名一致 |
| `name` | 是 | 显示名称 |
| `version` | 是 | 模块版本 |
| `description` | 是 | 一句话描述 |
| `category` | 是 | 所属分类（infra/media/notes/files/network） |
| `depends_on` | 是 | 硬依赖（缺失则无法启动） |
| `soft_depends_on` | 否 | 软依赖（可选的反代等） |
| `config` | 否 | 用户可配置项（端口、模式等） |
| `access` | 否 | Web 访问配置（子域名、端口、反代参数） |
| `healthcheck` | 否 | 健康检查配置 |
| `resources` | 否 | 资源限制 |
| `docs` | 否 | 使用文档、FAQ、外部链接 |

### 6.3 `config` 配置项类型

| type | 说明 | 示例 |
|------|------|------|
| `number` | 数字输入 | 端口号 |
| `string` | 文本输入 | 路径、密码 |
| `select` | 下拉选择 | 网络模式 |
| `boolean` | 开关 | 是否启用某功能 |

---

## 七、后续可选增强

完成基础集成后，可考虑：

1. **Nginx 反代配置**（已自动生效）：通过 Web 面板安装模块时，API 会自动读取 `module.yaml` 中的 `access` 字段，生成 `frigate.域名` 的反代配置并 reload Nginx。无需手动操作。若需手动触发重新生成，可通过 API 调用：
   ```bash
   # 手动触发 Nginx 配置重新生成
   curl -X POST http://127.0.0.1:8900/api/nginx/generate
   ```
   生成的配置文件位于 `modules/nginx/conf.d/sites.conf`，包含所有已安装模块的反代规则。
2. **MQTT 集成**：添加 MQTT 容器，支持 Home Assistant 联动
3. **Coral TPU 支持**：在 `docker-compose.yml` 中添加设备映射
4. **前端页面**：在 `core/web/src/views/` 中添加 Frigate 管理视图
5. **模板配置**：在 `modules/frigate/templates/` 下提供 `config.yml.j2` 模板，实现首次启动自动生成配置

---

## 八、完整文件清单

完成本指南后，应新增/修改以下文件：

```
新增:
  modules/frigate/docker-compose.yml    # Docker 服务定义
  modules/frigate/module.yaml           # 模块元数据

修改:
  modules/_registry.yaml                # 注册新模块
```

运行时自动生成的：

```
  data/frigate/config/                  # Frigate 配置目录
  data/frigate/storage/                 # 录像存储目录
```
