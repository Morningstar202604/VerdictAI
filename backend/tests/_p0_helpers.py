# -*- coding: utf-8 -*-
"""test_p0_infra / test_p2_platform 的辅助协程（避免依赖 pytest-asyncio 插件）。

run_retry_scenario：复刻 nodes.py 工具重试编排的核心循环；
run_trace_graph：mock 模式下跑一场完整辩论图，验证节点事件完整性；
run_tool_batch_scenario：复刻 nodes.py 的单轮多 tool_call 并行（gather）行为。
"""

from __future__ import annotations

import asyncio


def run_trace_graph() -> None:
    """mock 模式跑一场辩论，断言核心节点事件齐全。

    直接在测试进程内 asyncio.run，避免 pytest-asyncio 插件依赖；
    runner 的 span 收尾逻辑由 smoke/evaluate 覆盖此处不重复断言。
    """
    from app.agents.tools import activate_case
    from app.config import debate_snapshot
    from app.graph.builder import build_graph
    from app.intake.processor import preprocess

    case = {
        "id": "case_trace_test",
        "title": "Trace 测试案",
        "text": (
            "某日深夜，住宅区内发生命案。经查嫌疑人A案发时自称在加班，"
            "但监控显示其车辆于案发时间段出现在现场附近，且有通话记录自相矛盾。"
        ),
    }
    cfg = debate_snapshot()
    cfg["max_rounds"] = 1
    brief = asyncio.run(preprocess(case, cfg=cfg))
    case = dict(case)
    case["brief"] = brief
    activate_case(case)
    graph = build_graph()
    events: list = []

    async def sink(event: dict) -> None:
        if isinstance(event, dict):
            events.append(event)

    config = {
        "configurable": {
            "thread_id": "trace-test",
            "cfg": cfg,
            "sink": sink,
            "human_pop": lambda: None,
            "wait_for_human": lambda timeout=0: None,
            "hitl_timeout": 0,
            "note_tasks": [],
            "usage": {"calls": 0, "in_chars": 0, "out_chars": 0},
        }
    }
    inputs = {
        "case_id": case.get("id"),
        "case": case,
        "max_rounds": 1,
        "judge_mode": "ai",
        "agents": [],
    }

    async def _main() -> None:
        await graph.ainvoke(inputs, config=config)
        await asyncio.gather(
            *config["configurable"].get("note_tasks", []), return_exceptions=True
        )

    asyncio.run(_main())
    kinds = {e.get("kind") for e in events}
    assert {
        "round_start",
        "round_end",
        "critic_start",
        "critic_end",
        "reflect_start",
        "reflect",
        "judge_start",
        "judge_end",
        "verdict",
    }.issubset(kinds)


async def run_retry_scenario():
    """简化复刻 nodes.py 工具循环：失败退避重试 → 备用工具链降级。"""
    from langchain_core.tools import tool as lc_tool

    calls = {"primary": 0, "backup": 0}

    @lc_tool
    async def failing_tool(args: str = "") -> str:
        """一个必然失败的工具，用于验证重试与降级。"""
        calls["primary"] += 1
        raise RuntimeError("模拟一次工具故障")

    @lc_tool
    async def healthy_tool(args: str = "") -> str:
        """备用工具链中的健康工具。"""
        calls["backup"] += 1
        return "备用工具结果"

    failing_raw = failing_tool.coroutine
    healthy_raw = healthy_tool.coroutine

    events: list = []
    attempts = 0
    result = ""
    while True:
        attempts += 1
        try:
            result = await failing_raw()
            break
        except RuntimeError:
            events.append({"status": "retrying", "attempts": attempts})
            if attempts >= 2:
                result = await healthy_raw()
                events.append({"status": "fallback", "backup": "healthy_tool"})
                break
            await asyncio.sleep(0.01)
    return calls, events, result


async def run_tool_batch_scenario():
    """复刻 nodes.py 的并行工具编排：同轮多个 tool_call 用 gather 并发执行，
    结果按原序回填，并下发 tool + tool_batch 事件。"""
    calls = {"alpha": 0, "beta": 0}

    async def alpha(args: str = "") -> str:
        calls["alpha"] += 1
        await asyncio.sleep(0.02)
        return "alpha-结果"

    async def beta(args: str = "") -> str:
        calls["beta"] += 1
        await asyncio.sleep(0.02)
        return "beta-结果"

    events: list = []
    results: list = []
    tool_calls = [
        {"name": "alpha", "id": "t1", "args": {}},
        {"name": "beta", "id": "t2", "args": {}},
    ]
    tool_map = {"alpha": alpha, "beta": beta}

    async def _exec_one(tc):
        fn = tool_map.get(tc["name"])
        if fn is None:
            return "工具未找到"
        return await fn()

    gathered = await asyncio.gather(*[_exec_one(tc) for tc in tool_calls])
    for tc, result in zip(tool_calls, gathered):
        results.append(f"{tc['name']}={result}")
        events.append({"kind": "tool", "tool": tc["name"], "result": result})
    if len(tool_calls) > 1:
        events.append(
            {"kind": "tool_batch", "count": len(tool_calls),
             "tools": [tc["name"] for tc in tool_calls]}
        )
    return calls, events, results