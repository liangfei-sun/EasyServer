# Nginx 反向代理 · 运行指南

> 基于 2026-09-04 WSL Ubuntu 24.04 实测（QA 报告 R10）。实测结论与上游描述不一致处，以实测为准并已标注。

## 1. 概述

Nginx 反向代理是所有服务的统一入口，提供 SSL 终止、按子域名路由、HTTP→HTTPS 跳转。域名反代与智能混合路由模式依赖本模块。

| 项 | 值 |
|------|------|
| 镜像 | `nginx:stable` |
| 分类 | infra（网络基础设施） |
| 网络模式 | `host`（默认，直接使用宿主网络栈；可选 bridge） |
| 端口 | 80（HTTP，ACME 验证/跳转）、8443（HTTPS 入口） |
| 资源限制 | 内存 256m / CPU 1.0 |
| 容器名 | `easyserver-nginx` |

## 2. 前置条件

- 核心引擎运行中（`/api/health` 返回 ok）
- **无硬依赖模块**（`depends_on: []`）；可选配合 acme 模块自动签发证书（soft_depends_on）
- **端口检查**：80 与 8443 需在宿主侧可用。WSL2 mirrored 模式用户注意：Windows 侧进程占用 80 时 WSL 内无法绑定，实测环境中 0.0.0.0:80 被宿主侧进程占用（用 `/mnt/c/Windows/System32/netstat.exe -ano | findstr ":80 "` 排查）
- **证书**：nginx 生成的站点配置引用 ACME 证书文件。实测确认：**未安装 acme/未签发证书时首次启动必失败**（见第 3.2 节与第 9 节）

## 3. 安装

### 3.1 配置字段

| 字段 | 说明 | 默认值 | 必填 |
|------|------|--------|:---:|
| `NGINX_HTTP_PORT` | HTTP 监听端口（ACME 验证与跳转） | 80 | 是 |
| `NGINX_HTTPS_PORT` | HTTPS 监听端口（国内环境建议 8443） | 8443 | 是 |
| `NGINX_NETWORK_MODE` | 网络模式：host（推荐）/ bridge | host | 是 |

> 实测注意：模块配置表单的 `NGINX_HTTP_PORT` 仅用于健康检查 URL 渲染，**站点配置文件内 `listen 80` 为模板硬编码**（缺陷 B）——改 HTTP 端口需同步修改 `conf.d` 下配置文件，见 3.2。

### 3.2 安装路径与实测行为

**面板/API 安装**：应用商店 → Nginx → 安装（或 `POST /api/modules/install {"module_id":"nginx","config":{...}}`）。

**实测警告：install 返回 success ≠ 容器健康**。实测首次安装后容器进入 crash loop，两个必现问题：

1. **证书缺失（必现）**：站点配置引用 `/etc/nginx/ssl/<域名>/fullchain.cer`，未签发证书时 nginx 启动即崩（`cannot load certificate`）。
2. **80 端口被占（环境相关）**：模板硬编码 `listen 80`，端口被占时 `bind() failed`。

**实测修复步骤**（宿主执行；命令中 `<PROJECT_ROOT>` 默认安装为容器内路径映射 `/easyserver_data`，按安装指南第 3 步（3b）自定义 PROJECT_ROOT 的用户请替换）：

```bash
# ① 生成自签证书临时救急（正式证书由 acme 模块签发后替换）
sudo openssl req -x509 -newkey rsa:2048 -keyout <域名>.key -out fullchain.cer -days 1 -nodes -subj "/CN=<你的域名>"
sudo mkdir -p <PROJECT_ROOT>/modules/nginx/ssl/<你的域名>
sudo mv fullchain.cer <域名>.key <PROJECT_ROOT>/modules/nginx/ssl/<你的域名>/

# ② 若 80 被占，改 listen 端口（sites.conf 与 default.conf 各一处）
sudo sed -i 's/listen 80;/listen 8080;/' <PROJECT_ROOT>/modules/nginx/conf.d/sites.conf
sudo sed -i 's/listen 80 default_server;/listen 8080 default_server;/' <PROJECT_ROOT>/modules/nginx/conf.d/default.conf

sudo docker restart easyserver-nginx
```

修复后容器正常运行。上游无此预警，属实测发现的模板级缺陷（缺陷 A/B）。

## 4. 启动与验证

```bash
# 容器状态
sudo docker ps --filter name=easyserver-nginx        # 预期 Up（本模块 compose 无内置 healthcheck）

# 引擎侧健康检查 URL（module.yaml）
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:80    # 80 可绑定时

# HTTPS 入口（实测通过判据）
curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1:8443/
# 实测输出：200（返回管理面板 HTML）
```

无初始账号（nginx 本身无登录）。证书正式签发由 acme 模块完成，自签证书仅作临时救急。

## 5. 访问方式

- **直连**：`https://<服务器IP>:8443`（自签证书需 `-k` 或忽略浏览器告警；正式证书无告警）
- **子域名反代**：不适用——nginx 自身就是反代入口（`is_proxy: true`），各服务的子域名路由由它提供
- **Cloudflare Tunnel**：Tunnel 模式下 nginx 不承担入口角色（流量走 cloudflared）；混合路由中域名反代侧的流量仍经 nginx

## 6. 数据与备份

| 路径（宿主，挂载卷） | 内容 |
|------|------|
| `<PROJECT_ROOT>/modules/nginx/conf.d/` | 站点反代配置（sites.conf / default.conf / ssl-params.conf） |
| `<PROJECT_ROOT>/modules/nginx/ssl/` | 证书与私钥（ACME 产物或自签救急证书） |
| `<PROJECT_ROOT>/modules/nginx/log/` | 访问/错误日志 |
| `<PROJECT_ROOT>/modules/nginx/acme-challenge/` | ACME HTTP 验证目录 |

配置与证书均在上列目录内，常规备份覆盖 `conf.d/` 与 `ssl/` 即可。修改配置后用面板「重载 Nginx」或 `POST /api/nginx/reload` 热更新（**实测已装态 reload 返回 200 成功**；未安装态才会 500）。

## 7. 卸载

- 面板卸载或 `POST /api/modules/uninstall`（`remove_data: true` 时返回 `data_removed:true`）
- **实测残留（缺陷 C）**：返回 `removed_paths:[]` 但宿主 `modules/nginx/`（conf.d、ssl）目录**不会被删除**，需手动清理；root 属主目录需 `sudo rm`
- **实测警告（缺陷 D）**：卸载会**自动删除 `nginx:stable` 镜像**。弱网环境卸载→重装需全量重拉（实测约 8.8 分钟），重装前确认网络条件

## 8. FAQ

**Q：Nginx 启动失败？**
按日志区分：`cannot load certificate` → 未签发证书，按 3.2 生成自签或先装 acme；`bind() to 0.0.0.0:80 failed` → 80 被占，`sudo lsof -i :80`（WSL mirrored 环境用 netstat.exe）排查后改 listen 或释放端口。

**Q：访问显示 502 Bad Gateway？**
检查后端服务是否运行、端口是否正确。实测确认 host 模式下配置中 `proxy_pass http://127.0.0.1:8900` 指向宿主 loopback，语义正确（早期疑点已由实测撤销）；若核心引擎端口经 override 改过（如 8901），需相应调整 sites.conf。

**Q：如何自定义 Nginx 配置？**
在 `<PROJECT_ROOT>/modules/nginx/conf.d/` 添加 `.conf` 文件后重载 Nginx。

**Q：HTTP 端口能改吗？**
面板的 `NGINX_HTTP_PORT` 不会渲染进站点配置（实测，缺陷 B），需按 3.2 直接改 `conf.d` 下文件。

## 9. 实测排错

实测环境：WSL2 mirrored，Windows 侧进程占用 80。关键证据摘录：

```
# 首装 crash 根因①：证书缺失
easyserver-nginx | nginx: [emerg] cannot load certificate "/etc/nginx/ssl/example.test/fullchain.cer": BIO_new_file() failed
# 首装 crash 根因②：80 被占
easyserver-nginx | nginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)
# 修复后验证
$ curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1:8443/   → 200
$ docker exec easyserver-nginx curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8900/   → 200（uvicorn）
# uninstall
{"success":true,"module":"nginx","data_removed":true,"removed_paths":[]}
$ ls /easyserver_data/modules/nginx → conf.d/ ssl/（残留）
$ docker images | grep nginx → 无（镜像被自动删除）
```

> 引擎对 install 无健康门控（缺陷 A 族共性）：install success 后务必 `docker ps` 确认容器非 Restarting 状态。
