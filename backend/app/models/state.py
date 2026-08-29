from __future__ import annotations

import operator
from typing import Annotated, Dict, List, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


def _merge_claims(left: Dict, right: Dict) -> Dict:
    """合并各智能体的主张，不互相覆盖。"""
    merged = dict(left or {})
    merged.update(right or {})
    return merged


def _extend_contradictions(left: List, right: List) -> List:
    return list(left or []) + list(right or [])


class DebateState(TypedDict, total=False):
    # ---- 第一层：领域/案件 ----
    case_id: str
    case: Dict  # 完整卷宗（证据、时间线、人物等）

    # ---- 第三层：记忆 ----
    round: int
    max_rounds: int
    blackboard: Dict  # 共享黑板：已确认事实 / 争议点 / 矛盾清单
    claims: Annotated[Dict, _merge_claims]  # 各 Agent 本轮主张 {role_key: text}
    contradictions: Annotated[List, _extend_contradictions]  # 矛盾表
    messages: Annotated[List[BaseMessage], add_messages]  # 全部对话
    round_summaries: Annotated[
        List[str], operator.add
    ]  # 各轮专家主张摘要（跨轮记忆，仅近轮使用）

    # ---- 第六层：收敛 ----
    consensus: bool
    verdict: Dict  # 最终裁决/真相推定
    judge_mode: str  # 审判长模式：ai / human（按会话隔离，避免污染全局 settings）

    # ---- 第七层：人工介入 ----
    human_input: str

    # ---- 第八层：可观测 ----
    log: Annotated[List, operator.add]  # 结构化事件日志，供前端与时间轴
