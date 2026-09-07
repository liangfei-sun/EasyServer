# Nginx 反向代理 · 运行指南

> 基于 2026-09-04 WSL Ubuntu 24.04 实测（QA 报告 R10）。实测结论与上游描述不一致处，以实测为准并已标注。
>
> **2026-09-07 修复更新（QA 报告 R37/R38）**：本篇早期实测记录的「证书缺失必崩」「不支持 WebSocket」「超时配置丢失」等问题已在 `feature/wsl-install-test` 分支修复（BUG-2 commit `94ef4ef`、BUG-3 commit `292206f`、BUG-5 commit `e781d29`），相关章节已按修复后行为更新，历史实测记录以「已修复」标注保留。

## 1. 概述

Nginx 反向代理是所有服务的统一入口，提供 SSL 终止、按子域名路由、HTTP→HTTPS 跳转。域名反代与智能混合路由模式依赖本模块。

| 项 | 值 |
|------|------|
| 镜像 | `nginx:stable` |
| 分类 | infra（网络基础设施） |
| 网络模式 | `host`（默认，直接使用宿主网络栈；可选 bridge） |
| 端口 | HTTP 监听端口由引擎配置 `http_port` 决定（模板渲染，缺省 80；域名反代部署实践中通常为 **8080**，属设计决策——规避国内运营商对 80/443 的封锁，见第 9 节）、**8443**（HTTPS 入口） |
| 资源限制 | 内存 256m / CPU 1.0 |
| 容器名 | `easyserver-nginx` |
| WebSocket | ✅ 模板已内置升级头（BUG-3 修复，见 3.3） |
| 代理超时 | ✅ 模板已内置 connect 60s / send 300s / read 300s（BUG-5 修复，见 3.3） |

## 2. 前置条件

- 核心引擎运行中（`/api/health` 返回 ok）
- **无硬依赖模块**（`depends_on: []`）；可选配合 acme 模块自动签发证书（soft_depends_on）
- **端口检查**：HTTP 端口（`http_port`，常见 8080）与 8443 需在宿主侧可用。WSL2 mirrored 模式用户注意：Windows 侧进程占用端口时 WSL 内无法绑定（用 `/mnt/c/Windows/System32/netstat.exe -ano | findstr ":80 "` 排查）
- **证书**：**无需手动准备**（BUG-2 修复，commit `94ef4ef`）。`configure_network` 在 domain/hybrid 模式启动 nginx 前会自动调用 `ensure_self_signed_cert()`：检查 `modules/nginx/ssl/<域名>/` 下证书是否存在，不存在则用 openssl 生成自签名证书（含 SAN 通配符 `*.<域名>`，有效期 365 天）。正式证书由 acme 模块签发后自动替换

## 3. 安装

### 3.1 配置字段

| 字段 | 说明 | 默认值 | 必填 |
|------|------|--------|:---:|
| `NGINX_HTTP_PORT` | HTTP 监听端口（ACME 验证与跳转） | 80 | 是 |
| `NGINX_HTTPS_PORT` | HTTPS 监听端口（国内环境建议 8443） | 8443 | 是 |
| `NGINX_NETWORK_MODE` | 网络模式：host（推荐）/ bridge | host | 是 |

> 实测注意：模块配置表单的 `NGINX_HTTP_PORT` 仅用于健康检查 URL 渲染，站点配置的实际监听端口来自引擎配置 `http_port`（缺省 80）。修改方法见[网络配置指南 6.2 节](../NETWORK_CONFIG_GUIDE.md)。早期实测记录的「`listen 80` 模板硬编码」（缺陷 B）已不成立——当前模板为 `listen {{ http_port }}`。

### 3.2 安装路径与实测行为

**面板/API 安装**：应用商店 → Nginx → 安装（或 `POST /api/modules/install {"module_id":"nginx","config":{...}}`）。

**历史实测警告（2026-09-04，已修复）**：install 返回 success ≠ 容器健康。当时首次安装后容器进入 crash loop，两个必现问题：

1. **证书缺失（已修复，BUG-2 / commit `94ef4ef`）**：站点配置引用 `/etc/nginx/ssl/<域名>/fullchain.cer`，证书不存在时 nginx 启动即崩（`cannot load certificate`）。**现已自动修复**：`configure_network`（domain/hybrid 模式）启动 nginx 前自动生成自签名证书，无需任何手动步骤。
2. **80 端口被占（环境相关）**：Windows 侧占用 80 时 host 模式 `bind() failed`。当前模板监听端口来自 `http_port` 配置，域名反代部署实践中使用 8080（设计决策，规避运营商封锁 80/443），修改方法见[网络配置指南 6.2 节](../NETWORK_CONFIG_GUIDE.md)。

**~~实测修复步骤（手动生成自签证书）~~ —— 不再需要**：以下命令为 BUG-2 修复前的临时救急手段，仅作历史记录保留。**当前版本引擎在 `configure_network` 时自动生成自签名证书**（含 SAN 通配符），若你仍遇到 `cannot load certificate`，说明引擎自动证书生成失败（属引擎 bug），请先检查引擎日志中「自签名 SSL 证书」相关条目，再按第 9 节排查：

```bash
# ⚠️ 历史记录（BUG-2 修复前的手动救急步骤，现已不需要）
# sudo openssl req -x509 -newkey rsa:2048 -keyout <域名>.key -out fullchain.cer -days 1 -nodes -subj "/CN=<你的域名>"
# sudo mkdir -p <PROJECT_ROOT>/modules/nginx/ssl/<你的域名>
# sudo mv fullchain.cer <域名>.key <PROJECT_ROOT>/modules/nginx/ssl/<你的域名>/
# sudo docker restart easyserver-nginx
```

### 3.3 反代模板内置能力（2026-09-07 修复后）

当前 `sites.conf.j2` 模板为每个站点自动包含以下配置，**无需用户手动添加**：

| 能力 | 模板内容 | 来源 |
|------|---------|------|
| WebSocket 支持 | `proxy_http_version 1.1` + `proxy_set_header Upgrade $http_upgrade` + `proxy_set_header Connection $connection_upgrade` | BUG-3 修复（commit `292206f`）。`$connection_upgrade` map 变量定义在 `websocket-map.conf`，由 `generate_all` 自动部署到 `conf.d/` |
| 代理超时 | `proxy_connect_timeout 60s` / `proxy_send_timeout 300s` / `proxy_read_timeout 300s` | BUG-5 修复（commit `e781d29`）。此前手动添加的超时配置会在模板重新生成（模块安装/卸载）时丢失，现已内置，长连接/大文件上传不再被截断 |
| 模块级扩展 | `proxy_extra`（module.yaml）注入的额外指令（如 jellyfin 的 `proxy_buffering off`） | 原有机制，与上述内置项叠加 |

适用模块举例：uptime-kuma 实时通知（Socket.IO）、nextcloud 推送、joplin 同步状态等 WebSocket 场景均已验证可通（R38 修复续记）。

## 4. 启动与验证

```bash
# 容器状态
sudo docker ps --filter name=easyserver-nginx        # 预期 Up（本模块 compose 无内置 healthcheck）

# 引擎侧健康检查 URL（module.yaml；端口换成你的 http_port）
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080

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
按日志区分：`cannot load certificate` → **BUG-2 修复后此错误应由引擎自动修复**（`configure_network` 启动 nginx 前自动生成自签名证书）；若仍出现，说明自动证书生成失败（openssl 缺失、目录权限等），属引擎 bug——先看引擎日志中「自签名 SSL 证书」条目，再手动检查 `modules/nginx/ssl/<域名>/` 目录。`bind() to 0.0.0.0:XX failed` → HTTP 端口被占，`sudo lsof -i :<端口>`（WSL mirrored 环境用 netstat.exe）排查后改 `http_port`（见[网络配置指南 6.2](../NETWORK_CONFIG_GUIDE.md)）或释放端口。

**Q：访问显示 502 Bad Gateway？**
检查后端服务是否运行、端口是否正确。实测确认 host 模式下配置中 `proxy_pass http://127.0.0.1:8900` 指向宿主 loopback，语义正确（早期疑点已由实测撤销）；若核心引擎端口经 override 改过（如 8901），需相应调整 sites.conf。

**Q：如何自定义 Nginx 配置？**
在 `<PROJECT_ROOT>/modules/nginx/conf.d/` 添加 `.conf` 文件后重载 Nginx。

**Q：HTTP 端口能改吗？**
能，但入口不在模块表单——面板的 `NGINX_HTTP_PORT` 不会渲染进站点配置（实测），实际监听端口由引擎配置 `http_port` 决定，修改方法见[网络配置指南 6.2 节](../NETWORK_CONFIG_GUIDE.md)（改 config.yaml 后 regenerate）。

**Q：WebSocket 应用（uptime-kuma 实时通知、nextcloud 推送等）通过反代连不上？**
先确认引擎版本包含 BUG-3 修复（commit `292206f` 之后）：`grep Upgrade <PROJECT_ROOT>/modules/nginx/conf.d/sites.conf` 应能看到 `proxy_set_header Upgrade $http_upgrade`，且 `conf.d/websocket-map.conf` 存在。若配置是修复前生成的旧文件，重新执行一次配置生成（`POST /api/nginx/config/generate` 或重新 `configure_network`）即可。

## 9. 实测排错

实测环境：WSL2 mirrored，Windows 侧进程占用 80。关键证据摘录（2026-09-04 历史记录，证书问题已由 BUG-2 修复自动处理）：

```
# 首装 crash 根因①：证书缺失（已修复：configure_network 自动生成自签名证书）
easyserver-nginx | nginx: [emerg] cannot load certificate "/etc/nginx/ssl/example.test/fullchain.cer": BIO_new_file() failed
# 首装 crash 根因②：80 被占（现模板监听 http_port，域名反代实践用 8080）
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

### 9.1 关于 `http_port=8080`（BUG-3 结论：设计决策，非缺陷）

R37 曾将「HTTP 监听 8080 而非 80」列为 BUG-3，经确认**这是设计决策，不是缺陷**：国内运营商普遍封锁住宅宽带的 80/443 入站端口，EasyServer 的域名反代链路因此采用 8080（HTTP）/ 8443（HTTPS）非标准端口。副作用需知悉：

- 浏览器访问必须带端口号（如 `https://panel.<域名>:8443/`）
- ACME HTTP-01 验证要求 80 端口可达，在 8080 监听下不可用——证书签发请走 DNS-01 验证（acme 模块即 DNS 验证方式）

### 9.2 证书自动生成的验证方法（BUG-2 修复后）

```bash
# 删除证书目录模拟缺失
sudo rm -rf <PROJECT_ROOT>/modules/nginx/ssl/<你的域名>
# 重新触发网络配置（domain 或 hybrid 模式）
curl -s -X POST http://localhost:8901/api/config/network -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"access_mode":"domain","https_port":8443}'
# 预期：证书自动重建（fullchain.cer + <域名>.key），nginx 正常启动，nginx -t 通过
# （ssl_stapling ignored 警告为自签名证书预期行为，可忽略）
```
