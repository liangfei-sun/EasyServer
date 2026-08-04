# 网络配置指南

## DNS 配置

域名反代模式需要先配置 DNS 解析，将你的域名指向服务器 IP。

### 阿里云 DNS 配置

1. 登录 [阿里云控制台](https://dns.console.aliyun.com/)
2. 添加域名解析记录：

| 记录类型 | 主机记录 | 记录值 | 说明 |
|---------|---------|--------|------|
| A | @ | 服务器公网 IPv4 | 主域名 |
| A | * | 服务器公网 IPv4 | 泛解析（所有子域名） |
| AAAA | @ | 服务器 IPv6 | IPv6 解析（可选） |
| AAAA | * | 服务器 IPv6 | IPv6 泛解析（可选） |

### Cloudflare DNS 配置

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. 选择你的域名
3. 进入 DNS 管理页面，添加记录：

| 类型 | 名称 | 内容 | 代理状态 |
|------|------|------|---------|
| A | @ | 服务器 IPv4 | DNS only（灰色云朵） |
| A | * | 服务器 IPv4 | DNS only（灰色云朵） |
| AAAA | @ | 服务器 IPv6 | DNS only |
| AAAA | * | 服务器 IPv6 | DNS only |

> **注意**：使用域名反代模式时，请将 Cloudflare 代理状态设为「DNS only」（灰色云朵），而非「Proxied」（橙色云朵），否则流量会经过 Cloudflare，可能与 ACME 证书申请冲突。

---

## SSL 证书申请流程

EasyServer 使用 ACME 模块（acme.sh）自动申请和续签 Let's Encrypt 证书。

### 前提条件

- 域名已正确解析到服务器
- 阿里云 AccessKey 已配置（用于 DNS 验证）
- 服务器 80 端口可访问（HTTP 验证备用）

### 申请步骤

1. 在「模块市场」中安装 ACME 模块
2. 填写配置：
   - 阿里云 AccessKey 和 Secret
   - 要申请证书的主域名
3. 安装完成后，证书会自动申请
4. 证书每 60 天自动续签，无需手动操作

### 证书存储位置

证书文件存储在 `data/acme/` 目录下：
```
data/acme/
├── data/
│   └── *.你的域名/
│       ├── fullchain.cer    # 完整证书链
│       └── *.你的域名.key   # 私钥
```

---

## 域名反代配置

### 配置流程

1. 确保 DNS 解析已生效
2. 安装 Nginx 模块
3. 安装 ACME 模块并申请证书
4. 在「全局设置」中配置域名
5. 点击「生成 Nginx 配置」
6. 点击「重载 Nginx」使配置生效

### Nginx 自动生成的配置

管理引擎会为每个已安装的服务自动生成反向代理配置：

```nginx
server {
    listen 8443 ssl;
    server_name status.你的域名;

    ssl_certificate     /etc/nginx/ssl/fullchain.cer;
    ssl_certificate_key /etc/nginx/ssl/域名.key;

    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 端口说明

EasyServer 支持自定义 HTTPS 端口，请根据实际网络环境选择：

| 端口 | 适用场景 | 说明 |
|------|---------|------|
| 443 | 有公网 IPv4 且运营商未封锁 | 标准 HTTPS 端口，访问时无需输入端口号 |
| 8443 | 国内家庭宽带（默认） | 大多数运营商不封锁，兼容性好 |
| 8442/9443 | 8443 被占用时 | 自定义高位端口 |

> **国内用户注意**：部分运营商（尤其移动/联通）会封锁 443 和 80 端口。如果使用 IPv6 直连，443 端口通常可用；如果使用 IPv4 端口转发，建议先测试 443 是否可达，不可达则改用 8443。

访问时需要在域名后加端口号：

```
https://status.你的域名:8443
```

### 端口配置方法

在「全局设置」中修改 HTTPS 端口后，系统会自动重新生成 Nginx 配置并重启服务。如果修改后无法访问，请检查：
1. 路由器端口转发规则是否同步更新
2. 防火墙是否放行了新端口
3. 运营商是否封锁了该端口

---

## IPv6 直连配置

如果你的服务器有公网 IPv6 地址但不想配置域名，可以使用 IPv6 直连模式。

### 查看 IPv6 地址

```bash
ip -6 addr show scope global
```

### 配置步骤

1. 在「全局设置」中将访问模式切换为「IPv6 直连」
2. 各服务端口绑定到所有网络接口（0.0.0.0/::）
3. 通过 `http://[IPv6地址]:端口` 访问各服务

### 常用服务端口

| 服务 | 端口 | 访问地址 |
|------|------|---------|
| 管理面板 | 9800 | `http://[IPv6]:9800` |
| Uptime Kuma | 3001 | `http://[IPv6]:3001` |
| Jellyfin | 8096 | `http://[IPv6]:8096` |
| Calibre-Web | 8083 | `http://[IPv6]:8083` |
| FileBrowser | 8081 | `http://[IPv6]:8081` |

---

## Cloudflare Tunnel 配置

如果你的服务器没有公网 IP，或者 443 端口被封锁（如国内云服务器未备案），可以使用 Cloudflare Tunnel 将服务暴露到公网，访问时无需输入端口号。

### 工作原理

服务器主动向 Cloudflare 建立出站隧道连接，用户访问 Cloudflare 的标准 443 端口，Cloudflare 再通过隧道转发到本地服务。**无需服务器开放任何入站端口**，也不受运营商/云厂商端口封锁限制。

### 前提条件

- 域名已托管在 Cloudflare（已添加站点并修改 NS 记录）
- 准备一个 Cloudflare API Token，需包含以下权限：
  - `Account · Cloudflare Tunnel · Edit`
  - `Zone · DNS · Edit`

### 一键接入（推荐）

管理界面提供「内网穿透」页面，只需 3 步即可完成：

1. 在 [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens) 创建 API Token（1 分钟）
2. 在 EasyServer「内网穿透」页面粘贴 Token，点击「验证」
3. 点击「一键接入」，系统自动完成：
   - 自动创建隧道（同名隧道自动复用）
   - 保存隧道 Token 并启动 cloudflare-tunnel 容器
   - 检查域名托管状态

### 发布服务

接入完成后，在「内网穿透」页面的服务列表中点击「发布」，系统自动完成：

1. 添加 ingress 路由（hostname → http://localhost:端口）
2. 自动创建 DNS CNAME 记录（子域名 → 隧道ID.cfargotunnel.com）
3. 发布后即可通过 `https://子域名.你的域名` 免端口访问

### 映射示例

| 公网域名 | 服务地址 | 说明 |
|---------|---------|------|
| notes.你的域名 | http://localhost:8000 | NoteDiscovery |
| status.你的域名 | http://localhost:3001 | Uptime Kuma |
| media.你的域名 | http://localhost:8096 | Jellyfin |

### 手动配置（不使用管理界面）

1. 登录 [Cloudflare Zero Trust](https://one.dash.cloudflare.com/)
2. 进入 Access → Tunnels，创建新隧道
3. 复制生成的 Tunnel Token
4. 在「模块市场」中安装 Cloudflare Tunnel 模块
5. 粘贴 Tunnel Token 到配置中
6. 在 Cloudflare Dashboard 中配置公网域名映射

> **提示**：Cloudflare Tunnel 自带 SSL 加密，无需额外配置 ACME 证书。

---

## 混合模式

混合模式（hybrid）同时启用 **Nginx 反向代理** 和 **Cloudflare Tunnel**，可按需选择每个服务的访问方式：

| 服务 | 访问方式 |
|------|---------|
| 部分子域名 | `https://子域名.域名:8443`（走阿里云 Nginx） |
| 部分子域名 | `https://子域名.域名`（走 Cloudflare Tunnel，免端口） |

适用场景：域名托管在阿里云且 443 端口被封时，主服务继续走 8443，个别服务（如笔记）通过 Tunnel 实现免端口访问。配置方法：在「全局设置」中将访问模式切换为「混合模式」，然后在「内网穿透」页面发布需要走隧道服务的即可。
