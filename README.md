# EasyServer

> 当前版本：v0.1.0

个人服务器一站式部署方案 —— 模块化、可视化管理、一键安装。

## 特性

- **模块化架构**：每个服务独立 Docker Compose 文件，独立启停，互不影响
- **Web 管理面板**：基于 Vue 3 + Element Plus 的可视化界面，服务状态一目了然
- **安装向导**：首次使用完成域名、密码等基础配置，不自动安装任何服务；配置网络访问时自动安装对应网络模块，其余服务从应用商店按需安装
- **智能混合路由**：支持域名反代 (SSL)、IPv6 直连与 Cloudflare Tunnel 中转，可按服务粒度自由选择路由方式，智能推荐一键配置、无缝切换，详见 [网络配置指南](docs/network-config.md)
- **应用商店**：按需安装服务（后台任务执行，实时进度与失败诊断），支持依赖自动检查，密码类字段可一键随机生成
- **易于扩展**：新增服务只需 4 个文件，详见 [模块开发指南](docs/MODULE_DEV_GUIDE.md)

## 快速开始

### 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/liangfei-sun/EasyServer/main/scripts/install.sh | bash
```

安装脚本会自动：
1. 检测并安装 Docker
2. 克隆项目
3. 初始化配置
4. 启动核心引擎

### 手动安装

```bash
git clone git@github.com:liangfei-sun/EasyServer.git
cd easyserver
cp .env.example .env
# 编辑 .env 配置你的域名和参数
nano .env

# 创建网络并启动
docker network create easyserver-proxy
docker compose up -d
```

### 访问管理面板

安装完成后访问 `http://your-server-ip:8900`，首次访问会进入设置向导。

## 可用模块

| 模块 | 分类 | 端口 | 说明 |
|---|---|---|---|
| nginx | 基础设施 | 80/443 | 反向代理 + SSL |
| notediscovery | 笔记 | 8000 | 笔记发现服务 |
| calibre-web | 文件 | 8083 | 电子书管理 |
| filebrowser | 文件 | 8081 | 网页文件浏览器 |
| jellyfin | 媒体 | 8096 | 媒体服务器 |
| joplin | 笔记 | 22300 | Joplin 笔记同步 |
| uptime-kuma | 基础设施 | 3001 | 服务监控 |
| ddns-go | 网络 | - | 动态域名解析 |
| acme | 网络 | - | SSL 证书自动续签 |
| cloudflare-tunnel | 网络 | - | Cloudflare 隧道 |
| nextcloud | 文件 | 8888 | Nextcloud 私有云盘 |
| backup | 基础设施 | - | 数据备份（restic） |
| frigate | 媒体 | 8971 | AI 视频监控（NVR） |

## 项目结构

```
easyserver/
├── docker-compose.yml          # 核心引擎（管理面板）
├── .env.example                # 环境变量模板
├── scripts/
│   ├── install.sh              # 一键安装脚本
│   └── manage.sh               # CLI 管理工具
├── core/
│   ├── api/                    # FastAPI 后端
│   ├── web/                    # Vue 3 前端
│   ├── Dockerfile
│   └── requirements.txt
├── modules/                    # 服务模块
│   ├── _registry.yaml          # 模块注册表
│   ├── nginx/
│   ├── notediscovery/
│   └── ...
├── data/                       # 数据目录
└── docs/
    ├── ARCHITECTURE.md         # 架构设计
    ├── MODULE_DEV_GUIDE.md     # 模块开发指南
    └── network-config.md       # 网络配置指南（含混合路由教程）
```

## CLI 管理

```bash
./scripts/manage.sh start       # 启动所有服务
./scripts/manage.sh stop        # 停止所有服务
./scripts/manage.sh status      # 查看状态
./scripts/manage.sh logs        # 查看日志
./scripts/manage.sh backup      # 备份数据
./scripts/manage.sh svc nginx restart  # 操作单个服务
```

## 访问模式

### 域名反代模式 (推荐)
所有服务通过 Nginx 反向代理访问，自动配置 SSL 证书。
- `https://notes.example.com` → Joplin
- `https://media.example.com` → Jellyfin

### IPv6 直连模式
服务端口直接暴露在公网，适合无域名的场景。
- `http://[240e:xxx:xxx]:8081` → FileBrowser

### 智能混合路由模式 (推荐)
域名反代与 Tunnel 中转并存，按服务粒度自由选择路由方式：
- **域名反代**：DNS AAAA → 服务器 IPv6 → Nginx SSL，适合 IPv6 出口稳定的服务
- **Tunnel 中转**：DNS CNAME → Cloudflare 边缘 → Tunnel，免端口、不依赖公网出口

支持逐服务切换路由方式、智能推荐一键配置、DNS 记录自动同步与冲突保护。
详见 [网络配置指南](docs/network-config.md)。

## 新增模块

1. 在 `modules/` 下创建目录
2. 编写 `module.yaml` 描述元数据
3. 编写 `docker-compose.yml` 定义服务
4. 在 `_registry.yaml` 中注册

详见 [模块开发指南](docs/MODULE_DEV_GUIDE.md)

## 技术栈

- **后端**: Python 3.11 + FastAPI + Docker SDK
- **前端**: Vue 3 + Vite + Element Plus
- **部署**: Docker Compose
- **反代**: Nginx + Let's Encrypt

## License

MIT
