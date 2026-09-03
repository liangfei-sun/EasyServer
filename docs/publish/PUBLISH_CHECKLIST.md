<!--
EasyServer 推广物料 · 发布操作清单（本文件为内部操作手册，不对外发布）
- 覆盖产物：docs/publish/csdn/INSTALL_TUTORIAL.md、csdn/NETWORK_TUTORIAL.md、zhihu/ANSWER_DRAFT.md、juejin/QUICKSTART.md
- 事实基准：2026-09-04 WSL2 Ubuntu 24.04 实测（docs/guides/ 母稿 2 篇 + 模块篇 13 篇 + QA test-matrix）
-->

# 发布操作清单（逐平台）

## 0. 目的与边界

- 本清单是 `docs/publish/` 下 4 篇平台适配稿的**发布操作手册**：发布入口、账号要求、标题/摘要/标签/封面参数、配图外链流程、发布后运营。
- **不代发布**：全部操作由持有对应平台账号的人员人工执行。
- 事实基准统一为 2026-09-04 WSL2 + Ubuntu 24.04 完整实测；稿件数据均出自 `docs/guides/INSTALL_GUIDE.md`、`docs/guides/NETWORK_CONFIG_GUIDE.md`、`docs/guides/modules/`（13 篇）与 QA 缺陷总账，**禁止夸大或虚构**。
- 表述约定：首次提及项目用中性表述「**开源项目 EasyServer（MIT）**」，仓库链接统一为 `https://github.com/liangfei-sun/EasyServer`。

## 1. 产物与平台对照

| 文件 | 平台 | 形式定位 | 发布方式 |
|------|------|---------|---------|
| `csdn/INSTALL_TUTORIAL.md` | CSDN 博客 | 安装教程长文（系列第一篇） | 发布文章 |
| `csdn/NETWORK_TUTORIAL.md` | CSDN 博客 | 网络配置教程长文（系列第二篇） | 发布文章 |
| `zhihu/ANSWER_DRAFT.md` | 知乎 | 经验帖/回答体 | 优先「回答问题」，亦可发文章 |
| `juejin/QUICKSTART.md` | 掘金 | 技术向快速上手 | 发布文章 |
| `PUBLISH_CHECKLIST.md`（本文件） | — | 内部手册 | 不发布 |

## 2. 发布前自查表（每篇逐项打勾后再发布）

- [ ] **注释已删**：文首 HTML 注释块（编辑备注）不随稿发布
- [ ] **占位图已替换**：所有 `IMAGE_PLACEHOLDER-*` 已替换为图床外链（对照第 4 节），替换后逐张点开自检（防盗链 403 是常见翻车点）
- [ ] **无凭据泄漏**：全文无 AccessKey/Secret/API Token/Tunnel Token 明文，示例一律为 `<你的管理密码>` 类占位符
- [ ] **无测试密码**：未包含 QA 测试过程中的任何真实凭据；不含任何系统默认口令的具体值
- [ ] **数据与实测一致**：关键数字（首次构建约 31 分钟、镜像约 538 MB、Nextcloud 初始化约 40s、mirror 限速 25-40 KB/s、大镜像拉取约 600s 量级超时、13 模块/5 分类、port-check 列 10 个注册模块端口、JWT 约 7 天等）与母稿/实测报告一致，无夸大
- [ ] **仓库链接正确**：`https://github.com/liangfei-sun/EasyServer` 可公开访问
- [ ] **表述中性**：项目以「开源项目 EasyServer（MIT）」指代，无「最强/完美/秒杀」类夸大用语；缺陷如实表述为「实测已知问题」
- [ ] **平台方言合规**：CSDN（自动生成目录、blockquote 提示框）、知乎（无 `[TOC]`、正文已列表化少表格）、掘金（标准 GFM、代码块语言标注齐全）
- [ ] **合规项**：原创声明按平台规则勾选；若他平台已首发，按平台要求注明首发来源

## 3. 逐平台发布操作

### 3.1 CSDN（2 篇）

**发布入口**：`blog.csdn.net` 登录 → 右上角「创作」→「写博客」（或创作中心 → 「发布文章」）；选择 **Markdown 编辑器**。

**账号要求**：CSDN 账号；建议完成创作者认证后再发（流量分发与合集功能更完整）。

**操作步骤**：粘贴正文 → 删除文首注释块 → 替换图片占位符 → 填写下方参数 → 用编辑器「自动生成目录」替换手写目录 → 预览自查 → 发布。

**参数表**：

| 参数 | INSTALL_TUTORIAL | NETWORK_TUTORIAL |
|------|------------------|------------------|
| 标题 | Windows 上自建家庭服务器：WSL2 + Docker 从零部署开源项目 EasyServer，全流程保姆级教程（附踩坑实录） | 家庭服务器怎么被外网访问？域名反代 / IPv6 直连 / Cloudflare Tunnel / 混合路由 5 种方案实测对比与避坑 |
| 摘要 | 用文首「摘要」引用块内容 | 用文首「摘要」引用块内容 |
| 标签 | `docker` `linux` `运维` `nginx` | `docker` `linux` `运维` `nginx`（可加 `cloudflare`） |
| 分类建议 | 云计算 / 运维类目下就近选择 | 同左 |
| 封面 | 上传横版截图（建议用管理面板或构建完成图，编辑器可选单图/三图样式） | 建议用网络配置页总览图 |
| 可见范围 | 所有人可见 | 所有人可见 |

**方言注意**：
- CSDN 编辑器自带「自动生成目录」，优先用编辑器功能；手写锚点目录在 CSDN 渲染下不保证跳转。
- 提示框用 CSDN 支持的 blockquote 写法：`> 💡 **提示**：`、`> ⚠️ **注意**：`、`> ❗ **避坑**：`（稿件已按此写好）。

### 3.2 知乎（1 篇）

**发布入口（二选一，推荐 A）**：
- A：知乎搜索/创建问题「在 WSL 里跑一套开源自建家庭服务器是什么体验？」→「写回答」（回答体蹭问题流量）
- B：创作中心（`zhihu.com` 右上角「创作」）→「发布文章」（文章体）

**账号要求**：知乎账号（发布与带图建议完成基础实名）。

**参数表**：

| 参数 | 回答方式 | 文章方式 |
|------|---------|---------|
| 标题 | 使用问题原题（无需自拟） | 在 WSL 里跑一套开源自建家庭服务器是什么体验？31 分钟构建、13 模块实测的完整记录 |
| 话题 | `WSL`、`Docker`、`家庭服务器`、`NAS`、`开源`（3-5 个） | 同左 |
| 封面 | 无强制 | 建议用管理面板首页截图 |
| 首段 | 已按知乎惯例写「先说结论」TL;DR 段 | 同左 |

**方言注意**：知乎不支持 `[TOC]` 目录语法；表格在回答流中渲染不稳——本稿已全部改为列表与加粗组织，粘贴后不要再自行加表格；图片上传时知乎会自动转存其图床。

### 3.3 掘金（1 篇）

**发布入口**：`juejin.cn` 登录 → 右上角「写文章」（进入创作中心 Markdown 编辑器）。

**账号要求**：掘金账号（新号发布建议绑定手机号）。

**参数表**：

| 参数 | 值 |
|------|-----|
| 标题 | 手把手从零开始：WSL2 + Docker 部署开源家庭服务器 EasyServer，附实测避坑 Top5 |
| 摘要 | 用文首引言段（一套模块化的自建家庭服务器方案……命令可直接复制） |
| 标签 | `Docker`、`Linux`、`运维`、`WSL`（发布页以可选标签为准，选 3-5 个） |
| 封面 | 可用编辑器自动生成，或上传横版截图（建议 compose ps 状态图） |
| 专栏 | 可归入自建「家庭服务器」专栏（见第 5 节运营） |

**方言注意**：掘金为标准 GFM，稿件代码块均带语言标注，直接粘贴即可；发布后可用「沉淀为专栏」归档。

## 4. 配图外链说明（占位符 → 素材 → 图床）

**背景（重要）**：仓库 `.gitignore` 含 `# 截图文件 *.png` 规则，**新截图无法提交入库**。`docs/images/` 下已有 3 张历史跟踪的 png（网络配置教程底图），其余配图均无仓库素材。因此：**所有发布配图必须先上传图床，再以外链替换文内占位符**。

**图床选型（任选其一）**：
- **SM.MS**：免费额度即可用，注册后上传拿 https 直链，适合轻量使用
- **阿里云 OSS**（或腾讯云 COS）：稳定可控，需创建 Bucket（公共读）、建议配置防盗链与生命周期
- 上传后必须**外链自检**：浏览器无痕窗口打开直链确认可访问

**占位符对照表**（全部 10 处）：

| 占位符 | 出现文件 | 建议截图内容 | 可复用底稿 |
|--------|---------|-------------|-----------|
| `IMAGE_PLACEHOLDER-docker-version` | csdn/INSTALL_TUTORIAL | `docker version` + hello-world 输出 | 需新截图 |
| `IMAGE_PLACEHOLDER-build-log` | csdn/INSTALL_TUTORIAL | `docker compose build` 完成输出 | 需新截图 |
| `IMAGE_PLACEHOLDER-setup-wizard` | csdn/INSTALL_TUTORIAL、juejin/QUICKSTART | 管理面板初始化向导页 | 需新截图 |
| `IMAGE_PLACEHOLDER-health-check` | csdn/INSTALL_TUTORIAL | `/api/health` 返回 + `docker compose ps` | 需新截图 |
| `IMAGE_PLACEHOLDER-network-overview` | csdn/NETWORK_TUTORIAL | 网络配置页总览 | `docs/images/network-config-overview.png` |
| `IMAGE_PLACEHOLDER-mode-selector` | csdn/NETWORK_TUTORIAL | 访问方式选择器 | `docs/images/mode-selector.png` |
| `IMAGE_PLACEHOLDER-tunnel-card` | csdn/NETWORK_TUTORIAL | Tunnel 中转服务卡片 | `docs/images/tunnel-services-card.png` |
| `IMAGE_PLACEHOLDER-panel-home` | zhihu/ANSWER_DRAFT | 管理面板首页 | 需新截图 |
| `IMAGE_PLACEHOLDER-module-store` | zhihu/ANSWER_DRAFT | 应用商店模块列表 | 需新截图 |
| `IMAGE_PLACEHOLDER-compose-ps` | juejin/QUICKSTART | `docker compose ps` Up (healthy) | 需新截图 |

**截图脱敏要求**：新截图中不得出现真实域名、公网 IP、密钥、个人用户目录路径——面板示例统一用 `example.com` / `<user>` 类占位；复用 `docs/images/` 底稿前同样过一遍脱敏检查。

## 5. 发布后运营建议

**合集/专栏归档**：
- CSDN：创建合集「家庭服务器实战」（安装篇 + 网络篇入合集，后续稿件续挂）
- 掘金：创建专栏收录 Quickstart，后续模块实测拆文可入同一专栏
- 知乎：回答发布后可在个人主页「想法」引流一次；后续补「五种网络模式怎么选」文章并互相引用

**发布顺序建议**：CSDN 安装篇 →（间隔 1-2 天）CSDN 网络篇 → 掘金 Quickstart → 知乎回答（保持账号连续活跃，避免一天多平台同稿触发重复内容判定）。

**更新公告时机**：
- 上游发布新版本（v0.3.x 之后）且影响文中步骤时：更新对应稿件，并在评论区置顶「已更新至 vX.Y.Z，变更点：……」
- QA 缺陷被上游修复时（关注缺陷 N build 型安装、S tag 不可拉、W1 jellyfin host 崩溃、T joplin BASE_URL、V nextcloud 信任域）：同步更新掘金避坑 Top5 对应条目并置顶说明
- 文内数据如因环境变化失效（如 mirror 地址失效），以评论置顶勘误优先于正文大改

**数据沉淀**：发布后 24h/72h 回看阅读/点赞/评论；评论区高频问题沉淀为 FAQ，可反哺仓库 `docs/faq.md` 与后续选题。

## 6. 评论区回复模板

**模板 1（镜像拉取慢/超时）**：
> 这套流程对网络比较敏感，实测 mirror 限速约 25-40 KB/s，大镜像建议先 `docker pull <镜像名>` 预热再装；镜像加速配置见文中 3.3 节。若在安装流程中约 600s 超时失败，预拉后重试即可。

**模板 2（面板打不开/端口占用）**：
> 先按两步定位：`docker compose ps` 看是否 Up (healthy)，`curl http://localhost:8900/api/health` 看是否返回 ok。宿主 8900 被占时用 docker-compose.override.yml 换 8901。WSL2 mirrored 环境特别注意：Windows 侧占用在 WSL 内 `ss`/`lsof` 查不到，要用 `netstat.exe` 排查（文中第七节有完整命令）。

**模板 3（模块安装失败）**：
> 先对照文中避坑 Top5：Nextcloud/backup 这类 build 型模块面板安装结构性失败是实测已知问题，手动 `docker compose build && up -d` 可用；ddns-go/notediscovery 的单文件挂载陷阱需安装前预创建真文件。每个模块的实测细节在仓库 `docs/guides/modules/` 对应篇目里都有带证据的记录。

**通用原则**：回复均以实测为依据、不承诺未验证的结论；涉及已知缺陷时引导到仓库文档与 issue，不线下承诺修复时间。

## 7. 版本基线

- 稿件基线：开源项目 EasyServer（MIT）v0.3.0，分支 `feature/wsl-install-test`，QA 实测日期 2026-09-04
- 发布前若仓库已升级大版本或网络模块地址失效，需重跑第 2 节自查表的「数据与实测一致」项后再发布
