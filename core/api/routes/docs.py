"""
EasyServer Docs API
文档接口：全局文档列表、文档内容、模块使用说明
"""
from fastapi import APIRouter, HTTPException
from ..core.module_loader import ModuleLoader
from pathlib import Path
import os

router = APIRouter(prefix="/api/docs", tags=["docs"])

PROJECT_ROOT = os.environ.get("EASYSERVER_ROOT", "/app")


def _get_module_loader():
    return ModuleLoader(PROJECT_ROOT)


def _get_docs_dir():
    return Path(PROJECT_ROOT) / "docs"


# 全局文档注册表（id -> 文件名 + 标题）
GLOBAL_DOCS = [
    {"id": "quick-start", "title": "快速入门指南", "file": "quick-start.md", "icon": "Promotion"},
    {"id": "network-config", "title": "网络配置指南", "file": "network-config.md", "icon": "Connection"},
    {"id": "faq", "title": "常见问题解答", "file": "faq.md", "icon": "QuestionFilled"},
]


@router.get("")
async def list_docs():
    """获取文档目录列表（全局文档 + 模块文档）"""
    docs_dir = _get_docs_dir()
    ml = _get_module_loader()

    # 全局文档
    global_docs = []
    for doc in GLOBAL_DOCS:
        doc_path = docs_dir / doc["file"]
        global_docs.append({
            "id": doc["id"],
            "title": doc["title"],
            "icon": doc["icon"],
            "type": "global",
            "exists": doc_path.exists(),
        })

    # 模块文档
    module_docs = []
    modules = ml.get_all_modules()
    for module in modules:
        docs_field = module.get("docs")
        if docs_field:
            module_docs.append({
                "id": f"module-{module['id']}",
                "title": module.get("name", module["id"]),
                "type": "module",
                "module_id": module["id"],
                "has_usage": bool(docs_field.get("usage")),
                "has_faq": bool(docs_field.get("faq")),
                "links": docs_field.get("links", []),
            })

    return {
        "global_docs": global_docs,
        "module_docs": module_docs,
    }


@router.get("/modules/{module_id}")
async def get_module_docs(module_id: str):
    """获取模块使用说明"""
    ml = _get_module_loader()
    module = ml.get_module_by_id(module_id)
    if not module:
        raise HTTPException(status_code=404, detail=f"模块 {module_id} 不存在")

    docs_field = module.get("docs")
    if not docs_field:
        raise HTTPException(status_code=404, detail=f"模块 {module_id} 暂无使用说明")

    return {
        "module_id": module_id,
        "module_name": module.get("name", module_id),
        "docs": docs_field,
    }


@router.get("/{doc_id}")
async def get_doc(doc_id: str):
    """获取具体文档内容（Markdown）"""
    docs_dir = _get_docs_dir()

    # 查找全局文档
    for doc in GLOBAL_DOCS:
        if doc["id"] == doc_id:
            doc_path = docs_dir / doc["file"]
            if not doc_path.exists():
                raise HTTPException(status_code=404, detail=f"文档文件 {doc['file']} 不存在")
            content = doc_path.read_text(encoding="utf-8")
            return {
                "id": doc_id,
                "title": doc["title"],
                "type": "global",
                "content": content,
            }

    raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
