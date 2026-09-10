# -*- coding: utf-8 -*-
"""知识库路由：内置法条 + 用户自定义条目（三级检索的前两级入口）。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.legal.knowledge import add_knowledge, delete_knowledge, list_knowledge, search_knowledge

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("")
def get_knowledge(q: str = ""):
    """知识库：内置法条 + 用户自定义条目，支持关键词检索。"""
    return {"entries": search_knowledge(q) if q.strip() else list_knowledge()}


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