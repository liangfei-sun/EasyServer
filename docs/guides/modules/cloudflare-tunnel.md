# Cloudflare Tunnel · 运行指南

> 基于 2026-09-04 WSL Ubuntu 24.04 实测（QA 报告 R14）。实测结论与上游描述不一致处，以实测为准并已标注。
> **凭据要求：本模块需自备 Cloudflare Tunnel Token，且域名必须托管在 Cloudflare。因真实建链会创建/发布生产隧道，本指南验证到启动层（凭据校验/空态断言），未执行隧道真实建链。**
> 实测正面样本：凭据前置校验闭环有效（无 token → 400 拒绝，无半安装态、无 crash loop 容器残留）。

## 1. 概述

Cloudflare Tunnel 通过 cloudflared 出站连接将本地服务安全发布到公网：无需公网 IP、无需开放入站端口、自带 SSL 与 DDoS 防护、隐藏服务器真实 IP。**CLI 型模块，无 Web UI、无端口**；配合管理面板「内网穿透」页面可实现一键接入与一键发布。

| 项 | 值 |
|------|------|
| 镜像 | `cloudflare/cloudflared:2024.12.1`（实测池拉取就绪，elapsed=140s） |
| 分类 | network |
| 网络模式 | `network_mode: host`（出站建链，无需端口映射） |
| 端口 | 无（CLI 型） |
| 资源限制 | 内存 128m / CPU 0.5 |
| 容器名 | `easyserver-cloudflare-tunnel` |
| 内置 healthcheck | 无（module.yaml url 为空）；隧道状态以 Cloudflare Dashboard / 面板接口为准 |

## 2. 前置条件

- 核心引擎运行中；无依赖模块
- **自备 Cloudflare 凭据**（两类，用途不同）：
  - **Tunnel Token**：模块安装所需——登录 [Cloudflare Zero Trust](https://one.dash.cloudflare.com/) → Networks → Tunnels → 创建隧道 → 复制 Token（module.yaml usage 手动步骤；推荐改用面板一键接入自动完成）
  - **Cloudflare API Token**：面板一键接入所需——在「内网穿透」页面粘贴后系统自动创建隧道并启动本模块
- **域名托管在 Cloudflare**：未托管的域名无法使用 Tunnel（module.yaml usage 注意事项）
- 镜像可用性：实测 `cloudflare/cloudflared:2024.12.1` 可正常拉取（无 denied 问题）

## 3. 安装

### 3.1 配置字段

| 字段 | 说明 | 默认值 | 必填 |
|------|------|--------|:---:|
| `CF_TUNNEL_TOKEN` | Cloudflare 隧道令牌 | 空 | 是 |

> 单字段配置：token 直接注入 cloudflared 启动命令（`tunnel --no-autoupdate run --token ${CF_TUNNEL_TOKEN}`）与 `TUNNEL_TOKEN` 环境变量。隧道路由/域名映射不占本模块配置项，在 Cloudflare Dashboard 或面板「发布」中维护。

### 3.2 安装路径与实测行为（凭据校验闭环有效）

**无 token 时（实测负面断言）**：`POST /api/modules/install {"module_id":"cloudflare-tunnel"}` 返回 **400 `{"detail":"字段「Tunnel Token」为必填项"}`**——引擎前置校验有效，**不会**产生"启动无 token 的 cloudflared 反复崩溃重启"的半安装态。⚠️ 补充澄清（QA 走读结论）：网络文档排错章节担心的 crash loop 场景**仅存在于 configure_network 的 cloudflare_tunnel 模式路径**，模块 install 路径有校验保护，两者勿混淆。

**有 token 时（推荐路径）**：面板「内网穿透」页面一键接入（粘贴 API Token 自动创建隧道并启动模块），或手动安装（粘贴 Tunnel Token 后 `POST /api/modules/install`）。两者均未在 QA 中执行真实建链（禁触）。

```bash
# 校验接口可达（实测 200）
curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer <你的管理Token>" \
  http://localhost:8901/api/modules/cloudflare-tunnel/validate
# 实测输出：200

# 未安装空态（实测语义正确）
curl -s -H "Authorization: Bearer <你的管理Token>" http://localhost:8901/api/services
# 实测输出：{"services":[]}（status none）
```

## 4. 启动与验证

本指南验证到启动层；真实建链后的验证方法按上游文档整理（标注为非实测）：

```bash
# 容器状态（有 token 启动后）
sudo docker ps --filter name=easyserver-cloudflare-tunnel

# 隧道建链日志（非实测，cloudflared 通用判据）
sudo docker logs easyserver-cloudflare-tunnel
# 预期关键行：Registered tunnel connection（多条 conn= 注册成功即建链完成）

# 公网验证（非实测）：映射生效后
curl -s -o /dev/null -w '%{http_code}' https://子域名.你的域名
# 预期：200（或后端服务的正常响应码）
```

- 建链成功后每次修改域名映射**无需重启隧道，自动生效**（module.yaml usage）
- 隧道状态也可在 Cloudflare Zero Trust → Networks → Tunnels 中查看（connector 状态 healthy）

## 5. 访问方式

- **本模块无 Web UI、无端口**（`access.port: 0`）：它是"访问通道"本身，不是被访问的服务
- **发布服务**：面板服务列表点击「发布」自动配置路由与 DNS 记录，之后经 `https://子域名.你的域名` 免端口访问对应服务（module.yaml usage 一键接入流程）
- **手动映射示例**（module.yaml usage）：在 Cloudflare Dashboard 隧道配置中添加，如 `notes.example.com → http://localhost:8000`、`media.example.com → http://localhost:8096`
- **与 nginx 反代共存**：可以，将访问模式设为「混合模式」即可同时启用两种方式（module.yaml faq）

## 6. 数据与备份

| 路径 | 内容 |
|------|------|
| （无本地数据目录） | token/隧道配置均在 Cloudflare 侧，容器本身无状态 |

备份方法：无需本地备份；**Tunnel Token 与 API Token 按敏感凭据妥善保管**（勿入版本库/截图）。重建隧道 = 在 Cloudflare 重新创建并替换 token。

## 7. 卸载

> **实测未覆盖卸载路径**（QA 降级测试未安装容器）。以下为按引擎统一语义与 compose 结构的推断，标注为非实测：

- 预期：面板卸载删除容器与镜像（引擎存在卸载自动删镜像的普遍行为——缺陷 D 模式，见 nginx 等篇实测）；实测确认本地镜像 `cloudflare/cloudflared:2024.12.1` 在未安装状态下保留
- **Cloudflare 侧清理**：卸载模块不会删除 Cloudflare 上的隧道与 DNS 记录——如需彻底下线，请在 Zero Trust 控制台删除隧道，或在面板「发布」管理中取消发布
- 卸载不影响已发布域名的 DNS（需手动处理），注意避免解析悬空

## 8. FAQ

**Q：隧道连接失败？**
检查 Tunnel Token 是否正确，确认域名已托管在 Cloudflare（module.yaml faq）。实测补充：token 为空时引擎会在安装阶段直接 400 拒绝，不会进入 crash loop——若容器反复重启，多为 token 无效/被撤销，重新生成后重装。

**Q：访问显示 502 错误？**
检查映射的服务地址和端口是否正确，确认后端服务已启动（module.yaml faq）。如映射本机服务，host 模式下用 `http://localhost:<端口>`。

**Q：如何免端口访问？**
在管理面板「内网穿透」页面一键接入并发布服务，即可通过 `https://子域名.域名` 访问（module.yaml faq）。

**Q：可以同时使用域名反代和 Tunnel 吗？**
可以，将访问模式设为「混合模式」即可同时启用两种方式（module.yaml faq）。Tunnel 自带 SSL，无需额外配置 ACME 证书（module.yaml usage）。

**Q：WSL2 环境下能用吗？**
实测仅验证到启动层（凭据校验/空态）。cloudflared 为纯出站连接（host 模式无端口绑定），理论上不受 WSL2 mirrored 端口占用影响；真实建链请按第 4 节非实测方法自行验证。

## 9. 实测排错

实测环境：WSL2 Ubuntu 24.04，无 Cloudflare 凭据（降级前提）；禁触边界：不调用 /api/cloudflare/setup|publish|unpublish。关键证据摘录（QA 报告 R14）：

```
# 镜像就绪（池 00:16:10–00:18:30，elapsed=140s）
digest sha256:fc6afe4a5dcf2a801b39fcd538c9d5d4d53ea229fe9976584835bdb8c185ed5d
# 校验接口
$ curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" \
    http://localhost:8901/api/modules/cloudflare-tunnel/validate
200
# 无 token install 负面断言（400，无半安装态）
$ curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"module_id":"cloudflare-tunnel","config":{}}' http://localhost:8901/api/modules/install
{"detail":"字段「Tunnel Token」为必填项"}   (HTTP 400)
# 空态确认
$ curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8901/api/services
{"services":[]}
```
