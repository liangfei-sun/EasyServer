"""
EasyServer DNS Providers
DNS 提供商定义表：预置常见提供商 + 自定义项
凭证统一写入 .env（ACME_* 系列）与 data/acme/dns-credentials.env（acme 容器 env_file）
"""

# 敏感值脱敏前缀（前端回显已配置凭证时使用，后端写入时跳过该值防止覆盖）
MASK_PREFIX = "***"


def _p(provider_id, name, acme_plugin, description, help_url, fields, doc_url=""):
    return {
        "id": provider_id,
        "name": name,
        "acme_plugin": acme_plugin,
        "description": description,
        "help_url": help_url,
        "doc_url": doc_url,
        "fields": fields,
    }


# 预置 DNS 提供商（凭证字段名对应 acme.sh DNS API 插件的环境变量）
DNS_PROVIDERS = [
    _p(
        "aliyun", "阿里云", "dns_ali",
        "国内主流云服务商，使用 RAM 子账号 AccessKey",
        "https://ram.console.aliyun.com/manage/ak",
        [
            {
                "key": "key", "env": "ACME_ALI_KEY", "acme_env": "Ali_Key", "label": "AccessKey ID",
                "placeholder": "LTAI5t...",
                "help": "作用：用于 ACME 自动申请 SSL 证书时在阿里云 DNS 添加解析验证记录，以及 DDNS 动态域名解析。"
                        "获取：登录阿里云 RAM 控制台（https://ram.console.aliyun.com/users）→ 创建用户 → 授权 AliyunDNSFullAccess 权限 → 创建 AccessKey 并复制 ID",
            },
            {
                "key": "secret", "env": "ACME_ALI_SECRET", "acme_env": "Ali_Secret", "label": "AccessKey Secret",
                "placeholder": "AccessKey Secret（仅创建时显示一次，请立即复制）",
                "help": "与 AccessKey ID 配套的密钥，同样在 RAM 控制台创建 AccessKey 时生成。注意：Secret 只在创建时显示一次，丢失后需重新创建",
            },
        ],
    ),
    _p(
        "cloudflare", "Cloudflare", "dns_cf",
        "全球知名 CDN/DNS 服务商，使用 API Token",
        "https://dash.cloudflare.com/profile/api-tokens",
        [
            {
                "key": "token", "env": "ACME_CF_TOKEN", "acme_env": "CF_Token", "label": "API Token",
                "placeholder": "Cloudflare API Token",
                "help": "作用：用于 ACME 自动申请 SSL 证书时在 Cloudflare DNS 添加验证记录。"
                        "获取：登录 Cloudflare → My Profile → API Tokens → Create Token → 权限选择 Zone > DNS > Edit → 生成后复制",
            },
        ],
    ),
    _p(
        "dnspod", "腾讯云 DNSPod", "dns_dp",
        "腾讯云旗下 DNS 服务，使用 DNSPod ID 和 Key",
        "https://console.dnspod.cn/account/token",
        [
            {
                "key": "id", "env": "DP_Id", "acme_env": "DP_Id", "label": "DNSPod ID",
                "placeholder": "DNSPod ID",
                "help": "作用：ACME 申请证书时在 DNSPod 添加验证记录。"
                        "获取：登录 DNSPod 控制台 → 账号中心 → API Token 管理中创建",
            },
            {
                "key": "key", "env": "DP_Key", "acme_env": "DP_Key", "label": "DNSPod API Key",
                "placeholder": "DNSPod API Key",
                "help": "与 DNSPod ID 配套的 API Key，在同一个页面创建",
            },
        ],
    ),
    _p(
        "huaweicloud", "华为云", "dns_huaweicloud",
        "华为云 DNS 服务，使用账号名/密码/租户名",
        "https://console.huaweicloud.com/iam/",
        [
            {
                "key": "username", "env": "HUAWEICLOUD_Username", "acme_env": "HUAWEICLOUD_Username", "label": "IAM 用户名",
                "placeholder": "华为云 IAM 用户名",
                "help": "作用：ACME 申请证书时在华为云 DNS 添加验证记录。"
                        "获取：登录华为云 IAM 控制台，用户名即账号的 IAM 用户",
            },
            {
                "key": "password", "env": "HUAWEICLOUD_Password", "acme_env": "HUAWEICLOUD_Password", "label": "IAM 用户密码",
                "placeholder": "IAM 用户登录密码",
                "help": "IAM 用户的登录密码",
            },
            {
                "key": "domain", "env": "HUAWEICLOUD_DomainName", "acme_env": "HUAWEICLOUD_DomainName", "label": "租户名（账号名）",
                "placeholder": "华为云账号名",
                "help": "即华为云账号名称（租户名），在账号中心可见",
            },
        ],
    ),
    _p(
        "godaddy", "GoDaddy", "dns_gd",
        "海外知名域名注册商，使用 API Key/Secret",
        "https://developer.godaddy.com/keys",
        [
            {
                "key": "key", "env": "GD_Key", "acme_env": "GD_Key", "label": "API Key",
                "placeholder": "GoDaddy API Key",
                "help": "作用：ACME 申请证书时在 GoDaddy DNS 添加验证记录。"
                        "获取：GoDaddy Developer Portal（https://developer.godaddy.com/keys）→ Create API Key",
            },
            {
                "key": "secret", "env": "GD_Secret", "acme_env": "GD_Secret", "label": "API Secret",
                "placeholder": "GoDaddy API Secret",
                "help": "与 API Key 配套的 Secret，创建 Key 时同时生成",
            },
        ],
    ),
    _p(
        "he", "HE.net", "dns_he",
        "Hurricane Electric 免费 DNS 服务",
        "https://dns.he.net/",
        [
            {
                "key": "username", "env": "HE_Username", "acme_env": "HE_Username", "label": "HE 用户名",
                "placeholder": "HE.net 用户名",
                "help": "作用：ACME 申请证书时在 HE.net DNS 添加验证记录。获取：dns.he.net 注册账号",
            },
            {
                "key": "password", "env": "HE_Password", "acme_env": "HE_Password", "label": "HE 密码",
                "placeholder": "HE.net 密码",
                "help": "HE.net 账号密码",
            },
        ],
    ),
    # 自定义项：支持 acme.sh 支持但未预置的任何 DNS 提供商
    _p(
        "custom", "自定义（其他 DNS 提供商）", "",
        "填写 acme.sh 支持的任意 DNS 插件名和凭证变量，如 dns_aws、dns_ovh、dns_linode 等",
        "https://github.com/acmesh-official/acme.sh/wiki/dnsapi",
        [
            {
                "key": "plugin", "env": "ACME_DNS_CUSTOM_PLUGIN", "label": "acme.sh DNS 插件名",
                "placeholder": "如 dns_aws、dns_ovh、dns_linode",
                "help": "acme.sh 的 DNS API 插件名称，格式为 dns_xxx，完整列表见 https://github.com/acmesh-official/acme.sh/wiki/dnsapi",
            },
            {
                "key": "vars", "env": "", "label": "凭证变量（KEY=值，每行一个）",
                "placeholder": "AWS_ACCESS_KEY_ID=AKIA...\nAWS_SECRET_ACCESS_KEY=xxxxx",
                "type": "textarea",
                "help": "该插件需要读取的环境变量，每行一个 KEY=值，变量名必须与 acme.sh 文档中的一致",
            },
        ],
    ),
]


def get_provider(provider_id: str) -> dict:
    """按 ID 获取提供商定义"""
    for p in DNS_PROVIDERS:
        if p["id"] == provider_id:
            return p
    return None


def is_mask_value(value: str) -> bool:
    """判断是否为脱敏回显值（前端回填时跳过，防止覆盖真实凭证）"""
    return bool(value) and value.startswith(MASK_PREFIX)


def get_provider_fields(provider_id: str) -> list:
    p = get_provider(provider_id)
    return p["fields"] if p else []


def env_value_for_field(provider_id: str, field_key: str, credentials: dict) -> str:
    """从凭证字典中取某字段值（含脱敏检测）"""
    p = get_provider(provider_id)
    if not p:
        return ""
    for f in p["fields"]:
        if f["key"] == field_key:
            creds = credentials.get(provider_id, {})
            value = creds.get(field_key, "")
            return value if not is_mask_value(value) else ""
    return ""
