# EasyServer 网络配置指南

> 面向用户讲清楚「网络配置」页面的每一种玩法，并如实标注 **QA 实测确认的系统行为**（含与预期不同的行为差异）。上游完整文档见 `docs/network-config.md`，本文为其场景化教程版。
>
> 适用版本：EasyServer 0.2.x · 实测环境：WSL2 Ubuntu 24.04，零模块基线 + JWT 认证。

---

## 目录

- [1. 功能概述与入口](#1-功能概述与入口)
- [2. 访问模式对比与切换预警](#2-访问模式对比与切换预警)
- [3. 双源配置结构（config.yaml + .env）](#3-双源配置结构configyaml--env)
- [4. 场景一：域名反代（domain）](#4-场景一域名反代domain)
- [5. 场景二：IPv6 直连（ipv6_direct）](#5-场景二ipv6-直连ipv6_direct)
- [6. 场景三：Cloudflare Tunnel](#6-场景三cloudflare-tunnel)
- [7. 场景四：智能混合路由（hybrid）](#7-场景四智能混合路由hybrid)
- [8. 场景五：自由配置（custom）](#8-场景五自由配置custom)
- [9. 域名管理](#9-域名管理)
- [10. 端口检查（port-check）](#10-端口检查port-check)
- [11. SSL 证书与 Nginx 反代流程](#11-ssl-证书与-nginx-反代流程)
- [12. 实测排错与已知行为差异](#12-实测排错与已知行为差异)
- [13. FAQ 精选](#13-faq-精选)

---

## 1. 功能概述与入口

「网络配置」（侧边栏入口，路由 `/network`）是所有网络功能的统一入口：选择访问方式、域名与 DNS 管理、服务发布、SSL 证书。

页面结构从上到下：网络状态总览 → 当前模式的管理区 → Tunnel 中转服务卡片 → 高级选项（折叠，含切换访问方式）→ 域名信息。

所有配置操作既可通过 Web 面板完成，也可通过 REST API（`/docs` 有完整 Swagger UI）操作，本文同时给出两种方式。

---

## 2. 访问模式对比与切换预警

### 2.1 四种自动模式对比（含实测行为）

| 模式 | `ACCESS_MODE` 值 | 前提条件 | 实测 `BIND_ADDRESS` 行为 | 切换副作用（实测） |
|------|------|---------|------|------|
| 域名反代 | `domain` | 域名 + DNS 凭证 + 服务器公网可达 | `127.0.0.1`（还原/保持仅本机） | **自动安装并启动** Nginx、ACME、DDNS 模块 |
| Cloudflare Tunnel | `cloudflare_tunnel` | 域名托管 Cloudflare + API Token | `127.0.0.1` | **自动启动** cloudflare-tunnel 容器、停用 Nginx/ACME |
| IPv6 直连 | `ipv6_direct` | 服务器有公网 IPv6 | **`'::'`**（IPv6 全零地址，监听所有接口含 IPv6；**非 `0.0.0.0`**） | 停止代理类模块、重启已装模块；`network_configured→True` |
| 智能混合路由 | `hybrid` | 域名 + DNS 凭证 + CF Tunnel Token | `127.0.0.1` | **domain 全部动作 + 自动触发后台 DNS 同步 + 启动 cloudflare-tunnel** |

> 第五种 `custom`（自由配置）见第 8 节，实测切换无模块副作用，`BIND_ADDRESS` 还原为 `127.0.0.1`。

### 2.2 切换前必读预警（实测确认）

1. **domain / hybrid 切换会真实安装并启动模块**：系统把未安装的 Nginx、ACME、DDNS（hybrid 另加 Cloudflare Tunnel）写入 `installed_modules` 并执行 `docker compose up`，**触发镜像拉取**，首次切换可能持续数分钟，页面显示全屏提示「正在切换访问方式…请勿关闭页面」属正常现象。
2. **失败会残留状态**：实测源码确认，模块写入 `installed_modules` 发生在启动动作之前，若镜像拉取失败或启动出错，已写入的安装状态不会自动回滚。
3. **无 Token 切到 cloudflare_tunnel 会让 cloudflared 反复崩溃**：实测源码确认，未配置 Tunnel Token 时切换会直接启动无 token 的 cloudflared 容器（crash loop 残留）并触发镜像拉取。**务必先在凭证中配好 Token 再切换。**
4. **DNS 凭证为空时不要切 domain/hybrid**：DNS 同步与证书申请都会失败；hybrid 还会立即触发一次后台 DNS 同步。
5. UI 上通过「高级选项 → 切换访问方式」按钮切换，与 API `POST /api/config/network {"access_mode":"..."}` 等价。

---

## 3. 双源配置结构（config.yaml + .env）

EasyServer 使用**双源分层配置**，理解这点能避开绝大多数凭证类问题：

| 文件 | 职责 | 内容举例 |
|------|------|---------|
| `data/config.yaml` | 核心运行配置：网络模式、域名、DNS 凭证、模块列表 | `access_mode`、`domain`、`dns_credentials` |
| `.env`（挂载卷内运行时副本） | 环境变量：路径、域名、凭证、模块专用配置 | `ACCESS_MODE`、`BIND_ADDRESS`、`ALI_KEY` |

**实测确认的联动行为**：

- 通过面板/API **切换访问模式**时，系统自动把 `ACCESS_MODE`、`BIND_ADDRESS`、`HTTPS_PORT` 同步写入 `.env`（实测 `ipv6_direct` 切换后 `.env` 中出现 `ACCESS_MODE='ipv6_direct'`、`BIND_ADDRESS='::'`）。
- **凭证同步陷阱**：`GET /config` 会触发 `_sync_credentials_from_env()`，用 `.env` 里的凭证**覆盖** `config.yaml`。因此**修改 DNS 凭证时必须同时更新 `.env` 和 `config.yaml` 两处**，只改 `config.yaml` 会在下次读取时被回退覆盖。
- 面板内修改凭证通常两处都会写；直接手工编辑文件时务必自己保持同步。

---

## 4. 场景一：域名反代（domain）

**适用**：有自己的域名（任意 DNS 服务商），服务器公网可达，希望大带宽直连（流量不经中转）。访问地址带 HTTPS 端口（默认 8443）。

### 4.1 自备凭据清单（系统不会替你创建）

| 凭据 | 用途 | 获取方式 |
|------|------|---------|
| 阿里云 AccessKey ID + Secret（`ALI_KEY`/`ALI_SECRET`） | DNS 记录自动同步 + ACME DNS 验证 | 阿里云 RAM 控制台创建用户，授权 `AliyunDNSFullAccess` |
| Cloudflare API Token | 同上（Cloudflare 托管域名时） | CF Dashboard → API Tokens，需 `Zone · DNS · Edit` 权限；**`eyJ` 开头的是 Tunnel Token，不是 API Token，勿混淆** |

### 4.2 配置流程

1. 「网络配置」→「域名反代配置」→ 选择 DNS 提供商并填入凭证
2. 设置 HTTPS 端口（默认 8443）与管理面板子域名
3. 点击「保存并应用」：系统保存凭证、生成 Nginx 配置并重载
4. 点击「立即同步 DNS 记录」：自动为所有子域名创建 A/AAAA 解析（幂等：不存在则建、一致则跳过、IP 变化则更新，天然支持 DDNS）
5. 等待 DNS 生效（几分钟），之后通过 `https://子域名.你的域名:8443` 访问
6. SSL 证书由 ACME 模块通过 DNS API 验证自动申请 Let's Encrypt 证书，到期前 60 天自动续签

### 4.3 实测注意（nginx 未安装态的行为差异）

| 操作 | 实测行为 | 结论 |
|------|---------|------|
| `POST /api/nginx/generate`（未装 nginx） | 返回 200「Nginx 配置已生成」，且实际落盘 3 个配置文件，**无任何"nginx 未安装"提示** | 生成≠安装；配置落盘属正常预写，真正生效需安装 nginx 模块 |
| `POST /api/nginx/reload`（未装 nginx） | **返回 500 `{"detail":"Nginx 重载失败"}` 硬报错**，非静默跳过 | 未安装 nginx 时先安装模块再 reload；看到此 500 先检查模块是否已装 |

---

## 5. 场景二：IPv6 直连（ipv6_direct）

**适用**：无域名但服务器有公网 IPv6（云服务器需开通 IPv6），内网或信任网络使用。无需 DNS、无需证书，但**无 HTTPS 加密**。

### 5.1 启用步骤

1. 「网络配置」→「高级选项」→「切换到 IPv6 直连」
   （API 等价：`POST /api/config/network {"access_mode":"ipv6_direct","https_port":8443}`，实测返回 `{"success":true,...,"message":"网络配置已保存"}`）
2. 系统自动停止 Nginx / ACME / Tunnel 等代理模块，把服务监听地址切到所有接口，并重启已安装模块
3. 页面展示各服务访问链接 `http://[IPv6地址]:端口`，可直接复制

### 5.2 实测行为：BIND_ADDRESS 为 `'::'` 而非 0.0.0.0

实测切换后 `.env` 中 `BIND_ADDRESS='::'`（IPv6 全零地址）。效果上同样是监听所有接口（含 IPv6），但如果你在其他文档或脚本里预期看到 `0.0.0.0`，请不要误判为配置错误。验证方式：

```bash
docker exec easyserver-core grep -E '^(ACCESS_MODE|BIND_ADDRESS)' /app/.env
# 实测输出：ACCESS_MODE='ipv6_direct'  BIND_ADDRESS='::'
```

同时 `network_configured` 被置为 `True`。切回其他模式（实测切 `custom`）后 `BIND_ADDRESS` 还原为 `'127.0.0.1'`。

---

## 6. 场景三：Cloudflare Tunnel

**适用**：无公网 IP、443/80 被封（未备案）、追求免端口访问。服务器主动向 Cloudflare 建立出站隧道，用户走 Cloudflare 标准 443 端口，自带 SSL，访问地址不带端口号。

### 6.1 前提（自备凭据）

1. **域名已托管到 Cloudflare**（NS 记录指向 Cloudflare）
2. **Cloudflare API Token**：需权限 `Account · Cloudflare Tunnel · Edit` + `Zone · DNS · Edit`（Dashboard → My Profile → API Tokens 创建，生成后仅显示一次，立即保存）

### 6.2 接入流程

1. 「网络配置」→ Cloudflare Tunnel 卡片 →「一键接入」
2. 粘贴 API Token →「验证 Token」→ 看到「Token 有效」
3. 点「一键接入」：弹窗逐步显示创建/复用隧道 → 启动 cloudflare-tunnel 容器 → 检查域名托管状态
4. 「接入完成！」且网络状态显示「已连接」即成功

### 6.3 发布服务

「服务发布」卡片 →「可发布」页签 → 点「发布」：自动添加隧道路由（子域名 → 本地端口）并**自动创建 CNAME 记录**，发布后 `https://子域名.你的域名` 免端口访问。「取消发布」会同时删除路由与 CNAME。

### 6.4 实测预警

- **务必先配好 Token 再切换到本模式**。实测源码确认：无 Token 时切换（`POST /api/config/network {"access_mode":"cloudflare_tunnel"}`）会直接启动无 token 的 cloudflared 容器，进入 crash loop 残留，并触发镜像拉取。
- 隧道要求域名的权威 DNS 必须托管在 Cloudflare，否则 `cfargotunnel.com` 的 CNAME 无法工作。主域名托管在别处时，可按第 9.3 节添加一个 Cloudflare 托管的域名专用于 Tunnel。

---

## 7. 场景四：智能混合路由（hybrid）

**适用**：既有大带宽服务（Jellyfin/Frigate/Nextcloud 等），又有轻量服务（笔记/监控面板），想按服务分流——大带宽走域名反代（带宽直达），轻量走 Tunnel 中转（免端口）。

### 7.1 概念

两种路由方式**按服务并存**，同一子域名同一时刻只走一条路：

| 路由方式 | 流量路径 | 地址格式 |
|---------|---------|---------|
| 域名反代 | DNS AAAA → 服务器 IPv6 → Nginx SSL → 服务 | `https://子域名.域名:8443`（带端口） |
| Tunnel 中转 | DNS CNAME → Cloudflare 边缘 → Tunnel → 服务 | `https://子域名.域名`（免端口） |

### 7.2 配置步骤

1. **先完成前置**：域名信息已填、域名反代凭证已配置、Cloudflare Tunnel 已接入（三者在前面场景中完成）
2. 「高级选项」→ 点「智能混合路由」→ 确认切换。**首次切换会自动安装并启动 Nginx、ACME、DDNS、Cloudflare Tunnel 全套模块**，耗时数分钟，勿关页面
3. 在「Tunnel 中转服务」卡片为每个服务点「切换为 Tunnel 中转」或「切换为 域名反代」；切换后系统自动维护 DNS（Tunnel 建 CNAME 并清理 A/AAAA，反向则由 DNS 同步补建），无需手动操作
4. 可选：点「智能推荐」一键分流——实测推荐策略为 Frigate、Nextcloud、Jellyfin、FileBrowser、Calibre-Web 走域名反代；NoteDiscovery、Joplin、Uptime Kuma 走 Tunnel 中转

### 7.3 实测预警

hybrid 切换 = **domain 的全部动作**（自动装 Nginx/ACME/DDNS 并真实启动）**+ 立即触发一次后台 DNS 同步 + 启动 cloudflare-tunnel**。它是副作用最大的切换动作，DNS 凭证或 Tunnel Token 任一缺失时都不要执行；失败后 `installed_modules` 可能残留（见 2.2 预警第 2 条），需到应用商店核对模块状态。

### 7.4 DNS 同步的「跳过」提示

同步结果出现「跳过 N 条」表示该子域名已存在 CNAME（服务正通过 Tunnel 发布），系统主动跳过以避免同域 CNAME 与 A/AAAA 冲突——**这是保护机制，不是错误**。想让该服务改回域名反代：先在卡片中「切换为 域名反代」，再重新同步。

---

## 8. 场景五：自由配置（custom）

面向高级用户：**系统不自动管理任何网络模块**，由你自行在应用商店安装配置 Nginx、DDNS、ACME、Tunnel 等。

实测切换行为：`POST /api/config/network {"access_mode":"custom"}` 返回成功后，`BIND_ADDRESS` 还原为 `'127.0.0.1'`，**无任何模块被安装或启动**——五种模式中唯一零副作用的切换，可作为误切换后的「安全回退档」。页面提供已装网络模块状态列表、启动/停止按钮与「重新生成 Nginx 配置」手动入口。

---

## 9. 域名管理

### 9.1 增查删（实测 API 行为）

| 操作 | API | 实测行为 |
|------|-----|---------|
| 查询 | `GET /api/config/domains` | 返回域名数组，每项含 `domain`、`dns_provider`、`purpose`、`status` |
| 添加 | `POST /api/config/domains` | 缺 `dns_provider` → **422 明确报错**；`purpose` 非法 → **400 `"purpose 必须为 nginx / tunnel / both"`**；合法添加 → 200 且**自动触发一次 verify** |
| 验证 | `POST /api/config/domains/{domain}/verify` | 返回逐项检查结果；**凭据缺失时明确报错**（如 `"阿里云 DNS 凭证未配置"`）；见 9.2 的副作用预警 |
| 删除 | `DELETE /api/config/domains/{domain}` | **主域名删除被拒**（400 `"不允许删除主域名"`，合理保护）；其他域名可删 |

`purpose` 取值：`nginx`（域名反代）/ `tunnel`（Tunnel 中转）/ `both`（两者皆可）。

### 9.2 verify 的两个实测坑

1. **tunnel_dns 检查项报 `[Errno 2] No such file or directory`**：容器内缺少 DNS 工具（与 `dig` 缺失同根源），该项失败**不代表域名真有问题**，先看 dns_provider 与 ssl 两项结果。
2. **verify 有不可逆副作用**：实测对主域名执行 verify 后，其 `status` 被从 `active` 改为 `error` 且无单独恢复途径。建议 verify 前确认凭证已配好，避免对生产域名反复 verify。

### 9.3 多域名配置

Tunnel 要求域名托管在 Cloudflare。主域名在阿里云等别处时，添加一个 Cloudflare 托管域名专用于 Tunnel：

1. 「域名管理」→「添加域名」→ 填域名、选 Cloudflare、用途选「Tunnel 中转」
2. 系统自动验证 DNS 连通性，通过后 Tunnel 发布时即可选择该域名
3. 多域名时 Tunnel 服务卡片顶部出现「目标域名」下拉选择器；单域名则自动使用

> 免费域名提示（上游实测结论）：并非所有免费后缀都支持 NS 迁移到 Cloudflare（如 DigitalPlat 的 `.dpdns.org`/`.qzz.io` 支持），注册前先确认可改 NS。

---

## 10. 端口检查（port-check）

```bash
curl -s http://localhost:8900/api/services/port-check
```

实测返回结构：`{"has_conflict": false, "conflicts": [], ...}` 并**列出全部注册模块端口清单**（实测 10 个）。两个使用要点：

1. **空安装态也会列出全部注册模块端口**（当前实现行为），该清单是"系统规划的端口全景"而非"已安装端口"，解读时注意。
2. `has_conflict:true` 时逐条看 `conflicts`。WSL2 mirrored 模式用户注意：Windows 侧占用导致的冲突在 Linux 侧 `ss`/`lsof` 查不到，需用 `/mnt/c/Windows/System32/netstat.exe -ano | findstr <端口>` 在 Windows 侧排查（详见安装指南第 6 节）。

---

## 11. SSL 证书与 Nginx 反代流程

### 11.1 证书来源总览

| 访问方式 | 证书来源 | 你的准备工作 |
|---------|---------|-------------|
| Cloudflare Tunnel | Cloudflare 边缘自动签发 | 无需配置 |
| 域名反代 / 智能混合路由 | Let's Encrypt（ACME 模块经 DNS API 验证自动申请与续签） | **自备 DNS API 凭据**（阿里云 AccessKey / CF API Token） |
| IPv6 直连 | 无（HTTP） | — |

### 11.2 Nginx 反代工作方式

Nginx 容器监听 HTTPS 端口（默认 8443），按域名将请求转发到对应服务。反代配置由系统**自动生成与维护**（安装/卸载模块时自动增删配置块），也可手动「重新生成 Nginx 配置」。

**实测已知疑点（待验证）**：生成的 `sites.conf` 中管理面板反代为 `proxy_pass http://127.0.0.1:8900`——nginx 容器运行在 `easyserver-proxy` 网络内，`127.0.0.1` 指向 **nginx 容器自身**而非核心引擎，疑似应为 `http://easyserver-core:8000`。若安装 nginx 后经域名访问面板出现 502，此处为已知嫌疑点，可通过「服务管理 → nginx → 日志」与 `/easyserver_data/modules/nginx/conf.d/sites.conf` 核对。

### 11.3 修改 HTTPS 端口

修改后系统自动重启 Nginx 容器（必须重启才能绑定新端口），并注意：云服务器安全组/防火墙放行新端口、路由器转发同步更新、域名反代访问改为新端口。443 被运营商/云厂商封锁时选 8443（默认，普遍不封）或 8442/9443。

---

## 12. 实测排错与已知行为差异

以下均为 QA 实测确认的行为，遇到对应现象时**先对照本表判断是否为已知行为**，再决定是否深入排查：

| # | 现象 | 级别 | 说明与应对 |
|---|------|------|-----------|
| 1 | nginx 未安装时 `POST /api/nginx/reload` 返回 500 | 已知行为 | 硬报错而非静默跳过；先安装 nginx 模块再 reload |
| 2 | nginx 未安装时 `POST /api/nginx/generate` 返回 200 且落盘配置 | 已知行为 | 生成≠生效，配置为预写；安装模块后启用 |
| 3 | 切 domain/hybrid 后未装过的模块出现在已安装列表（即使失败） | 缺陷 | `installed_modules` 先写后装、失败不回滚；到应用商店核对真实状态 |
| 4 | 无 Token 切 cloudflare_tunnel 后出现反复重启的 cloudflared 容器 | 缺陷 | crash loop 残留；先停掉该容器、配好 Token 再重新切换 |
| 5 | 域名 verify 的 tunnel_dns 项报 `[Errno 2] No such file or directory` | 缺陷 | 容器缺 DNS 工具；以 dns_provider/ssl 检查项为准 |
| 6 | verify 后主域名 `status` 变 `error` 无法恢复 | 缺陷 | verify 前先确认凭证已配置；避免对生产域名反复 verify |
| 7 | 端口检查空安装态列出全部模块端口 | 已知行为 | 清单为注册表全量，非已安装集合 |
| 8 | ipv6_direct 切换后 `BIND_ADDRESS='::'` 而非 `0.0.0.0` | 已知行为 | `::` 即监听所有接口（含 IPv6），非配置错误 |
| 9 | 切换访问方式页面长时间加载 | 正常现象 | 首次切换在安装并启动模块（含拉取镜像），耗时数分钟，勿关页面 |
| 10 | DNS 同步结果「跳过 N 条」 | 正常现象 | CNAME 冲突保护机制（见 7.4） |
| 11 | 容器内 healthcheck.sh 报 401 / exit 127 | 缺陷 | 脚本 API 检查项无认证头、依赖缺失的 `dig`；以 `/api/health` 与 compose ps 为准 |

---

## 13. FAQ 精选

**Q1：切换访问方式时页面一直转圈，是卡死了吗？**
正常现象。首次切换在安装并启动相关模块（含镜像拉取），可能持续数分钟，勿关闭或刷新页面，等待「已切换到 xxx」提示。

**Q2：为什么有的服务免端口、有的带端口？**
取决于服务的路由方式：Tunnel 中转免端口，域名反代带 HTTPS 端口（默认 8443）。「Tunnel 中转服务」卡片的「访问地址」列会自动给出正确格式。

**Q3：修改主域名后服务无法访问？**
修改主域名**不会**自动更新已有配置（防误操作设计）。需手动：Tunnel 已发布路由先取消再重新发布；域名反代点「重新生成 Nginx 配置」并重新同步 DNS；SSL 证书由 ACME 对新域名重新签发。

**Q4：Token 报无效或 Invalid request headers？**
八成混淆了两种 Token：API Token（`cfut_` 或 40 位十六进制，调 API 用）与 Tunnel Token（`eyJ` 开头，cloudflared 运行时凭证）。到 Cloudflare Dashboard 重建 API Token（`cfut_` 类）填入网络配置。

**Q5：SSL 证书申请失败？**
按序排查：DNS 凭证有 DNS 写入权限（阿里云需 `AliyunDNSFullAccess`）→ 域名已完成解析 → 填的是 API Token 而非 Tunnel Token → Let's Encrypt 每周每域名限 5 次，失败等 24 小时 → 「服务管理 → ACME → 日志」看详细错误。

**Q6：Tunnel 服务外网无法访问？**
按序：域名 DNS 是否托管在 Cloudflare → `docker ps | grep tunnel` 容器是否运行 → `docker logs easyserver-cloudflare-tunnel --tail=30` → `dig @8.8.8.8 子域名.域名 CNAME +short` 确认解析。

---

*上游完整文档：`docs/network-config.md`（五种方式详解、附录 A 凭据创建、附录 B 证书与端口、附录 C 术语表）。本文档行为差异部分以 QA 实测报告 R01/R02 为依据。*
