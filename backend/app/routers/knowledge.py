# -*- coding: utf-8 -*-
"""知识库路由：内置法条 + 用户自定义条目（三级检索的前两级入口）。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.legal.knowledge import add_knowledge, delete_knowledge, list_knowledge, search_knowledge

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("")
def get_knowledge(q: str = "", semantic: int = 0):
    """知识库：内置法条 + 用户自定义条目。

    q 为空 → 全部列表；q 非空 → 检索：
    - semantic=0 纯关键词（精确、确定，供专家工具引用）；
    - semantic=1 混合检索（关键词精确命中优先 + 向量语义补足，供 UI 探索用）。"""
    if not q.strip():
        return {"entries": list_knowledge(), "mode": "all"}
    if semantic:
        from app.legal.retriever import hybrid_search

        return {"entries": hybrid_search(q, limit=6), "mode": "hybrid"}
    return {"entries": search_knowledge(q, limit=6), "mode": "keyword"}


@router.post("")
def post_knowledge(payload: dict):
    """新增自定义知识条目（标题/正文/关键词）。"""
    data = payload if isinstance(payload, dict) else {}
    title = str(data.get("title") or "").strip()
    text = str(data.get("text") or "").strip()
    if not title or not text:
        return JSONResponse({"error": "标题与正文不能为空"}, status_code=400)
    kws = data.get("keywords") or []
    if isinstance(kws, str):
        kws = [k for k in kws.replace("，", ",").split(",") if k.strip()]
    entry = add_knowledge(title, text, kws)
    return {"entry": entry}


@router.delete("/{entry_id}")
def remove_knowledge(entry_id: str):
    """删除自定义知识条目（内置法条不可删除）。"""
    if not delete_knowledge(entry_id):
        return JSONResponse({"error": "条目不存在或为内置法条（不可删除）"}, status_code=400)
    return {"deleted": entry_id}