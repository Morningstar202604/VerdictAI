from __future__ import annotations

import json
import os

from app.config import settings
from app.agents.roles import ROLES, INVESTIGATION_ORDER, TRIAL_ORDER

CONFIG_PATH = os.path.join(settings.data_dir, "agent_config.json")


def _builtin_order() -> dict:
    return {k: i for i, k in enumerate(INVESTIGATION_ORDER + TRIAL_ORDER)}


def _defaults() -> dict:
    order = _builtin_order()
    out = {}
    for key, r in ROLES.items():
        grp = (
            "investigation"
            if key in INVESTIGATION_ORDER
            else "trial"
            if key in TRIAL_ORDER
            else "other"
        )
        out[key] = {
            "key": key,
            "name": r["name"],
            "color": r["color"],
            "stance": r["stance"],
            "duty": r["duty"],
            "group": grp,
            "enabled": True,
            "order": order.get(key, 99),
            "default_prompt": r["system"],
            "system_prompt": None,
            "tools": None,
        }
    # 纠错官（固定节点，非出庭辩论专家，但提示词可配置）
    out["critic"] = {
        "key": "critic",
        "name": "纠错官",
        "color": "#f59e0b",
        "stance": "梳理矛盾、质疑漏洞",
        "duty": "比对各专家主张，输出矛盾/纠错清单",
        "group": "other",
        "enabled": True,
        "order": 99,
        "default_prompt": (
            "你是辩论纠错官。请对比以下各专家本轮主张，找出逻辑冲突、与物证不符、"
            "或缺少依据之处。只输出 JSON 数组，每项形如 "
            '{"issue": "...", "parties": ["role_key", ...]}。不要输出其他内容。'
        ),
        "system_prompt": None,
        "tools": None,
    }
    return out


def load() -> dict:
    defaults = _defaults()
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
    except FileNotFoundError:
        return defaults
    for k, v in saved.items():
        if k in defaults:
            for field in ("enabled", "order", "system_prompt", "tools", "model"):
                if field in v:
                    defaults[k][field] = v[field]
    return defaults


def save(data: dict) -> dict:
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    clean = {}
    for k, v in data.items():
        clean[k] = {
            "enabled": bool(v.get("enabled", True)),
            "order": int(v.get("order", 99)),
            "system_prompt": v.get("system_prompt"),
            "tools": v.get("tools"),
            "model": v.get("model"),
        }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    return effective_list()


def effective_list() -> list:
    items = list(load().values())
    items.sort(key=lambda x: x["order"])
    return items


def debate_order() -> list:
    """出场辩论的专家（不含审判长），按 order 升序、仅启用项。"""
    items = [
        r
        for r in effective_list()
        if r["key"] not in ("judge", "critic") and r.get("enabled")
    ]
    items.sort(key=lambda x: x["order"])
    return [r["key"] for r in items]


def effective_tools(key: str) -> list:
    from app.agents.tools import TOOLS_BY_NAME, builtin_tool_names

    cfg = load().get(key, {})
    names = cfg.get("tools")
    if names is None:
        names = builtin_tool_names(key)
    return [TOOLS_BY_NAME[n] for n in names if n in TOOLS_BY_NAME]


def prompt_for_critic(claims_json: str) -> str:
    cfg = load().get("critic", {})
    override = cfg.get("system_prompt")
    base = (
        override.strip()
        if (override and override.strip())
        else _defaults()["critic"]["default_prompt"]
    )
    return f"{base}\n\n请基于以下各专家主张比对：\n{claims_json}"


def effective_prompt(key: str, case_summary: str) -> str:
    from app.agents.roles import build_system_prompt

    cfg = load().get(key, {})
    override = cfg.get("system_prompt")
    if override and override.strip():
        return (
            f"{override.strip()}\n\n"
            f"# 本案卷宗摘要\n{case_summary}\n\n"
            f"请记住你的身份：{ROLES[key]['name']}（{ROLES[key]['stance']}）。"
            f"请用中文、专业且简洁地发言，直接给出结论与依据，不要输出内部思考过程。"
        )
    return build_system_prompt(key, case_summary)
