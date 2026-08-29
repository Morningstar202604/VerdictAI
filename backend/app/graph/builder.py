from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.nodes import (
    critic_node,
    experts_node,
    human_final_node,
    judge_node,
)
from app.config import settings
from app.models.state import DebateState


def should_continue(state: DebateState) -> str:
    # 审判长已收敛，或已达到最大轮次（避免永不收敛时死循环）
    if state.get("consensus") or state.get("round", 0) >= settings.max_rounds:
        # 审判长由人类担任时，在结束前暂停等待落槌（judge_mode 取会话级，避免污染全局）
        judge_mode = state.get("judge_mode") or settings.judge_mode
        return "human_final" if judge_mode == "human" else "end"
    return "experts"


def build_graph():
    """构建多智能体探案辩论图：专家发言 -> 纠错 -> 审判长收敛 -> (人类落槌) -> 结束。"""
    builder = StateGraph(DebateState)

    builder.add_node("experts", experts_node)
    builder.add_node("critic", critic_node)
    builder.add_node("judge", judge_node)
    builder.add_node("human_final", human_final_node)

    builder.add_edge(START, "experts")
    builder.add_edge("experts", "critic")
    builder.add_edge("critic", "judge")

    builder.add_conditional_edges(
        "judge",
        should_continue,
        {
            "experts": "experts",  # 未收敛：自动进入下一轮（人类可中途介入注入）
            "human_final": "human_final",  # AI 已收敛 + 人类审判长：暂停落槌
            "end": END,
        },
    )
    builder.add_edge("human_final", END)

    return builder.compile(checkpointer=MemorySaver())
