# -*- coding: utf-8 -*-
"""角色与 Agent 配置路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import require_admin
from app.agents import agent_config
from app.agents.roles import role_list

router = APIRouter(tags=["agents"])


@router.get("/api/roles")
def roles():
    # P2-5：每个角色附带提示词版本信息（最新版本 + 可选版本清单），
    # 对应 roles.py 的角色表与 prompts 注册中心保持一致
    out = role_list()
    from app.agents import prompts

    for r in out:
        key = r["key"]
        try:
            r["prompt_versions"] = prompts.prompt_versions(key)
            r["prompt_version_latest"] = prompts.prompt_latest(key)
        except KeyError:
            r["prompt_versions"] = []
            r["prompt_version_latest"] = 1
    return {"roles": out}


@router.get("/api/prompts")
def list_prompts():
    """提示词版本目录（P2-5）：全部可版本化提示词的版本号与最新正文长度。"""
    from app.agents import prompts

    return {"prompts": [prompts.prompt_version_info(k) for k in prompts.prompt_keys()]}


@router.get("/api/agent-config")
def get_agent_config():
    return {"agents": agent_config.effective_list()}


@router.post("/api/agent-config")
def post_agent_config(payload: dict, _: dict = Depends(require_admin)):
    data = payload.get("agents", payload) if isinstance(payload, dict) else payload
    # 兼容三种提交形状：{agents:{key:cfg}}（设置页保存）、
    # {agents:[{key:cfg},...]}（导出/导入文件）、{key:cfg}（直接对象）
    if isinstance(data, list):
        data = {it.get("key"): it for it in data if isinstance(it, dict) and it.get("key")}
    return {"agents": agent_config.save(data)}