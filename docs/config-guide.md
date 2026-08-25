# EasyServer 配置指南

> 本文档面向人类用户和 AI 工具，说明如何通过直接编辑文件来配置 EasyServer。

## 配置文件概览

EasyServer 使用 **双源分层配置**：

| 文件 | 职责 | 格式 |
|------|------|------|
| `data/config.yaml` | 核心运行配置：网络模式、域名、DNS 凭证、模块列表、安装状态 | YAML |
| `.env` | 环境变量：路径、子域名前缀、服务密码、模块专用配置 | ENV |

**同步机制**：`GET /config` 请求会触发 `_sync_credentials_from_env()`，从 `.env` 读取凭证同步到 `config.yaml`。修改 DNS 凭证时**必须同时更新两个文件**。

---

## data/config.yaml 字段说明

### 核心字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `setup_completed` | bool | `false` | 初始化向导是否完成 |
| `network_configured` | bool | `false` | 网络是否已配置 |
| `admin_password_hash` | string | `""` | 管理员密码的 SHA-256 哈希 |
| `access_mode` | string | `"domain"` | 访问模式：`domain` / `cloudflare_tunnel` / `ipv6_direct` / `hybrid` |
| `ssl_email` | string | `""` | Let's Encrypt 证书邮箱 |

### 网络配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `domain` | string | `""` | 主域名（反代模式使用） |
| `https_port` | int | `8443` | HTTPS 对外端口（运营商常封锁 443） |
| `panel_subdomain` | string | `"panel"` | 管理面板子域名前缀 |
| `dns_provider` | string | `""` | 主 DNS 提供商：`aliyun` / `cloudflare` |
| `domains[]` | list | `[]` | 多域名配置数组，每项含 `domain`、`dns_provider`、`purpose`（`nginx`/`tunnel`）、`status`、可选 `zone_id` |

**dns_credentials 结构**：

```yaml
dns_credentials:
  aliyun:
    key: "<ALI_KEY>"        # 阿里云 AccessKey ID
    secret: "<ALI_SECRET>"  # 阿里云 AccessKey Secret
  cloudflare:
    token: "<CF_DNS_TOKEN>" # Cloudflare DNS Zone 级 API Token
```

**cloudflare_tunnel 结构**：

```yaml
cloudflare_tunnel:
  account_id: "<CF_ACCOUNT_ID>"
  tunnel_id: "<TUNNEL_ID>"
  tunnel_name: "easyserver-tunnel"
  api_token: "<CF_TUNNEL_TOKEN>"   # Tunnel 级 API Token
  zone_id: "<ZONE_ID>"
  routes:                          # Tunnel 路由规则
    - hostname: svc.example.com
      service: http://localhost:PORT
```

### 模块管理

| 字段 | 类型 | 说明 |
|------|------|------|
| `installed_modules[]` | list | 已安装模块 ID 列表，如 `[filebrowser, jellyfin, ...]` |

> **注意**：直接编辑此列表仅作声明，**不会**触发容器创建/销毁。模块安装/卸载需通过 API 或 Web 界面。

---

## .env 环境变量说明

基于 `.env.example`，完整变量列表：

### 基础配置

| 变量 | 示例值 | 说明 |
|------|--------|------|
| `PROJECT_ROOT` | `/home/lf/easyserver` | 项目根目录（绝对路径） |
| `DATA_DIR` | `/home/lf/easyserver/data` | 数据持久化目录 |
| `DOMAIN` | `example.com` | 主域名 |
| `ACCESS_MODE` | `domain` | 访问模式（同 config.yaml） |
| `HTTPS_PORT` | `8443` | HTTPS 端口 |
| `SSL_EMAIL` | `admin@example.com` | Let's Encrypt 邮箱 |

### 子域名前缀

| 变量 | 默认值 | 对应服务 |
|------|--------|----------|
| `SUBDOMAIN_PANEL` | `panel` | 管理面板 |
| `SUBDOMAIN_NOTES` | `notes` | NoteDiscovery |
| `SUBDOMAIN_BOOKS` | `books` | Calibre-Web |
| `SUBDOMAIN_FILES` | `files` | FileBrowser |
| `SUBDOMAIN_MEDIA` | `media` | Jellyfin |
| `SUBDOMAIN_JOPLIN` | `joplin` | Joplin |
| `SUBDOMAIN_STATUS` | `status` | Uptime Kuma |

### DNS 凭证

| 变量 | 说明 |
|------|------|
| `ALI_KEY` | 阿里云 AccessKey ID |
| `ALI_SECRET` | 阿里云 AccessKey Secret |
| `CF_TUNNEL_TOKEN` | Cloudflare Tunnel Token |

### 服务密码

| 变量 | 说明 |
|------|------|
| `JOPLIN_DB_PASSWORD` | Joplin PostgreSQL 密码 |
| `NOTEDISCOVERY_PASSWORD` | NoteDiscovery 登录密码 |
| `NOTEDISCOVERY_SECRET_KEY` | NoteDiscovery 会话密钥 |
| `NEXTCLOUD_PORT` | Nextcloud 端口（安装时自动写入） |
| `NEXTCLOUD_ADMIN_USER` | Nextcloud 管理员用户名 |
| `NEXTCLOUD_ADMIN_PASSWORD` | Nextcloud 管理员密码 |
| `NEXTCLOUD_TRUSTED_DOMAINS` | Nextcloud 可信域名 |

---

## 配置修改指南

### 安全修改（可直接编辑文件）

| 操作 | 修改文件 | 说明 |
|------|----------|------|
| 修改主域名 | `config.yaml` → `domain` + `.env` → `DOMAIN` | 两处保持一致 |
| 修改 HTTPS 端口 | `config.yaml` → `https_port` + `.env` → `HTTPS_PORT` | 需重启 Nginx 容器 |
| 修改 DNS 凭证 | **同时**更新 `.env` 和 `config.yaml` | 否则 GET /config 会回退 |
| 修改子域名前缀 | `.env` → `SUBDOMAIN_*` | 需重载 Nginx 配置 |
| 声明已安装模块 | `config.yaml` → `installed_modules` | 仅声明，不触发容器操作 |

### 需通过 API / 界面的操作

| 操作 | 原因 |
|------|------|
| 网络模式切换 | 需触发 Nginx 重载、容器启停、DNS 记录更新 |
| 模块安装 / 卸载 | 需执行 `docker compose up/down`，写入配置 |
| DNS 记录同步 | 需调用 DNS Provider API 创建/更新记录 |
| 管理员密码修改 | 需生成 hash 并写入 config.yaml |

### 修改后的关联操作

| 修改内容 | 生效操作 |
|----------|----------|
| `https_port` | `docker restart easyserver-nginx` |
| `SUBDOMAIN_*` | 重载 Nginx 配置或重启 Nginx 容器 |
| `dns_credentials` | 调用 API `POST /api/dns/sync` 同步 DNS 记录 |
| `cloudflare_tunnel.routes` | 调用 API 更新 Tunnel 路由 |
| `installed_modules`（手动编辑） | 无自动关联操作，需手动管理容器 |

---

## AI 工具配置建议

1. **读取配置**：直接读取 `data/config.yaml` 和 `.env`，获取完整运行状态
2. **简单修改**（域名、端口、凭证）：编辑文件后提醒用户执行关联操作
3. **复杂操作**（网络切换、模块管理）：通过 API 调用完成，而非直接编辑文件
   - `POST /api/network/configure` — 网络模式切换
   - `POST /api/modules/{id}/install` — 安装模块
   - `POST /api/modules/{id}/uninstall` — 卸载模块
   - `POST /api/dns/sync` — DNS 记录同步
4. **凭证修改**：务必同时更新 `.env` 和 `config.yaml`，避免运行时同步覆盖
5. **容器内修改**：`data/config.yaml` 属主为 root，需通过 `docker exec easyserver-core python3 -c "..."` 修改
