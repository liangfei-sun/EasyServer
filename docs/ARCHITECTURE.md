# EasyServer 架构设计文档

## 项目定位

EasyServer 是一个面向非技术用户的个人服务器一站式部署方案。用户只需一台 Ubuntu 机器，通过 Web 界面即可完成所有服务的安装、配置、管理。

### 核心特性

- **模块化架构**：每个服务独立模块，按需安装，互不影响
- **Web 管理界面**：所有操作通过浏览器完成，零命令行门槛
- **四种访问模式**：域名反代（阿里云/Cloudflare）、Cloudflare Tunnel、IPv6 直连、智能混合路由（推荐）
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
│   │   │   ├── config.py          # 配置管理路由
│   │   │   ├── network.py         # 网络配置路由（从 config.py 拆分）
│   │   │   ├── domains.py         # 多域名管理路由
│   │   │   ├── modules.py         # 模块管理路由
│   │   │   ├── services.py        # 服务操作路由
│   │   │   ├── cloudflare.py      # Cloudflare Tunnel 路由
│   │   │   ├── dns.py             # DNS 管理路由
│   │   │   ├── nginx.py           # Nginx 配置路由
│   │   │   ├── backup.py          # 备份路由
│   │   │   └── docs.py            # 文档路由
│   │   └── core/                  # 核心逻辑
│   │       ├── config_manager.py  # 配置管理器（YAML + .env 读写）
│   │       ├── docker_manager.py  # Docker 容器管理
│   │       ├── module_loader.py   # 模块加载器
│   │       ├── auth.py            # 认证（JWT + bcrypt）
│   │       ├── deps.py            # 依赖注入（FastAPI Depends）
│   │       ├── background_tasks.py # 后台任务管理
│   │       ├── nginx_utils.py     # Nginx 配置工具函数
│   │       ├── nginx_generator.py # Nginx 配置模板生成
│   │       ├── cloudflare_api.py  # Cloudflare API 封装
│   │       ├── alidns_api.py      # 阿里云 DNS API 封装
│   │       ├── dns_providers.py   # DNS 提供商抽象层
│   │       └── ip_utils.py        # IP 地址工具函数
│   ├── web/                       # 前端（Vue 3）
│   │   ├── src/
│   │   │   ├── views/             # 页面组件
│   │   │   │   ├── network/       # 网络配置子组件
│   │   │   │   │   ├── DomainManager.vue   # 域名管理
│   │   │   │   │   ├── DomainReverse.vue   # 域名反代配置
│   │   │   │   │   ├── TunnelSetup.vue     # Tunnel 配置向导
│   │   │   │   │   └── TunnelPublish.vue   # Tunnel 服务发布
│   │   │   │   └── ...            # 其他页面
│   │   │   ├── composables/       # 组合式函数
│   │   │   │   └── useMobile.js   # 移动端检测
│   │   │   ├── router/            # 路由配置
│   │   │   └── api/               # API 请求封装
│   │   └── dist/                  # 构建产物
│   ├── requirements.txt
│   ├── Dockerfile              # 多阶段构建：前端编译 + Python 运行时（内置 Docker CLI）
│   └── entrypoint.sh           # 容器入口脚本（自动初始化 .env / 网络 / 模块模板）
│
├── modules/                       # 服务模块目录（构建时复制为镜像内 modules_template/）
│   ├── _registry.yaml             # 模块注册表（分类索引）
│   └── <module>/                  # 每个模块独立目录
│       ├── module.yaml            # 模块元数据（自描述）
│       ├── docker-compose.yml     # 容器编排
│       ├── templates/             # 配置模板（Jinja2）
│       └── scripts/               # 模块级脚本
│
├── data/                          # 持久化数据（gitignore）
│   ├── config.yaml                # 全局配置（运行时生成）
│   └── <module>/                  # 各模块的数据目录
│
├── scripts/                       # 全局脚本
│   ├── install.sh                 # 系统级安装脚本
│   ├── manage.sh                  # CLI 管理命令
│   └── auto-deploy.sh             # 自动化部署脚本
│
├── docs/                          # 项目文档
├── .env                           # 全局配置（gitignore）
├── .env.example                   # 配置模板
├── .dockerignore                  # Docker 构建排除规则
├── docker-compose.yml             # 核心引擎编排（自包含镜像）
└── README.md
```

> **镜像内目录结构说明**：Docker 构建时，`modules/` 复制为镜像内的 `/app/modules_template/`（只读模板），`scripts/`、`docs/`、`.env.example` 也一并打包进镜像。容器首次启动时，`entrypoint.sh` 将 `modules_template/` 内容复制到宿主机 `PROJECT_ROOT/modules/` 目录，后续运行时直接操作宿主机目录，镜像内模板保持不变。

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

1. `module_loader` 扫描 `MODULES_DIR`（宿主机运行时目录）
2. 解析每个子目录中的 `module.yaml`
3. 读取 `_registry.yaml` 获取分类信息
4. 合并为完整的模块列表供 API 和 Web 使用

**双路径回退机制**：读取模块文件（如 Nginx Jinja2 模板）时，优先从 `MODULES_DIR`（宿主机运行时目录）读取，不存在时回退到 `MODULES_TEMPLATE_DIR`（镜像内只读模板）。写入操作（如 Nginx 配置生成）始终写入 `MODULES_DIR`。

```python
# deps.py 中的常量定义
MODULES_DIR = os.environ.get("EASYSERVER_MODULES_DIR", "/easyserver_data/modules")
MODULES_TEMPLATE_DIR = os.environ.get("EASYSERVER_MODULES_TEMPLATE_DIR", "/app/modules_template")
```

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

### 多域名架构

EasyServer 支持多域名管理，通过 `config.yaml` 中的 `domains[]` 数组实现：

- 每个域名条目独立绑定 DNS 提供商（阿里云 / Cloudflare）和用途（反代 / Tunnel）
- 保留 `domain` 字段作为主域名（向后兼容），无 `domains` 字段时自动从 `domain` 推导
- 所有 API 的 `domain` 参数均为 `Optional`，默认回退主域名

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

### 智能混合路由模式（hybrid）— 推荐

域名反代与 Tunnel 中转并存，按服务粒度自由选择路由方式：

- **域名反代服务**：DNS AAAA → 服务器 IPv6 → Nginx SSL，适合 IPv6 出口稳定的服务
- **Tunnel 中转服务**：DNS CNAME → Cloudflare 边缘 → Tunnel，免端口、不依赖公网出口
- 支持逐服务切换路由方式，智能推荐一键配置
- DNS 记录自动同步，内置冲突保护（同一域名不能同时用于反代和 Tunnel）

> **推荐**：hybrid 模式是最佳实践，兼顾域名统一管理和 Tunnel 免端口优势，可按服务特性灵活选择路由。

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
- **依赖注入**：通过 `deps.py` 统一管理 FastAPI 依赖（配置、Docker 客户端等）
- **后台任务**：通过 `background_tasks.py` 管理模块安装/卸载等耗时操作
- **路由拆分**：原 config.py 路由拆分为 `config.py`（配置管理）、`network.py`（网络配置）、`domains.py`（多域名管理）

### 前端（Vue 3）

- **Element Plus 按需引入**：通过 unplugin-vue-components 自动按需导入，减小打包体积
- **路由懒加载**：所有页面组件使用 `() => import()` 动态导入，首屏加载更快
- **Vite 分包**：vendor chunk 分离，Element Plus 独立打包，利用浏览器缓存
- **移动端适配**：`useMobile` composable 统一检测移动端，响应式布局
- **组件拆分**：NetworkConfig.vue 拆分为 4 个子组件（DomainManager、TunnelPublish、TunnelSetup、DomainReverse），降低单文件复杂度
- 安装向导：极简 2 步（域名+密码），初始设置不安装任何模块，网络配置时按所选访问方式自动安装对应网络模块
- 登录页：JWT Token 认证
- 网络配置：智能推荐 + 统一管理（Tunnel / 域名反代 / IPv6 直连 / 自由配置，含 DNS 自动同步）
- 仪表盘：服务状态、网络检测、快捷操作
- 服务管理：独立卡片式操作，危险操作二次确认
- 应用商店：搜索筛选、一键安装（后台任务执行，可实时查看安装进度与失败原因）
- 备份中心：本地+云端备份、快照管理
- 设置：容器资源管理、基础信息（网络相关配置在「网络配置」页面）

### 容器化

EasyServer 采用**自包含镜像**架构：代码、前端构建产物、模块模板、运维脚本、Docker CLI 全部打包在镜像内部，宿主机仅挂载运行时数据目录。管理引擎通过挂载 Docker socket 操作其他容器。

```yaml
# docker-compose.yml（根目录）
services:
  easyserver-core:
    image: easyserver/core:latest
    build:
      context: .            # 构建上下文为项目根目录
      dockerfile: core/Dockerfile
    container_name: easyserver-core
    ports:
      - "${BIND_ADDRESS:-127.0.0.1}:8900:8000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro   # Docker socket（只读）
      - ${DATA_DIR:-./data}:/data                      # 数据持久化
      - ${PROJECT_ROOT:-./easyserver-data}:/easyserver_data  # 模块运行时目录
    environment:
      - EASYSERVER_ROOT=/app
      - EASYSERVER_MODULES_DIR=/easyserver_data/modules
      - DATA_DIR=/data
      - PROJECT_ROOT_HOST=${PROJECT_ROOT:-./easyserver-data}  # 宿主机路径（供 docker compose 使用）
      - DATA_DIR_HOST=${DATA_DIR:-./data}                 # 宿主机数据路径
    env_file:
      - .env
    restart: unless-stopped
```

**关键设计说明**：

- **无源码挂载**：镜像内代码只读，更新时重新 `docker compose build` 即可，宿主机文件不会被意外修改
- **`PROJECT_ROOT_HOST` / `DATA_DIR_HOST`**：容器内路径（`/easyserver_data`、`/data`）与宿主机路径（`${PROJECT_ROOT}`、`${DATA_DIR}`）不同，管理引擎通过 Docker socket 调用 `docker compose` 启动模块时，需使用宿主机路径写入卷映射，因此通过这两个环境变量传递宿主机实际路径
- **Docker CLI 内置**：镜像内通过 apt 安装 `docker-ce-cli`，不再依赖挂载宿主机 Docker 二进制文件
- **entrypoint.sh 自动化**：容器启动时自动完成 `.env` 生成、Docker 网络创建、模块模板初始化，无需手动干预

---

## 安全设计

- **密码安全**：使用 bcrypt 哈希存储密码，防暴力破解
- **JWT 认证**：Token 7 天有效期，JWT 密钥自动持久化到 `.env`（首次生成后不再变更）
- **登录速率限制**：限制登录尝试频率，防止暴力破解
- **Setup 白名单**：初始化接口仅允许本地访问（127.0.0.1），防止公网未初始化时被恶意配置
- **CORS 动态中间件**：根据当前域名配置动态计算允许的 Origin，避免硬编码
- **Nginx 安全头**：自动添加 X-Frame-Options、X-Content-Type-Options、Strict-Transport-Security 等安全响应头
- **容器安全**：所有容器添加 `no-new-privileges` 安全选项，防止权限提升
- `.env` 文件加入 `.gitignore`，防止密钥泄露
- DNS 凭证 API 层脱敏返回，前端不显示完整密钥
- 日志统一限制 10m/3files，防止磁盘撑满
- 域名模式下服务端口仅绑定 127.0.0.1
- SSL 证书目录不纳入版本控制
- 危险操作（停止/重启/更新）需二次确认
