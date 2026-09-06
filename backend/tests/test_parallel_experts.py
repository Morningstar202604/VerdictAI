"""专家并行发言测试。

铁律：gather 保持传入顺序 → 无论完成先后，claims 与轮次摘要的
角色顺序都确定；mock 演示保持串行（auto 语义）；并发上限真实生效。"""

import asyncio
import json

import pytest

from app.agents.nodes import DEBATE_ROLES, _parallel_enabled, experts_node
from app.config import debate_snapshot, settings


@pytest.fixture()
def debate_env(monkeypatch):
    """mock 供应商 + 收集事件的 sink + 最小可跑状态。"""
    monkeypatch.setattr(settings, "llm_provider", "mock")
    events = []

    async def sink(ev):
        events.append(ev)

    async def noop():
        return None

    cfg = debate_snapshot()
    cfg["max_concurrency"] = 7
    config = {"configurable": {"sink": sink, "cfg": cfg, "note_tasks": [], "usage": {}}}
    state = {
        "case": {"id": "case_par", "title": "并行测试案件", "summary": "并行测试。",
                 "brief": {"per_role_material": {}, "reasoning_intensity": "low",
                           "global_guidance": "", "intake_done": True}},
        "round": 0, "max_rounds": 3, "agents": [], "judge_mode": "ai",
    }
    return {"events": events, "config": config, "state": state, "sink": sink}


def _patch_note_tasks(monkeypatch):
    """合议记录走后台任务，测试里直接跳过以免拖慢。"""
    import app.agents.nodes as N

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(N, "_summarize_note", _noop)


def test_parallel_disabled_for_mock_by_default(debate_env):
    assert _parallel_enabled(debate_env["config"]["configurable"]["cfg"]) is False


def test_parallel_enabled_for_real_provider(debate_env):
    cfg = dict(debate_env["config"]["configurable"]["cfg"])
    cfg["llm_provider"] = "openai"
    assert _parallel_enabled(cfg) is True
    assert _parallel_enabled({**cfg, "parallel_experts": "off"}) is False


def test_parallel_gather_order_deterministic(debate_env, monkeypatch):
    """7 位专家乱序完成时，claims/轮次摘要的角色顺序仍与出场顺序一致。"""
    _patch_note_tasks(monkeypatch)
    monkeypatch.setattr(settings, "parallel_experts", "on")
    cfg = debate_env["config"]["configurable"]["cfg"]
    cfg["parallel_experts"] = "on"
    cfg["llm_provider"] = "openai"  # auto 判定需要非 mock
    cfg["llm_base_url"] = "http://test-local"  # 不会真正联网：LLM 仍为 mock 注入

    async def run():
        return await experts_node(debate_env["state"], debate_env["config"])

    # get_llm 在 provider=openai 时会构造 ChatOpenAI——测试改回 mock 但保留 parallel=on
    monkeypatch.setattr(settings, "llm_provider", "mock")
    cfg["parallel_experts"] = "on"
    result = asyncio.run(run())

    claims = result["claims"]
    assert set(claims.keys()) == set(DEBATE_ROLES)
    summary = json.loads(result["round_summaries"][0])
    assert list(summary.keys()) == DEBATE_ROLES  # 顺序与出场顺序完全一致


def test_concurrency_cap_serializes_when_one(debate_env, monkeypatch):
    """max_concurrency=1 时退化为串行：第一人结束后第二人才开始。"""
    _patch_note_tasks(monkeypatch)
    monkeypatch.setattr(settings, "parallel_experts", "on")
    cfg = debate_env["config"]["configurable"]["cfg"]
    cfg["parallel_experts"] = "on"
    cfg["llm_provider"] = "mock"
    cfg["max_concurrency"] = 1
    monkeypatch.setattr(settings, "llm_provider", "mock")

    asyncio.run(experts_node(debate_env["state"], debate_env["config"]))

    starts = [i for i, e in enumerate(debate_env["events"]) if e["kind"] == "agent_start"]
    ends = [i for i, e in enumerate(debate_env["events"]) if e["kind"] == "agent_end"]
    assert len(starts) == 7 and len(ends) == 7
    # 串行：第 1 个 agent_end 必然早于最后 1 个 agent_start
    assert ends[0] < starts[-1]


def test_parallel_overlaps_in_flight(debate_env, monkeypatch):
    """默认并发 7：多个专家在他人结束前就已开始（真并行在飞）。"""
    _patch_note_tasks(monkeypatch)
    monkeypatch.setattr(settings, "parallel_experts", "on")
    cfg = debate_env["config"]["configurable"]["cfg"]
    cfg["parallel_experts"] = "on"
    cfg["llm_provider"] = "mock"
    cfg["max_concurrency"] = 7
    monkeypatch.setattr(settings, "llm_provider", "mock")

    asyncio.run(experts_node(debate_env["state"], debate_env["config"]))

    starts = [i for i, e in enumerate(debate_env["events"]) if e["kind"] == "agent_start"]
    ends = [i for i, e in enumerate(debate_env["events"]) if e["kind"] == "agent_end"]
    assert min(ends) > max(starts)  # 全部先开始、后结束
