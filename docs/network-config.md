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

由于国内运营商通常封锁 443 端口，EasyServer 默认使用 8443 作为 HTTPS 端口。访问时需要在域名后加端口号：

```
https://status.你的域名:8443
```

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

如果你的服务器没有公网 IP，可以使用 Cloudflare Tunnel 将服务暴露到公网。

### 前提条件

- 域名已托管在 Cloudflare
- Cloudflare 账户已开通 Tunnel 功能

### 配置步骤

1. 登录 [Cloudflare Zero Trust](https://one.dash.cloudflare.com/)
2. 进入 Access → Tunnels，创建新隧道
3. 复制生成的 Tunnel Token
4. 在「模块市场」中安装 Cloudflare Tunnel 模块
5. 粘贴 Tunnel Token 到配置中
6. 在 Cloudflare Dashboard 中配置公网域名映射

### 映射示例

| 公网域名 | 服务地址 |
|---------|---------|
| dashboard.你的域名 | http://localhost:9800 |
| status.你的域名 | http://localhost:3001 |
| media.你的域名 | http://localhost:8096 |

> **提示**：Cloudflare Tunnel 自带 SSL 加密，无需额外配置 ACME 证书。
