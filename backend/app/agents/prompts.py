# -*- coding: utf-8 -*-
"""提示词注册中心（P2-5）：内置提示词的版本化仓库（对标 LangSmith Prompt Hub）。

大厂 Agent 平台（OpenAI/Dify/LangSmith）都提供 Prompt 版本管理：
- 每类提示词持有带版本号的正文快照，可追踪、可回滚、可做 Prompt A-B 对比；
- 运行期按配置选中某个版本（agent_config.prompt_version），不改正文也能回溯；
- 新增/修改提示词直接登记新版本号，绝不覆盖历史，配合审计即可复现任意场次。

登记方式：在 _PROMOTXT 中为某 key 追加新版本号（如 2），并保留旧版本号，
prompt_latest() 自动取最大版本；agent_config 可把角色/节点钉到指定版本。

目前覆盖：七角色 system 提示词 + critic/judge/reflect 三个 LLM 节点的调用提示词。
"""

from __future__ import annotations

from app.agents.roles import ROLES


# key -> {版本号: 正文}。角色正文来自 roles.py（v1 基线）；节点提示词在此登记。
# 新增版本：直接给对应 key 追加更高版本号，旧版本保留供回滚/对比。
_PROMOTXT: dict[str, dict[int, str]] = {}


def _register_role_prompts() -> None:
    for key, r in ROLES.items():
        _PROMOTXT.setdefault(key, {})[1] = r.get(
            "system", f"你是{key}专家，请基于卷宗理性分析、给出结论与依据。"
        )


_register_role_prompts()

# critic：纠错官（v1 基线，与 agent_config 内置一致）
_PROMOTXT.setdefault("critic", {})[1] = (
    "你是辩论纠错官。请对比以下各专家本轮主张，找出逻辑冲突、与物证不符、"
    "或缺少依据之处。只输出 JSON 数组，每项形如 "
    '{"issue": "...", "parties": ["role_key", ...]}。不要输出其他内容。'
)

# judge：审判长收敛（v1）；v2 增加「错误事实纠正」要求（示例：润色后登记）
_PROMOTXT.setdefault("judge", {})[1] = (
    "你是审判长。请综合各专家主张与矛盾清单，输出 JSON："
    '{"truth_hypothesis": "...", "evidence_chain": [...], "doubts": [...], '
    '"recommendation": "...", "next_steps": ["给司法机关的可执行后续流程，3-6条"], '
    '"disclaimer": "..."}。不要输出其他内容。'
)
_PROMOTXT.setdefault("judge", {})[2] = (
    "你是审判长。请先识别各专家主张间的矛盾与逻辑缺陷，若发现某专家基于错误事实"
    "得出结论，必须显式纠正并说明依据；然后输出 JSON："
    '{"truth_hypothesis": "...", "evidence_chain": [...], "doubts": [...], '
    '"recommendation": "...", "next_steps": ["给司法机关的可执行后续流程，3-6条"], '
    '"disclaimer": "..."}。不要输出其他内容。'
)

# reflect：可证伪性审查（v1）
_PROMOTXT.setdefault("reflect", {})[1] = (
    "你是庭审反思官。请对以下各专家主张进行可证伪性审查：对每条主张给出最有力的"
    "反对理由或必须补齐的证据（反对理由不得重复），只输出 JSON 数组：\n"
    '[{"role":"角色key","subject":"该条主张(≤40字)","objection":"反对理由/待核验点(≤80字)"}]\n'
    "禁止输出代码块或额外文字。"
)


def prompt_keys() -> list:
    return sorted(_PROMOTXT.keys())


def prompt_latest(key: str) -> int:
    versions = _PROMOTXT.get(key)
    if not versions:
        raise KeyError(f"提示词 {key} 未登记")
    return max(versions)


def prompt_text(key: str, version: int = None) -> str:
    """取提示词正文：version=None 取最高版本；指定版本存在则返回该版本。"""
    versions = _PROMOTXT.get(key)
    if not versions:
        raise KeyError(f"提示词 {key} 未登记")
    if version is not None and version in versions:
        return versions[version]
    return versions[prompt_latest(key)]


def prompt_versions(key: str) -> list:
    """该提示词的全部版本号（升序），供配置前端展示可回滚的版本。"""
    versions = _PROMOTXT.get(key)
    return sorted(versions) if versions else []


def resolve(key: str, requested: int = None) -> tuple[str, int]:
    """解析生效的正文与版本号：requested 非法/None 时回退到最新版本。"""
    versions = _PROMOTXT.get(key)
    if not versions:
        raise KeyError(f"提示词 {key} 未登记")
    if requested is None or requested not in versions:
        requested = prompt_latest(key)
    return versions[requested], requested


def prompt_version_info(key: str) -> dict:
    latest = prompt_latest(key)
    return {
        "key": key,
        "latest": latest,
        "versions": prompt_versions(key),
        "len_chars": len(prompt_text(key, latest)),
    }