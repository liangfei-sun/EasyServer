# EasyServer 架构设计文档

## 项目定位

EasyServer 是一个面向非技术用户的个人服务器一站式部署方案。用户只需一台 Ubuntu 机器，通过 Web 界面即可完成所有服务的安装、配置、管理。

### 核心特性

- **模块化架构**：每个服务独立模块，按需安装，互不影响
- **Web 管理界面**：所有操作通过浏览器完成，零命令行门槛
- **四种访问模式**：域名反代（阿里云/Cloudflare）、Cloudflare Tunnel、IPv6 直连
- **安全认证**：JWT Token 登录保护，7 天有效期
- **可扩展设计**：新增服务只需添加模块目录，无需修改核心代码

---

## 目录结构

```
easyserver/
├── core/                          # 核心管理引擎
│   ├── api/                       # 后端 API（Python FastAPI）
│   │   ├── main.py                # 入口
│   │   ├── routes/                # API 路由
│   │   └── core/                  # 核心逻辑
│   ├── web/                       # 前端（Vue 3）
│   │   └── dist/                  # 构建产物
│   ├── requirements.txt
│   └── Dockerfile
│
├── modules/                       # 服务模块目录
│   ├── _registry.yaml             # 模块注册表（分类索引）
│   └── <module>/                  # 每个模块独立目录
│       ├── module.yaml            # 模块元数据（自描述）
│       ├── docker-compose.yml     # 容器编排
│       ├── templates/             # 配置模板（Jinja2）
│       └── scripts/               # 模块级脚本
│
├── data/                          # 持久化数据（gitignore）
│   └── <module>/                  # 各模块的数据目录
│
├── scripts/                       # 全局脚本
│   ├── install.sh                 # 系统级安装脚本
│   ├── manage.sh                  # CLI 管理命令
│   └── backup.sh                  # 备份脚本
│
├── docs/                          # 项目文档
├── .env                           # 全局配置（gitignore）
├── .env.example                   # 配置模板
├── docker-compose.yml             # 核心引擎编排
└── README.md
```

---

## 模块系统

### 设计原理

每个服务模块是一个自包含的目录，通过 `module.yaml` 描述自身的所有信息：

- **元数据**：名称、版本、描述、分类
- **依赖关系**：硬依赖（必须安装）和软依赖（可选增强）
- **配置项**：Web 界面据此动态渲染配置表单
- **访问配置**：子域名、端口、代理参数
- **健康检查**：URL、间隔、超时
- **资源限制**：内存、CPU

### 模块加载流程

1. `module_loader` 扫描 `modules/` 目录
2. 解析每个子目录中的 `module.yaml`
3. 读取 `_registry.yaml` 获取分类信息
4. 合并为完整的模块列表供 API 和 Web 使用

### 模块安装流程

1. 用户在 Web 界面选择要安装的模块
2. 填写配置表单（由 module.yaml 中的 config 字段渲染）
3. 管理引擎将配置写入 `.env`
4. 如果模块有 Jinja2 模板，渲染生成配置文件
5. 执行 `docker compose -f modules/<id>/docker-compose.yml up -d`
6. 更新 Nginx 反代配置（如果 nginx 模块已安装）

> **安装策略**：初始安装 EasyServer 时不安装任何服务模块，所有模块一律平等、默认不安装。用户在网络配置引导中选择访问方式时，系统自动安装对应网络模块（域名反代 → nginx/acme/ddns-go；隧道 → cloudflare-tunnel），其余服务由用户在应用商店按需安装。

### 模块卸载流程

1. 用户确认卸载（可选择保留或删除数据）
2. 执行 `docker compose down --rmi all`：停止容器并删除镜像
3. 若选择删除数据：解析 docker-compose.yml 中挂载的宿主机路径，删除 `${DATA_DIR}/<id>/` 目录（nginx 等模块的 ssl/log 数据目录一并处理，`conf.d` 等配置目录保留）
4. 从 `installed_modules` 列表移除
5. 更新 Nginx 反代配置

---

## 网络设计

### 独立网络 + 共享反代网络

每个使用桥接网络的服务拥有两个网络：

```yaml
networks:
  - <module>-net          # 独立网络（模块私有）
  - easyserver-proxy      # 共享反代网络（供 Nginx 访问）
```

- **独立网络**：每个服务的私有网络，停止/重启不影响其他服务
- **共享反代网络**：`easyserver-proxy`，由管理引擎创建，Nginx 通过此网络连接后端服务

### host 网络模式的服务

部分服务（jellyfin, ddns-go, acme, cloudflare-tunnel）使用 `network_mode: host`，直接使用主机网络栈。这些服务通过 `127.0.0.1` 与 Nginx 通信。

---

## 访问模式

### 域名模式（domain）

```
外网用户 → 子域名:端口 → Nginx（SSL终止）→ 127.0.0.1:端口 → 服务容器
```

- 支持阿里云和 Cloudflare 两种 DNS 提供商
- 所有服务端口绑定 `127.0.0.1`（仅本机访问）
- Nginx 根据子域名路由到对应后端
- SSL 证书由 acme.sh 自动申请和续签

### Cloudflare Tunnel 模式（cloudflare_tunnel）

```
外网用户 → Cloudflare Edge → Tunnel → 本地服务
```

- 无需公网 IP，无需开放端口
- Cloudflare Tunnel 自带 SSL、反代和 DNS
- 无需安装 Nginx、ACME、DDNS 等模块

### IPv6 直连模式（ipv6_direct）

```
外网用户 → [IPv6地址]:端口 → 服务容器（直接访问）
```

- 服务端口绑定 `::` 或 `0.0.0.0`（所有接口）
- 不启动 Nginx（或 Nginx 仅做基础功能）
- 用户通过 IPv6 地址 + 端口直接访问各服务

### 混合模式（hybrid）

两种模式并存：Nginx 反代 + 服务端口同时开放。

### 模式切换

管理引擎根据 `.env` 中的 `ACCESS_MODE` 变量：
1. 重新生成 Nginx 配置（域名模式/混合模式）
2. 调整各模块的端口绑定（127.0.0.1 或 0.0.0.0）
3. 重载 Nginx

---

## 管理引擎

### 后端（FastAPI）

- 封装 Docker Compose 命令，实现 per-module 独立操作
- 扫描 modules/ 目录自动发现可用模块
- 读写 data/config.yaml 管理全局配置
- 使用 Jinja2 渲染 Nginx 配置模板

### 前端（Vue 3）

- 安装向导：极简 2 步（域名+密码），初始设置不安装任何模块，网络配置时按所选访问方式自动安装对应网络模块
- 登录页：JWT Token 认证
- 网络配置：智能推荐 + 统一管理（Tunnel / 域名反代 / IPv6 直连 / 自由配置，含 DNS 自动同步）
- 仪表盘：服务状态、网络检测、快捷操作
- 服务管理：独立卡片式操作，危险操作二次确认
- 应用商店：搜索筛选、一键安装（后台任务执行，可实时查看安装进度与失败原因）
- 备份中心：本地+云端备份、快照管理
- 全局设置：容器资源管理、基础信息（网络相关配置已迁移至「网络配置」页面）

### 容器化

管理引擎自身也容器化运行，通过挂载 Docker socket 操作其他容器：

```yaml
# docker-compose.yml（根目录）
services:
  easyserver-core:
    build: ./core
    container_name: easyserver-core
    ports:
      - "127.0.0.1:9800:9800"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./:/app
      - ./data:/data
    restart: unless-stopped
```

---

## 安全设计

- JWT Token 认证，7 天有效期，过期自动跳转登录
- `.env` 文件加入 `.gitignore`，防止密钥泄露
- DNS 凭证 API 层脱敏返回，前端不显示完整密钥
- 所有容器添加 `no-new-privileges` 安全选项
- 日志统一限制 10m/3files，防止磁盘撑满
- 域名模式下服务端口仅绑定 127.0.0.1
- SSL 证书目录不纳入版本控制
- 危险操作（停止/重启/更新）需二次确认
