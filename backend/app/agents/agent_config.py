from __future__ import annotations

import json
import os

from app.config import settings
from app.agents.roles import ROLES, INVESTIGATION_ORDER, TRIAL_ORDER
from app.data.store import atomic_write_json

CONFIG_PATH = os.path.join(settings.data_dir, "agent_config.json")


def _builtin_order() -> dict:
    return {k: i for i, k in enumerate(INVESTIGATION_ORDER + TRIAL_ORDER)}


def _defaults() -> dict:
    order = _builtin_order()
    out = {}
    for key, r in ROLES.items():
        grp = (
            "expert"
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
            "prompt_version": None,  # P2-5 提示词版本：None=最新；填版本号可回滚
            "few_shot": None,  # P2-8 少样本示例：可选 [{role:"user"/"assistant","content":"..."}] 注入系统提示词
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
        "prompt_version": None,
        "few_shot": None,
    }
    return out


def _get_prompt_version(cfg: dict, key: str):
    """读取配置中的提示词版本（兼容历史配置无此字段）。"""
    v = cfg.get("prompt_version")
    try:
        v = int(v) if v is not None else None
    except (TypeError, ValueError):
        v = None
    return v


def load() -> dict:
    defaults = _defaults()
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
    except FileNotFoundError:
        return defaults
    except json.JSONDecodeError:
        # 配置文件损坏（如历史版本非原子写入被中断）时回退内置默认，
        # 只影响专家配置的自定义部分；不自动覆盖原文件，便于人工恢复
        return defaults
    for k, v in saved.items():
        if k in defaults:
            for field in ("enabled", "order", "system_prompt", "tools", "model", "prompt_version", "few_shot"):
                if field in v:
                    defaults[k][field] = v[field]
    return defaults


def save(data: dict) -> dict:
    clean = {}
    for k, v in (data or {}).items():
        if not isinstance(v, dict):
            continue
        clean[k] = {
            "enabled": bool(v.get("enabled", True)),
            "order": int(v.get("order", 99)),
            "system_prompt": v.get("system_prompt"),
            "tools": v.get("tools"),
            "model": v.get("model"),
            "prompt_version": _get_prompt_version(v, k),
            "few_shot": v.get("few_shot"),
        }
    atomic_write_json(CONFIG_PATH, clean)
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
    from app.agents import tools as tools_mod

    cfg = load().get(key, {})
    names = cfg.get("tools")
    if names is None:
        names = tools_mod.builtin_tool_names(key)
    loaded = [tools_mod.TOOLS_BY_NAME[n] for n in names if n in tools_mod.TOOLS_BY_NAME]
    # MCP 外部工具（P1-5）：合并该角色可见的外部工具，失败/未配置时为空
    try:
        from app.agents import mcp as mcp_mod

        seen = {t.name for t in loaded}
        for t in mcp_mod.mcp_tools_for_role(key):
            if getattr(t, "name", "") and t.name not in seen:
                loaded.append(t)
                seen.add(t.name)
    except Exception:
        pass
    return loaded


def prompt_for_critic(claims_json: str, prompt_version: int = None) -> tuple[str, int]:
    """纠错官提示词：从注册中心解析正文+版本号（P2-5）。

    system_prompt 手工覆写优先于版本选择；均未指定时用注册中心最新版本。
    返回 (正文, 生效版本号)，供审计记录版本。"""
    from app.agents import prompts

    cfg = load().get("critic", {})
    override = cfg.get("system_prompt")
    if override and override.strip():
        return f"{override.strip()}\n\n请基于以下各专家主张比对：\n{claims_json}", -1  # -1=手工版
    if prompt_version is None:
        prompt_version = _get_prompt_version(cfg, "critic")
    base, ver = prompts.resolve("critic", prompt_version)
    return f"{base}\n\n请基于以下各专家主张比对：\n{claims_json}", ver


def effective_prompt(key: str, case_summary: str, prompt_version: int = None) -> tuple[str, int]:
    """返回 (系统提示词正文, 生效版本号)。系统覆写优先；否则按注册中心+配置版本。

    mock/演示路径同样走此函数，保证前端「提示词编辑」与版本选择一致生效。"""
    from app.agents import prompts

    cfg = load().get(key, {})
    fs = _few_shot_block(cfg.get("few_shot"))
    override = cfg.get("system_prompt")
    if override and override.strip():
        return (
            f"{override.strip()}\n\n"
            f"# 本案卷宗摘要\n{case_summary}\n\n"
            f"请记住你的身份：{ROLES[key]['name']}（{ROLES[key]['stance']}）。"
            f"请用中文、专业且简洁地发言，直接给出结论与依据，不要输出内部思考过程。"
            + fs
        ), -1
    if prompt_version is None:
        prompt_version = _get_prompt_version(cfg, key)
    body, ver = prompts.resolve(key, prompt_version)
    return build_from_prompt_body(key, body, case_summary) + fs, ver


def _few_shot_block(few_shot) -> str:
    """把配置的少样本示例（[{role, content}]）渲染为提示词里的「参考示例」块（P2-8）。

    对齐大厂 Agent 提示词工程的 few-shot 手法：给模型一到两组「输入→理想输出」示例，
    显著提升输出格式与专业风格的稳定性。示例缺失/非法时返回空串，不影响主流程。"""
    if not few_shot or not isinstance(few_shot, list):
        return ""
    lines = []
    for ex in few_shot[:4]:
        if not isinstance(ex, dict):
            continue
        role = "示例输入" if str(ex.get("role")) == "user" else "示例输出"
        content = str(ex.get("content") or "").strip()
        if content:
            lines.append(f"{role}：\n{content}")
    if not lines:
        return ""
    return "\n\n# 参考示例（仅用于理解期望风格，请勿照抄内容）\n" + "\n\n".join(lines)


def build_from_prompt_body(key: str, body: str, case_summary: str) -> str:
    """把注册中心正文 + 实际身份/卷宗信息组装为完整系统提示词（与 roles.build_system_prompt 同构）。"""
    from app.agents.roles import ROLES as _R

    role = _R[key]
    stance = role.get("stance", "")
    return (
        f"{body}\n\n"
        f"# 本案卷宗摘要\n{case_summary}\n\n"
        f"请记住你的身份：{role['name']}（{stance}）。\n\n"
        "输出格式要求（重要）：\n"
        "- 使用 Markdown 结构化排版：可用 `####` 小节标题、**加粗**强调、`-` 无序列表、`1.` 有序列表。\n"
        "- 每个论点之间用<b>空行</b>分隔，不要把所有内容挤成一段。\n"
        "- 明确分点：结论 → 依据 → 疑点/冲突，逐条列出。\n"
        "- 用中文、专业且简洁地发言，并始终标注你的依据。"
    )
