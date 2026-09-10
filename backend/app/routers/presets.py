# -*- coding: utf-8 -*-
"""策略模板（Presets）路由：产品"技能包"的 CRUD 与应用。"""

from __future__ import annotations

import json
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings
from app.data.store import atomic_write_json

router = APIRouter(prefix="/api/presets", tags=["presets"])

_PRESETS_PATH = os.path.join(settings.data_dir, "presets.json")

_BUILTIN_PRESETS: dict = {
    "刑事·严格证据攻防": {
        "guidance": "以证据裁判为主线：每一项指控事实必须对应证据编号；重点审查保管链、原始载体与取证程序；口供不作为定案唯一依据；对证明标准（排除合理怀疑）逐项检验。",
        "agents": {
            "law": "你是一位刑事诉讼证据法专家。除常规审查外，本轮请对每件关键证据逐项输出「三性」结论（真实性/合法性/关联性），并对证明标准达成度给出百分比估计与缺口清单。",
            "defense": "你是一位辩护 Agent。请优先攻击证据链中最薄弱的一环（保管链瑕疵、剪辑数据、身份不明生物检材），并明确给出替代事实模型；每个合理怀疑必须对应卷宗证据编号。",
        },
    },
    "民事·责任划分": {
        "guidance": "以合同与法律关系为骨架：先固定权利义务与违约事实，再按原因力比例划分责任；对不可抗力、减损义务、过错相抵逐项检验；赔偿数额须有计算依据。",
        "agents": {
            "psych": "你是一位集中于商业动机的分析专家：围绕交易背景、履约能力、违约获益与止损可能性构建动机与行为时间线，区分商业风险与主观过错。",
            "prosecutor": "你是一位主张方代理人：请按「合同成立 → 履行义务 → 违约事实 → 损失因果 → 数额依据」五步构建请求权基础，并引用《民法典》相应条文。",
        },
    },
}


def _load_presets() -> dict:
    presets = dict(_BUILTIN_PRESETS)
    try:
        with open(_PRESETS_PATH, encoding="utf-8") as f:
            custom = json.load(f)
        if isinstance(custom, dict):
            presets.update(custom)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return presets


@router.get("")
def get_presets():
    return {"presets": _load_presets()}


@router.post("")
def save_preset(payload: dict):
    data = payload if isinstance(payload, dict) else {}
    name = str(data.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "模板名称不能为空"}, status_code=400)
    body = {"guidance": str(data.get("guidance") or ""),
            "agents": data.get("agents") or {}}
    custom = {}
    try:
        with open(_PRESETS_PATH, encoding="utf-8") as f:
            custom = json.load(f)
        if not isinstance(custom, dict):
            custom = {}
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    custom[name] = body
    atomic_write_json(_PRESETS_PATH, custom)
    return {"saved": name}


@router.delete("/{name}")
def delete_preset(name: str):
    if name in _BUILTIN_PRESETS:
        return JSONResponse({"error": "内置模板不可删除"}, status_code=400)
    custom = {}
    try:
        with open(_PRESETS_PATH, encoding="utf-8") as f:
            custom = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        custom = {}
    if name not in custom:
        return JSONResponse({"error": "模板不存在"}, status_code=404)
    del custom[name]
    atomic_write_json(_PRESETS_PATH, custom)
    return {"deleted": name}


@router.post("/apply")
def apply_preset(payload: dict):
    """应用策略模板：写入各专家系统提示词（持久化到 agent_config），返回总体指导语。"""
    from app.agents import agent_config as ac

    data = payload if isinstance(payload, dict) else {}
    name = str(data.get("name") or "").strip()
    presets = _load_presets()
    if name not in presets:
        return JSONResponse({"error": "模板不存在"}, status_code=404)
    preset = presets[name]
    cfg = ac.load()
    for role_key, prompt in (preset.get("agents") or {}).items():
        if role_key in cfg and prompt:
            cfg[role_key]["system_prompt"] = prompt
    ac.save(cfg)
    return {"applied": name, "guidance": preset.get("guidance", ""),
            "agents": ac.effective_list()}