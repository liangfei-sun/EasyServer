# ACME SSL 证书 · 运行指南

> 基于 2026-09-04 WSL Ubuntu 24.04 实测（QA 报告 R13）。实测结论与上游描述不一致处，以实测为准并已标注。
> **凭据要求：本模块需自备 DNS API 凭据（阿里云 AccessKey 或 Cloudflare Token）与自有域名。因真实签发涉及 Let's Encrypt 限额风险，本指南验证到启动层（凭据校验/降级断言），未执行真实签发。**
> **第二预警：实测镜像 `neilpang/acme.sh:v3.0.9` 拉取被拒（denied，PULL_BLOCKED）**，当前网络环境下即便凭据齐备也无法完成安装，见 3.2 与 FAQ。

## 1. 概述

ACME 模块基于 acme.sh 自动申请与续签 Let's Encrypt SSL 证书，采用 DNS 验证方式（支持泛域名 `*.你的域名`），证书每 60 天自动续签。**CLI 型模块，无 Web UI、无端口**，产出物为证书文件，供 Nginx 模块反代时自动引用。

| 项 | 值 |
|------|------|
| 镜像 | `neilpang/acme.sh:v3.0.9`（**实测拉取被拒，PULL_BLOCKED**） |
| 分类 | infra |
| 网络模式 | `network_mode: host`（CLI 型无需端口映射） |
| 端口 | 无（CLI 型） |
| 资源限制 | 内存 64m / CPU 0.25 |
| 容器名 | 引擎按模块命名（实测未安装，未确认具体名） |
| 内置 healthcheck | 无（module.yaml url 为空） |

## 2. 前置条件

- 核心引擎运行中；soft_depends_on: nginx（证书供其引用，非硬依赖）
- **自备 DNS API 凭据**（二选一，由 `ACME_DNS_PROVIDER` 决定）：
  - **阿里云**：登录 RAM 控制台创建子用户，授权 `AliyunDNSFullAccess`，生成 AccessKey ID 与 Secret
  - **Cloudflare**：Dashboard → My Profile → API Tokens → Create Custom Token，权限 `Zone > DNS > Edit`，Zone Resources 选定域名
- **自有域名**：DNS 已托管在对应服务商；`ACME_DOMAIN` 填主域名（如 `example.com`，非子域名）
- **镜像可用性（实测预警）**：`neilpang/acme.sh:v3.0.9` 在实测环境（Docker Hub mirror 链路）拉取被拒——错误为 `error from registry: denied`（非网络超时，疑似 Docker Hub 对该镜像/tag 的访问限制）。主池预拉取与手动补拉均失败

## 3. 安装

### 3.1 配置字段

| 字段 | 说明 | 默认值 | 必填 |
|------|------|--------|:---:|
| `ACME_DNS_PROVIDER` | DNS 提供商（aliyun / cloudflare） | aliyun | 是 |
| `ACME_ALI_KEY` | 阿里云 AccessKey ID | 空 | 选 aliyun 时填写 |
| `ACME_ALI_SECRET` | 阿里云 AccessKey Secret | 空 | 选 aliyun 时填写 |
| `ACME_CF_TOKEN` | Cloudflare API Token | 空 | 选 cloudflare 时填写 |
| `ACME_DOMAIN` | 主域名 | 空 | 是 |

> 凭据类字段（key/secret/token）在面板表单中按 `show_when` 联动显示——选择 DNS 提供商后仅展示对应字段。

### 3.2 安装路径与实测行为（凭据校验闭环有效 + 镜像阻塞）

**无凭据时（实测）**：引擎前置校验闭环有效——`POST /api/modules/install {"module_id":"acme"}` 返回 **400 `{"detail":"字段「DNS 提供商」为必填项"}`**，不会像 filebrowser/ddns-go 那样产生半安装状态。⚠️ 错误文案为表单式中文字符串，未指明合法取值集合（缺陷 K，P3）。

**凭据齐备时（降级推断）**：安装仍会被镜像拉取阻塞——实测 `neilpang/acme.sh:v3.0.9` PULL_BLOCKED（主池 + 手动补拉均 `denied`）。当前网络环境下面板安装 acme 无法完成，可尝试：

```bash
# 手动补拉尝试（实测失败，仅作记录）
docker pull neilpang/acme.sh:v3.0.9
# 实测输出：Error response from daemon: error from registry: denied
```

**`dns-credentials.env` 硬依赖（缺陷 L，P2）**：compose 中 `env_file: ./dns-credentials.env` 为硬引用——实测无该文件时**连 `docker compose config` 语法校验都失败**（`env file ... not found`），`up` 必败。该文件由引擎在安装时生成（含凭据），但"仅浏览/校验配置"的合法场景被此硬依赖阻断。compose v2.24+ 可用 `required: false` 修复。

## 4. 启动与验证

本指南验证到启动层（凭据校验与降级断言），以下为实测验证项（示例中 API 端口 `8901` 为 QA 实测环境经 `docker-compose.override.yml` 修改后的端口，默认安装请使用 `8900`；compose 命令中 `<PROJECT_ROOT>` 默认安装为容器内路径映射 `/easyserver_data`，按安装指南第 3 步（3b）自定义 PROJECT_ROOT 的用户请替换）：

```bash
# 1. 校验接口可达（实测 200）
curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer <你的管理Token>" \
  http://localhost:8901/api/modules/acme/validate
# 实测输出：200

# 2. 无凭据安装负面断言（实测 400，无半安装态）
curl -s -X POST -H "Authorization: Bearer <你的管理Token>" -H 'Content-Type: application/json' \
  -d '{"module_id":"acme","config":{}}' http://localhost:8901/api/modules/install
# 实测输出：{"detail":"字段「DNS 提供商」为必填项"}   (HTTP 400)

# 3. compose 语法断言（无凭据文件时失败——缺陷 L 实证）
sg docker -c "docker compose -f <PROJECT_ROOT>/modules/acme/docker-compose.yml config"
# 实测输出：env file /easyserver_data/modules/acme/dns-credentials.env not found
```

**凭据齐备后的验证路径（未实测，按上游文档描述）**：安装成功后容器执行 acme.sh 签发流程；证书产物落盘 `<DATA_DIR>/acme/data/`；日志可见 Let's Encrypt 验证与签发记录。真实签发涉及限额风险，请自行评估后操作。

## 5. 访问方式

- **无 Web UI、无端口**（`access.port: 0`）：本模块不提供任何服务端点
- **产物访问**：证书文件位于 `<DATA_DIR>/acme/data/`，**Nginx 模块自动引用**（module.yaml usage）——用户视角的"使用方式"即在域名反代模式下配置的 `https://你的域名:8443` 自动获得有效证书
- 状态查看：`docker logs` 观察签发/续签日志

## 6. 数据与备份

| 路径 | 内容 |
|------|------|
| `<DATA_DIR>/acme/data/` | acme.sh 主目录：已签发证书、账户配置、续签状态 |

备份方法：打包该目录即可。证书可随时重新签发（受 LE 限额约束），故备份优先级中等；建议连同账户配置备份以便平滑迁移。

## 7. 卸载

> **实测未覆盖卸载路径**（QA 降级测试未安装容器，无 uninstall 实测数据）。以下为按引擎统一语义与 compose 结构的推断，标注为非实测：

- 预期：面板卸载删除容器与镜像（引擎存在卸载自动删镜像的普遍行为——缺陷 D 模式，见 nginx 等篇实测）；`dns-credentials.env`（含凭据）与 `<DATA_DIR>/acme/data/`（证书目录）的处置未实测，卸载前建议先备份证书目录
- 已实测的参照：无凭据时引擎 400 拒绝安装（无半安装态），`GET /api/services` 返回空

## 8. FAQ

**Q：证书申请失败怎么办？**
检查 DNS 服务商 API 凭据是否正确：阿里云需确认 RAM 子用户有 DNS 管理权限（`AliyunDNSFullAccess`）；Cloudflare 需确认 Token 有 `Zone DNS Edit` 权限（module.yaml faq）。

**Q：证书到期后会自动续签吗？**
会。ACME 模块自动续签（约 60 天周期），只需保持容器运行和凭证有效（module.yaml faq）。

**Q：支持切换 DNS 服务商吗？**
可以在全局设置中切换，切换后需重新填写对应服务商的 API 凭证（module.yaml faq）。

**Q：镜像拉取失败（denied）怎么办？**
实测已知问题：`neilpang/acme.sh:v3.0.9` 拉取被拒（非网络超时）。可尝试改用其他可用 tag 或配置可用镜像源；QA 报告建议文档注明备用镜像源。

**Q：compose config 报 dns-credentials.env not found？**
凭据文件的硬依赖所致（缺陷 L）：凭据由面板安装流程生成；手动排查时确认模块目录下是否存在该文件。无凭据时 `config`/`validate` 均失败属实测确认的行为。

## 9. 实测排错

实测环境：WSL2 Ubuntu 24.04，无任何 DNS 凭据（降级前提）；禁触边界：不创建 dns-credentials.env、不执行真实签发。关键证据摘录（QA 报告 R13）：

```
# 镜像状态（主池与手动补拉均失败，非网络超时）
PULL_BLOCKED — error from registry: denied（疑似 docker hub 对该镜像/tag 的访问限制）
# 校验接口
$ curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $TOKEN" \
    http://localhost:8901/api/modules/acme/validate
200
# compose 语法断言（env_file 硬依赖实证）
$ sg docker -c "docker compose -f /easyserver_data/modules/acme/docker-compose.yml config"
... env file /easyserver_data/modules/acme/dns-credentials.env not found: stat ...: no such file or directory
# 无凭据 install 负面断言
$ curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d '{"module_id":"acme","config":{}}' http://localhost:8901/api/modules/install
{"detail":"字段「DNS 提供商」为必填项"}   (HTTP 400)
# 空态确认
$ curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8901/api/services
{"services":[]}
```
