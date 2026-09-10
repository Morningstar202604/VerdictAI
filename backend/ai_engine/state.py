# -*- coding: utf-8 -*-
"""本地推理引擎 · 会话状态与轮次推导。

按 (案件哈希, 角色) 键控轮次，杜绝并行专家请求互相污染；
案件数量超限时按 LRU 淘汰旧状态，防止内存无限增长。
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any, Dict, List

from ai_engine.parsing import Case, _section, _text_of

LOCK = threading.Lock()
_MAX_CASES = 50  # 最多跟踪的案件数，超出后淘汰最旧的，防止内存无限增长
STATE: Dict[str, Any] = {
    "rounds_by_case": {},   # {case_hash: {role: round_no}} —— 按案件隔离，支持并发辩论
    "critic_by_case": {},   # {case_hash: critic_calls}
    "names": [],
    "last_case": None,
    "last_verdict": None,
    "_case_order": [],      # 按插入顺序记录 case_hash，用于 LRU 淘汰
    "critic_emitted_by_case": {},  # {case_hash: [已提出的矛盾，用于逐轮消化]}
}


def _touch_case(case_hash: str) -> None:
    """更新案件访问顺序，并在超限时淘汰最旧案件的状态。"""
    order = STATE["_case_order"]
    if case_hash in order:
        order.remove(case_hash)
    order.append(case_hash)
    while len(order) > _MAX_CASES:
        old = order.pop(0)
        STATE["rounds_by_case"].pop(old, None)
        STATE["critic_by_case"].pop(old, None)
        STATE["critic_emitted_by_case"].pop(old, None)


def _refresh_case(material: str, hash_basis: str = "") -> Case:
    # hash 仅取全角色共享的案件概要小节；无小节时退到系统提示中的「本案卷宗摘要」
    # （同场辩论各角色一致），不能用拼接全文——否则第二轮注入历史摘要后
    # hash 变化，会误重置轮次计数。
    basis = (
        _section(material, "案件概要")
        or _section(material, "本案卷宗摘要")
        or hash_basis
        or material[:200]
    )
    h = hashlib.md5(basis.encode("utf-8")).hexdigest()
    case = Case(material)
    case.hash = h
    return case


def _summary_count(messages: List[dict]) -> int:
    """请求里【前序轮次专家意见摘要】的条数（后端每轮注入最近 2 条）。"""
    n = 0
    for m in messages:
        if m.get("role") == "system" and "前序轮次专家意见摘要" in _text_of(m.get("content")):
            n += 1
    return n


def _round_for(case_hash: str, role: str, messages: List[dict]) -> int:
    """确定性推导当前辩论轮次（并行同轮专家请求互不干扰）：

    - 0 条摘要 → 第 1 轮；1 条 → 第 2 轮；
    - ≥2 条 → 第 3 轮起，用 (案件, 角色) 键控计数器累计（后端摘要封顶 2 条）；
    - 出现低轮次请求（新一场辩论开始）时计数器自动归零。
    """
    sc = _summary_count(messages)
    with LOCK:
        _touch_case(case_hash)
        if sc < 2:
            STATE["rounds_by_case"].setdefault(case_hash, {})[role] = sc + 1
            return sc + 1
        c = STATE["rounds_by_case"].setdefault(case_hash, {}).get(role, 2)
        c = c + 1
        STATE["rounds_by_case"][case_hash][role] = c
        return c


def _reset_critic(case_hash: str, messages: List[dict]) -> None:
    """新辩论（第 1 轮专家请求）时归零该案件的纠错官轮次计数。"""
    if _summary_count(messages) == 0:
        with LOCK:
            _touch_case(case_hash)
            STATE["critic_by_case"][case_hash] = 0