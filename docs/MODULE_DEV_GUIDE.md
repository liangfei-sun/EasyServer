# 模块开发指南

本文档说明如何为 EasyServer 添加新的服务模块。整个过程无需修改核心代码，只需按规范创建文件即可。

---

## 快速开始：4 步添加新模块

以添加 "Nextcloud" 为例：

### 第 1 步：创建模块目录

```bash
mkdir -p modules/nextcloud/{templates,scripts}
```

### 第 2 步：编写 module.yaml

创建 `modules/nextcloud/module.yaml`：

```yaml
id: nextcloud
name: "Nextcloud 私有云盘"
version: "1.0"
description: "开源私有云存储，支持文件同步、在线编辑、分享"
category: files                    # 对应 _registry.yaml 中的分类 ID
author: your_name

depends_on: []                     # 硬依赖（必须先安装的服务）
soft_depends_on:
  - nginx                          # 软依赖（有则自动增强配置）
  - acme

config:                            # Web 界面动态渲染的配置表单
  - key: NEXTCLOUD_PORT
    label: "服务端口"
    type: number
    default: 8888
    required: true
  - key: NEXTCLOUD_ADMIN_USER
    label: "管理员用户名"
    type: string
    default: admin
    required: true
  - key: NEXTCLOUD_ADMIN_PASSWORD
    label: "管理员密码"
    type: password
    default: ""
    required: true

access:
  subdomain: cloud                 # 子域名前缀（如 cloud.example.com）
  port: 8888                       # 容器内部端口
  protocol: http

healthcheck:
  url: "http://127.0.0.1:{NEXTCLOUD_PORT}/status.php"
  interval: 30s
  timeout: 10s
  retries: 3

resources:
  memory_limit: "1g"
  cpu_limit: "2.0"
```

### 第 3 步：编写 docker-compose.yml

创建 `modules/nextcloud/docker-compose.yml`：

```yaml
# EasyServer - Nextcloud 模块

services:
  nextcloud:
    image: nextcloud:latest
    container_name: easyserver-nextcloud
    ports:
      - "${BIND_ADDRESS:-127.0.0.1}:${NEXTCLOUD_PORT:-8888}:80"
    volumes:
      - ${DATA_DIR}/nextcloud/html:/var/www/html
      - ${DATA_DIR}/nextcloud/data:/var/www/html/data
    environment:
      - TZ=Asia/Shanghai
      - NEXTCLOUD_ADMIN_USER=${NEXTCLOUD_ADMIN_USER:-admin}
      - NEXTCLOUD_ADMIN_PASSWORD=${NEXTCLOUD_ADMIN_PASSWORD}
    networks:
      - nextcloud-net
      - easyserver-proxy
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

networks:
  nextcloud-net:
    name: easyserver-nextcloud-net
  easyserver-proxy:
    external: true
```

### 第 4 步：注册模块

在 `modules/_registry.yaml` 的对应分类下添加模块 ID：

```yaml
categories:
  - id: files
    name: "文件管理"
    modules:
      - filebrowser
      - nextcloud                  # 新增
```

完成！Web 界面会自动发现并展示新模块。

---

## module.yaml 字段完整说明

### 必填字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 模块唯一标识，与目录名一致 |
| `name` | string | 显示名称 |
| `version` | string | 模块版本号 |
| `description` | string | 一句话描述 |
| `category` | string | 分类 ID，对应 `_registry.yaml` 中的 `categories[].id` |

### 可选字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `author` | string | 作者名称 |
| `icon` | string | 图标文件名（放在模块目录下） |
| `depends_on` | list | 硬依赖的模块 ID 列表，安装前必须已安装 |
| `soft_depends_on` | list | 软依赖的模块 ID 列表，有则自动增强配置 |

### config 配置项

`config` 是一个列表，每项定义一个配置参数，Web 界面据此渲染表单：

```yaml
config:
  - key: PORT                      # 环境变量名（大写）
    label: "显示标签"               # 表单字段标签
    type: number                   # 字段类型：string/number/boolean/password/select
    default: 8080                  # 默认值
    required: true                 # 是否必填
    description: "说明文字"         # 帮助文本
```

**支持的 type 值**：

| type | 说明 | 额外字段 |
|---|---|---|
| `string` | 文本输入 | - |
| `number` | 数字输入 | - |
| `boolean` | 开关 | - |
| `password` | 密码输入（隐藏） | - |
| `select` | 下拉选择 | `options: [{value: "x", label: "显示"}]` |

### access 访问配置

```yaml
access:
  subdomain: media                 # 子域名前缀
  port: 8096                       # 容器内部端口
  protocol: http                   # http 或 https
  is_proxy: false                  # 是否为代理类型服务（如 nginx）
  proxy_extra:                     # Nginx 额外配置（键值对）
    proxy_buffering: "off"
    client_max_body_size: "0"
```

### healthcheck 健康检查

```yaml
healthcheck:
  url: "http://127.0.0.1:{PORT}/health"   # 支持 {变量} 引用 config 中的值
  interval: 30s
  timeout: 10s
  retries: 3
```

### resources 资源限制

```yaml
resources:
  memory_limit: "1g"               # 内存上限
  cpu_limit: "2.0"                 # CPU 核心数上限
```

---

## docker-compose.yml 编写规范

### 必须遵守的规范

1. **容器名**：统一前缀 `easyserver-`，如 `easyserver-nextcloud`
2. **数据路径**：使用 `${DATA_DIR}/<module>/` 变量
3. **端口绑定**：使用 `${BIND_ADDRESS:-127.0.0.1}` 变量，支持访问模式切换
4. **日志限制**：必须添加 `max-size: "10m"`, `max-file: "3"`
5. **时区**：统一 `TZ=Asia/Shanghai`
6. **安全选项**：添加 `no-new-privileges:true`
7. **网络**：非 host 模式需添加独立网络和共享反代网络

### 端口绑定与访问模式

```yaml
# 域名模式：绑定 127.0.0.1（仅本机，通过 Nginx 反代）
ports:
  - "${BIND_ADDRESS:-127.0.0.1}:${PORT:-8080}:8080"

# host 模式：不需要 ports 映射
network_mode: host
```

管理引擎根据 `ACCESS_MODE` 自动设置 `BIND_ADDRESS`：
- `domain` → `BIND_ADDRESS=127.0.0.1`
- `ipv6_direct` → `BIND_ADDRESS=0.0.0.0`
- `hybrid` → `BIND_ADDRESS=0.0.0.0`

### host 网络模式

部分服务需要 host 网络模式（如需要监听所有网卡、访问主机网络栈）：

```yaml
services:
  my-service:
    network_mode: host
    # 不需要 ports 映射
    # 不需要 networks 配置
```

### 多服务模块

某些模块包含多个服务（如 Joplin = app + db）：

```yaml
services:
  joplin-db:
    image: postgres:16
    container_name: easyserver-joplin-db
    networks:
      - joplin-internal              # 模块内部网络
    volumes:
      - ${DATA_DIR}/joplin/postgres:/var/lib/postgresql/data
    # ...

  joplin-app:
    image: joplin/server:latest
    container_name: easyserver-joplin-app
    depends_on:
      - joplin-db
    networks:
      - joplin-internal              # 模块内部网络
      - easyserver-proxy             # 共享反代网络
    # ...

networks:
  joplin-internal:
    name: easyserver-joplin-internal
  easyserver-proxy:
    external: true
```

---

## Nginx 配置模板（可选）

如果模块需要特殊的 Nginx 代理配置（非标准反代），可在 `templates/` 下创建 Jinja2 模板：

```
# modules/jellyfin/templates/nginx-site.conf.j2

server {
    listen {{ https_port }} ssl;
    server_name {{ subdomain }}.{{ domain }};

    ssl_certificate /etc/nginx/ssl/{{ domain }}/fullchain.cer;
    ssl_certificate_key /etc/nginx/ssl/{{ domain }}/{{ domain }}.key;
    include /etc/nginx/conf.d/ssl-params.conf;

    client_max_body_size 0;

    location / {
        proxy_pass http://127.0.0.1:{{ port }};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;         # Jellyfin 串流必须关闭缓冲
    }
}
```

管理引擎会自动使用模块的自定义模板，如果没有模板则使用默认模板。

---

## 测试清单

新模块开发完成后，逐项验证：

- [ ] `module.yaml` 格式正确，所有必填字段已填写
- [ ] `docker-compose.yml` 可通过 `docker compose -f modules/<id>/docker-compose.yml up -d` 独立启动
- [ ] 容器名为 `easyserver-<id>` 前缀
- [ ] 数据路径使用 `${DATA_DIR}/<id>/`
- [ ] 日志限制已配置
- [ ] 时区已设置
- [ ] 已在 `_registry.yaml` 中注册
- [ ] Web 界面能正确显示模块信息和配置表单
