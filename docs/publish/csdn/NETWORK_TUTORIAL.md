<!--
EasyServer 推广稿 · CSDN 网络配置教程
- 改编母稿：docs/guides/NETWORK_CONFIG_GUIDE.md，事实基准：2026-09-04 WSL2 + Ubuntu 24.04 实测（零模块基线 + JWT 认证）
- 发布操作（图床替换/自查表/参数表）：见 docs/publish/PUBLISH_CHECKLIST.md
- 发布前：删除本注释块；确认所有 IMAGE_PLACEHOLDER-* 已替换为图床外链
-->

# 家庭服务器怎么被外网访问？域名反代 / IPv6 直连 / Cloudflare Tunnel / 混合路由 5 种方案实测对比与避坑

> **摘要**：装好家庭服务器只是第一步，"怎么让手机、外地办公室、甚至公网安全地访问到它"才是重头戏。本文基于 2026-09-04 WSL2 Ubuntu 24.04 实测，把开源项目 EasyServer（MIT）「网络配置」页面的 5 种访问方式逐个过一遍：选型对比、切换副作用、凭证准备、实测排错，并如实标注与预期不同的系统行为。五种方式各有适用场景，看完这篇就能对号入座。

<!-- CSDN 编辑器自带"自动生成目录"功能，发布时可直接使用；下方目录为手写备份 -->

## 目录

- 一、功能入口与 5 种模式总览
- 二、切换前必读：副作用预警
- 三、双源配置结构：config.yaml + .env
- 四、场景一：域名反代（domain）
- 五、场景二：IPv6 直连（ipv6_direct）
- 六、场景三：Cloudflare Tunnel
- 七、场景四：智能混合路由（hybrid）
- 八、场景五：自由配置（custom）
- 九、域名管理与 verify 的两个坑
- 十、SSL 证书与 HTTPS 端口
- 十一、实测排错速查表
- 十二、FAQ 精选
- 十三、写在最后

---

## 一、功能入口与 5 种模式总览

「网络配置」（管理面板侧边栏入口）是所有网络功能的统一入口：选择访问方式、域名与 DNS 管理、服务发布、SSL 证书。页面结构从上到下：网络状态总览 → 当前模式的管理区 → Tunnel 中转服务卡片 → 高级选项（折叠，含切换访问方式）→ 域名信息。

所有配置操作既可通过 Web 面板完成，也可通过 REST API（`/docs` 有完整 Swagger UI）操作。

![占位：网络配置页总览](IMAGE_PLACEHOLDER-network-overview)

**四种自动模式 + 一种自由模式对比**（含实测行为）：

| 模式 | `ACCESS_MODE` 值 | 前提条件 | 适用场景 |
|------|------|---------|------|
| 域名反代 | `domain` | 域名 + DNS 凭证 + 服务器公网可达 | 有域名，要大带宽直连（流量不经中转） |
| IPv6 直连 | `ipv6_direct` | 服务器有公网 IPv6 | 无域名、内网/信任网络使用 |
| Cloudflare Tunnel | `cloudflare_tunnel` | 域名托管 Cloudflare + API Token | 无公网 IP、443/80 被封（未备案）、免端口访问 |
| 智能混合路由 | `hybrid` | 域名 + DNS 凭证 + CF Tunnel Token | 大带宽服务与轻量服务并存，按服务分流 |
| 自由配置 | `custom` | 无 | 高级玩家自管网络模块；也可作"安全回退档" |

![占位：访问方式选择器](IMAGE_PLACEHOLDER-mode-selector)

**怎么选？一句话版本**：

- 有域名 + 国内大带宽需求 → **域名反代**
- 没域名但有公网 IPv6 → **IPv6 直连**
- 没公网 IP / 不想备案 / 想免端口 → **Cloudflare Tunnel**
- 既要大带宽又要免端口 → **混合路由**（大流量走反代，轻服务走 Tunnel）
- 想完全自己掌控 → **自由配置**

---

## 二、切换前必读：副作用预警（实测确认）

这一节是实测总结里最值钱的部分，切换访问方式不是"改个下拉框"那么简单：

1. **domain / hybrid 切换会真实安装并启动模块**：系统把未安装的 Nginx、ACME、DDNS（hybrid 另加 Cloudflare Tunnel）写入安装列表并执行 `docker compose up`，**触发镜像拉取**。首次切换可能持续数分钟，页面显示全屏提示「正在切换访问方式…请勿关闭页面」属正常现象，别当成卡死去刷新。
2. **失败会残留状态**：模块写入 `installed_modules` 发生在启动动作之前，若镜像拉取失败或启动出错，已写入的安装状态不会自动回滚——到应用商店核对模块真实状态。
3. **无 Token 切到 cloudflare_tunnel 会让 cloudflared 反复崩溃**：实测源码确认，未配置 Tunnel Token 时切换会直接启动无 token 的 cloudflared 容器（crash loop 残留）并触发镜像拉取。**务必先在凭证中配好 Token 再切换**。
4. **DNS 凭证为空时不要切 domain/hybrid**：DNS 同步与证书申请都会失败；hybrid 还会立即触发一次后台 DNS 同步。

> ❗ **避坑口诀**：先配凭证，再切模式。UI 上通过「高级选项 → 切换访问方式」按钮切换，与 API `POST /api/config/network {"access_mode":"..."}` 等价。

---

## 三、双源配置结构：config.yaml + .env

EasyServer 使用**双源分层配置**，理解这点能避开绝大多数凭证类问题：

| 文件 | 职责 | 内容举例 |
|------|------|---------|
| `data/config.yaml` | 核心运行配置：网络模式、域名、DNS 凭证、模块列表 | `access_mode`、`domain`、`dns_credentials` |
| `.env`（挂载卷内运行时副本） | 环境变量：路径、域名、凭证、模块专用配置 | `ACCESS_MODE`、`BIND_ADDRESS`、`ALI_KEY` |

**实测确认的联动行为**：

- 通过面板/API 切换访问模式时，系统自动把 `ACCESS_MODE`、`BIND_ADDRESS`、`HTTPS_PORT` 同步写入 `.env`。
- **凭证同步陷阱**：读取配置时会用 `.env` 里的凭证**覆盖** `config.yaml`。因此**手工修改 DNS 凭证时必须同时更新两处**，只改 `config.yaml` 会在下次读取时被回退覆盖。面板内修改凭证通常两处都会写；直接编辑文件时务必自己保持同步。

---

## 四、场景一：域名反代（domain）

**适用**：有自己的域名（任意 DNS 服务商），服务器公网可达，希望大带宽直连。访问地址带 HTTPS 端口（默认 8443）。

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

### 4.3 实测注意：nginx 未安装态的行为差异

| 操作 | 实测行为 | 结论 |
|------|---------|------|
| 生成 Nginx 配置（未装 nginx） | 返回成功，且实际落盘配置文件，**无任何"nginx 未安装"提示** | 生成≠安装；配置落盘属正常预写，真正生效需安装 nginx 模块 |
| 重载 Nginx（未装 nginx） | **返回 500「Nginx 重载失败」硬报错**，非静默跳过 | 未安装 nginx 时先安装模块再重载；看到此 500 先检查模块是否已装 |

---

## 五、场景二：IPv6 直连（ipv6_direct）

**适用**：无域名但服务器有公网 IPv6（云服务器需开通 IPv6），内网或信任网络使用。无需 DNS、无需证书，但**无 HTTPS 加密**。

**启用步骤**：「高级选项」→「切换到 IPv6 直连」。系统自动停止 Nginx / ACME / Tunnel 等代理模块，把服务监听地址切到所有接口，并重启已安装模块；页面展示各服务访问链接 `http://[IPv6地址]:端口`，可直接复制。

**实测行为细节**：切换后 `.env` 中 `BIND_ADDRESS='::'`（IPv6 全零地址），效果上监听所有接口（含 IPv6）——**不是 `0.0.0.0`**，别误判为配置错误：

```bash
docker exec easyserver-core grep -E '^(ACCESS_MODE|BIND_ADDRESS)' /app/.env
# 实测输出：ACCESS_MODE='ipv6_direct'  BIND_ADDRESS='::'
```

---

## 六、场景三：Cloudflare Tunnel

**适用**：无公网 IP、443/80 被封（未备案）、追求免端口访问。服务器主动向 Cloudflare 建立出站隧道，用户走 Cloudflare 标准 443 端口，自带 SSL，访问地址不带端口号。

### 6.1 前提（自备凭据）

1. **域名已托管到 Cloudflare**（NS 记录指向 Cloudflare）
2. **Cloudflare API Token**：需权限 `Account · Cloudflare Tunnel · Edit` + `Zone · DNS · Edit`（Dashboard → My Profile → API Tokens 创建，生成后仅显示一次，立即保存）

### 6.2 接入与发布

1. 「网络配置」→ Cloudflare Tunnel 卡片 →「一键接入」
2. 粘贴 API Token →「验证 Token」→ 看到「Token 有效」
3. 点「一键接入」：弹窗逐步显示创建/复用隧道 → 启动 cloudflare-tunnel 容器 → 检查域名托管状态
4. 「服务发布」卡片 →「可发布」页签 → 点「发布」：自动添加隧道路由（子域名 → 本地端口）并**自动创建 CNAME 记录**，发布后 `https://子域名.你的域名` 免端口访问；「取消发布」会同时删除路由与 CNAME

![占位：Tunnel 中转服务卡片](IMAGE_PLACEHOLDER-tunnel-card)

### 6.3 实测预警

- **务必先配好 Token 再切换到本模式**（原因见第二节第 3 条，无 Token 切换 = crash loop 残留）。
- 隧道要求域名的权威 DNS 必须托管在 Cloudflare，否则 `cfargotunnel.com` 的 CNAME 无法工作。主域名托管在别处时，可添加一个 Cloudflare 托管的域名专用于 Tunnel（见第九节多域名配置）。

---

## 七、场景四：智能混合路由（hybrid）

**适用**：既有大带宽服务（Jellyfin/Frigate/Nextcloud 等），又有轻量服务（笔记/监控面板），想按服务分流——大带宽走域名反代（带宽直达），轻量走 Tunnel 中转（免端口）。

两种路由方式**按服务并存**，同一子域名同一时刻只走一条路：

| 路由方式 | 流量路径 | 地址格式 |
|---------|---------|---------|
| 域名反代 | DNS AAAA → 服务器 IPv6 → Nginx SSL → 服务 | `https://子域名.域名:8443`（带端口） |
| Tunnel 中转 | DNS CNAME → Cloudflare 边缘 → Tunnel → 服务 | `https://子域名.域名`（免端口） |

**配置步骤**：

1. 先完成前置：域名信息已填、域名反代凭证已配置、Cloudflare Tunnel 已接入
2. 「高级选项」→ 点「智能混合路由」→ 确认切换。**首次切换会自动安装并启动 Nginx、ACME、DDNS、Cloudflare Tunnel 全套模块**，耗时数分钟，勿关页面
3. 在「Tunnel 中转服务」卡片为每个服务点「切换为 Tunnel 中转」或「切换为 域名反代」；切换后系统自动维护 DNS，无需手动操作
4. 可选：点「智能推荐」一键分流——实测推荐策略为 Frigate、Nextcloud、Jellyfin、FileBrowser、Calibre-Web 走域名反代；NoteDiscovery、Joplin、Uptime Kuma 走 Tunnel 中转

> ⚠️ **注意**：hybrid 切换 = domain 的全部动作 + 立即触发一次后台 DNS 同步 + 启动 cloudflare-tunnel，它是副作用最大的切换动作，DNS 凭证或 Tunnel Token 任一缺失时都不要执行。

**「跳过 N 条」提示不是错误**：DNS 同步结果出现「跳过」表示该子域名已存在 CNAME（服务正通过 Tunnel 发布），系统主动跳过以避免同域 CNAME 与 A/AAAA 冲突——这是保护机制。想让该服务改回域名反代：先在卡片中「切换为 域名反代」，再重新同步。

---

## 八、场景五：自由配置（custom）

面向高级用户：**系统不自动管理任何网络模块**，由你自行在应用商店安装配置 Nginx、DDNS、ACME、Tunnel 等。

实测切换行为：切换成功后 `BIND_ADDRESS` 还原为 `'127.0.0.1'`，**无任何模块被安装或启动**——五种模式中唯一零副作用的切换，可作为误切换后的「安全回退档」。页面提供已装网络模块状态列表、启动/停止按钮与「重新生成 Nginx 配置」手动入口。

---

## 九、域名管理与 verify 的两个坑

**增查删实测行为**：添加域名时缺 `dns_provider` 会 422 明确报错；`purpose` 非法返回 400（合法值：`nginx` 域名反代 / `tunnel` Tunnel 中转 / `both` 两者皆可）；**主域名删除被拒**（合理保护）。

**verify 的两个实测坑**（重点）：

1. **tunnel_dns 检查项报 `[Errno 2] No such file or directory`**：容器内缺少 DNS 工具，该项失败**不代表域名真有问题**，先看 dns_provider 与 ssl 两项结果。
2. **verify 有不可逆副作用**：实测对主域名执行 verify 后，其 `status` 被从 `active` 改为 `error` 且无单独恢复途径。建议 verify 前确认凭证已配好，避免对生产域名反复 verify。

**多域名配置**：Tunnel 要求域名托管在 Cloudflare，主域名在别处时，可添加一个 Cloudflare 托管域名专用于 Tunnel：「域名管理」→「添加域名」→ 填域名、选 Cloudflare、用途选「Tunnel 中转」。多域名时 Tunnel 服务卡片顶部出现「目标域名」下拉选择器；单域名则自动使用。

> 💡 **提示**（上游实测结论）：并非所有免费域名后缀都支持 NS 迁移到 Cloudflare，注册前先确认可改 NS。

---

## 十、SSL 证书与 HTTPS 端口

**证书来源总览**：

| 访问方式 | 证书来源 | 你的准备工作 |
|---------|---------|-------------|
| Cloudflare Tunnel | Cloudflare 边缘自动签发 | 无需配置 |
| 域名反代 / 混合路由 | Let's Encrypt（ACME 模块经 DNS API 验证自动申请与续签） | **自备 DNS API 凭据**（阿里云 AccessKey / CF API Token） |
| IPv6 直连 | 无（HTTP） | — |

**Nginx 反代工作方式**：Nginx 容器监听 HTTPS 端口（默认 8443），按域名将请求转发到对应服务。反代配置由系统**自动生成与维护**（安装/卸载模块时自动增删配置块），也可手动「重新生成 Nginx 配置」。

**修改 HTTPS 端口**：修改后系统自动重启 Nginx 容器，注意：云服务器安全组/防火墙放行新端口、路由器转发同步更新。443 被运营商/云厂商封锁时选 8443（默认，普遍不封）或 8442/9443。

---

## 十一、实测排错速查表

遇到对应现象时**先对照本表判断是否为已知行为**，再决定是否深入排查：

| # | 现象 | 级别 | 应对 |
|---|------|------|------|
| 1 | nginx 未安装时重载返回 500 | 已知行为 | 先安装 nginx 模块再 reload |
| 2 | nginx 未安装时生成配置返回成功且落盘 | 已知行为 | 生成≠生效，配置为预写 |
| 3 | 切 domain/hybrid 后未装过的模块出现在已安装列表 | 缺陷 | 写入先于安装、失败不回滚；到应用商店核对真实状态 |
| 4 | 无 Token 切 cloudflare_tunnel 后出现反复重启的 cloudflared 容器 | 缺陷 | 先停掉该容器、配好 Token 再重新切换 |
| 5 | 域名 verify 的 tunnel_dns 项报文件不存在 | 缺陷 | 容器缺 DNS 工具；以 dns_provider/ssl 检查项为准 |
| 6 | verify 后主域名状态变 error 无法恢复 | 缺陷 | verify 前先确认凭证已配置 |
| 7 | 端口检查空安装态列出全部模块端口 | 已知行为 | 清单为注册表全量，非已安装集合 |
| 8 | ipv6_direct 切换后 `BIND_ADDRESS='::'` 而非 `0.0.0.0` | 已知行为 | `::` 即监听所有接口（含 IPv6），非配置错误 |
| 9 | 切换访问方式页面长时间加载 | 正常现象 | 首次切换在安装并启动模块（含拉取镜像），勿关页面 |
| 10 | DNS 同步结果「跳过 N 条」 | 正常现象 | CNAME 冲突保护机制 |
| 11 | 容器内 healthcheck.sh 报 401 / exit 127 | 缺陷 | 脚本缺陷；以 `/api/health` 与 compose ps 的 healthy 状态为准 |

---

## 十二、FAQ 精选

**Q1：切换访问方式时页面一直转圈，是卡死了吗？**
正常现象。首次切换在安装并启动相关模块（含镜像拉取），可能持续数分钟，勿关闭或刷新页面，等待「已切换到 xxx」提示。

**Q2：为什么有的服务免端口、有的带端口？**
取决于服务的路由方式：Tunnel 中转免端口，域名反代带 HTTPS 端口（默认 8443）。「Tunnel 中转服务」卡片的「访问地址」列会自动给出正确格式。

**Q3：修改主域名后服务无法访问？**
修改主域名**不会**自动更新已有配置（防误操作设计）。需手动：Tunnel 已发布路由先取消再重新发布；域名反代点「重新生成 Nginx 配置」并重新同步 DNS；SSL 证书由 ACME 对新域名重新签发。

**Q4：Token 报无效或 Invalid request headers？**
八成混淆了两种 Token：API Token（调 API 用）与 Tunnel Token（`eyJ` 开头，cloudflared 运行时凭证）。到 Cloudflare Dashboard 重建 API Token 填入网络配置。

**Q5：SSL 证书申请失败？**
按序排查：DNS 凭证有 DNS 写入权限（阿里云需 `AliyunDNSFullAccess`）→ 域名已完成解析 → 填的是 API Token 而非 Tunnel Token → Let's Encrypt 每周每域名限 5 次，失败等 24 小时 → 「服务管理 → ACME → 日志」看详细错误。

**Q6：Tunnel 服务外网无法访问？**
按序：域名 DNS 是否托管在 Cloudflare → `docker ps | grep tunnel` 容器是否运行 → `docker logs easyserver-cloudflare-tunnel --tail=30` → `dig @8.8.8.8 子域名.域名 CNAME +short` 确认解析。

---

## 十三、写在最后

五种访问方式没有绝对优劣，只有场景匹配：**家庭宽带 + 有域名选反代，没公网 IP 选 Tunnel，嫌麻烦直接上混合路由让系统帮你分流**。唯一要牢记的是那句避坑口诀：**先配凭证，再切模式**。

安装部署部分没看的同学可以移步本账号上一篇：《Windows 上自建家庭服务器：WSL2 + Docker 从零部署开源项目 EasyServer，全流程保姆级教程》。

- 仓库地址：[https://github.com/liangfei-sun/EasyServer](https://github.com/liangfei-sun/EasyServer)（开源项目 EasyServer，MIT 协议）
- 本文基于 2026-09-04 WSL2 Ubuntu 24.04 零模块基线 + JWT 认证环境实测；行为差异部分以 QA 实测为依据，环境不同可能有差异。

**互动一下**：你的家庭服务器走的哪条线路？IPv6 直连的延迟表现如何？Tunnel 中转的稳定性你打几分？评论区聊聊你的选型理由；文中 11 条实测排错如果帮到你，**点赞 + 收藏**就是最大的支持。

---

> **标签建议**：`docker` `linux` `运维` `nginx`（可加：`cloudflare` `家庭服务器`）
