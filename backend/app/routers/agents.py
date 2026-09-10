# -*- coding: utf-8 -*-
"""角色与 Agent 配置路由。"""

from __future__ import annotations

from fastapi import APIRouter

from app.agents import agent_config
from app.agents.roles import role_list

router = APIRouter(tags=["agents"])


@router.get("/api/roles")
def roles():
    return {"roles": role_list()}


@router.get("/api/agent-config")
def get_agent_config():
    return {"agents": agent_config.effective_list()}


@router.post("/api/agent-config")
def post_agent_config(payload: dict):
    data = payload.get("agents", payload) if isinstance(payload, dict) else payload
    # 兼容三种提交形状：{agents:{key:cfg}}（设置页保存）、
    # {agents:[{key:cfg},...]}（导出/导入文件）、{key:cfg}（直接对象）
    if isinstance(data, list):
        data = {it.get("key"): it for it in data if isinstance(it, dict) and it.get("key")}
    return {"agents": agent_config.save(data)}