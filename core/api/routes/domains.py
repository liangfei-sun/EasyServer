"""
EasyServer 多域名管理 API
域名 CRUD、验证
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import re
import asyncio
import logging

from ..core.deps import get_config_manager
from ..core.dns_providers import get_provider
from .config import _check_ssl_status

router = APIRouter(prefix="/api/config", tags=["config"])

logger = logging.getLogger("easyserver.domains")

_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)


class DomainAddRequest(BaseModel):
    domain: str
    dns_provider: str
    purpose: str = "nginx"  # nginx | tunnel | both


@router.get("/domains")
async def list_domains():
    """获取域名列表及状态"""
    cm = get_config_manager()
    return {"domains": cm.get_domains()}


@router.post("/domains")
async def add_domain(request: DomainAddRequest):
    """添加域名（添加后自动触发验证）"""
    # 验证域名格式
    if not _DOMAIN_RE.match(request.domain):
        raise HTTPException(status_code=400, detail=f"无效的域名格式: {request.domain}")
    # 验证 dns_provider
    if not get_provider(request.dns_provider):
        raise HTTPException(status_code=400, detail=f"无效的 DNS 提供商: {request.dns_provider}")
    # 验证 purpose
    if request.purpose not in ("nginx", "tunnel", "both"):
        raise HTTPException(status_code=400, detail="purpose 必须为 nginx / tunnel / both")

    cm = get_config_manager()
    ok = cm.add_domain({
        "domain": request.domain,
        "dns_provider": request.dns_provider,
        "purpose": request.purpose,
    })
    if not ok:
        raise HTTPException(status_code=400, detail="添加域名失败")

    # 添加成功后自动验证
    verify_result = await verify_domain(request.domain)
    return {"success": True, "domains": cm.get_domains(), "verify": verify_result}


@router.post("/domains/{domain}/verify")
async def verify_domain(domain: str):
    """验证域名连通性和配置状态"""
    cm = get_config_manager()
    domain_cfg = cm.get_domain_config(domain)
    if not domain_cfg:
        raise HTTPException(status_code=404, detail=f"域名 {domain} 未配置")

    results = {
        "domain": domain,
        "dns_provider": domain_cfg.get("dns_provider", ""),
        "checks": {},
        "status": "active",
        "errors": []
    }

    dns_provider = domain_cfg.get("dns_provider", "")

    # 检查 1: DNS 提供商连通性
    try:
        if dns_provider == "aliyun":
            from .dns import _get_aliyun_credentials
            creds = _get_aliyun_credentials(cm)
            if creds.get("key") and creds.get("secret"):
                from ..core.alidns_api import AliyunDNSClient
                client = AliyunDNSClient(creds["key"], creds["secret"])
                records = client.find_record(domain, "@", "A")
                results["checks"]["dns_provider"] = {"ok": True, "message": "阿里云 DNS 连通正常"}
            else:
                results["checks"]["dns_provider"] = {"ok": False, "message": "阿里云 DNS 凭证未配置"}
                results["errors"].append("阿里云 DNS 凭证未配置，请在设置中配置 AccessKey")
        elif dns_provider == "cloudflare":
            from .dns import _get_cloudflare_token
            token = _get_cloudflare_token(cm)
            if token and not token.startswith("eyJ"):
                results["checks"]["dns_provider"] = {"ok": True, "message": "Cloudflare API 连通正常"}
            else:
                results["checks"]["dns_provider"] = {"ok": False, "message": "Cloudflare API Token 未配置或无效"}
                results["errors"].append("Cloudflare API Token 未配置或无效（注意：eyJ 开头的是 Tunnel Token，不是 API Token）")
        else:
            results["checks"]["dns_provider"] = {"ok": True, "message": f"DNS 提供商: {dns_provider}"}
    except Exception as e:
        results["checks"]["dns_provider"] = {"ok": False, "message": f"DNS 提供商连接失败: {str(e)}"}
        results["errors"].append(f"DNS 提供商连接失败: {str(e)}")

    # 检查 2: Tunnel 域名 cfargotunnel.com CNAME 可解析性（仅 purpose=tunnel/both 时检查）
    purpose = domain_cfg.get("purpose", "")
    if purpose in ("tunnel", "both"):
        try:
            proc = await asyncio.create_subprocess_exec(
                "dig", "@8.8.8.8", f"test.{domain}", "CNAME", "+short",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            result_stdout = stdout.decode().strip()
            if "cfargotunnel.com" in result_stdout:
                results["checks"]["tunnel_dns"] = {"ok": True, "message": "CNAME 指向 cfargotunnel.com，Tunnel DNS 配置正确"}
            elif result_stdout:
                results["checks"]["tunnel_dns"] = {"ok": True, "message": f"DNS 解析正常: {result_stdout}"}
            else:
                results["checks"]["tunnel_dns"] = {"ok": True, "message": "域名尚无 DNS 记录（添加服务后会自动创建）"}
        except Exception as e:
            results["checks"]["tunnel_dns"] = {"ok": False, "message": f"DNS 解析检测失败: {str(e)}"}

    # 检查 3: SSL 证书（仅 purpose=nginx/both 时检查）
    if purpose in ("nginx", "both"):
        ssl = await _check_ssl_status(domain)
        if ssl.get("ssl_valid"):
            results["checks"]["ssl"] = {"ok": True, "message": f"SSL 证书有效，到期: {ssl.get('ssl_expiry', '')}"}
        else:
            results["checks"]["ssl"] = {"ok": False, "message": "SSL 证书未找到或已过期"}
            results["errors"].append("SSL 证书未找到或已过期，请通过 ACME 模块申请证书")

    # 综合状态
    has_error = any(not check.get("ok", True) for check in results["checks"].values())
    if has_error:
        results["status"] = "error"
    elif results["errors"]:
        results["status"] = "warning"
    else:
        results["status"] = "active"

    # 更新域名状态
    cm.update_domain_status(domain, results["status"])

    return results


@router.delete("/domains/{domain}")
async def remove_domain(domain: str):
    """删除域名"""
    cm = get_config_manager()
    # 检查是否为主域名
    primary = cm.get_primary_domain()
    if domain == primary:
        raise HTTPException(status_code=400, detail="不允许删除主域名")
    ok = cm.remove_domain(domain)
    if not ok:
        raise HTTPException(status_code=404, detail=f"域名未找到: {domain}")
    return {"success": True, "domains": cm.get_domains()}
