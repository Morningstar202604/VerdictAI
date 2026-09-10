"""P0 基础设施：会话 Trace、LLM 响应缓存、工具重试编排。

- Trace：runner 在结束时下发 trace 事件，含每个审判节点 span 与用量增量；
- 缓存：同 prompt 命中不重复调用、stats 计数、0=关闭；
- 工具重试：失败退避重试 + 备用工具链降级事件。
"""

import asyncio

import pytest

from app.config import settings
from app.models.llm import (
    clear_response_cache,
    llm_cache_stats,
    response_cache_get,
    response_cache_put,
)


def _msgs():
    from langchain_core.messages import HumanMessage, SystemMessage

    return [
        SystemMessage(content="你是测试角色"),
        HumanMessage(content="这是完全相同的测试消息，用于验证缓存命中"),
    ]


@pytest.fixture(autouse=True)
def _cache_env(monkeypatch):
    monkeypatch.setattr(settings, "llm_cache_size", 32)
    clear_response_cache()
    yield
    clear_response_cache()
    monkeypatch.setattr(settings, "llm_cache_size", 0)


def test_cache_miss_then_hit():

    model = "test-model-x"
    assert response_cache_get(model, _msgs()) is None  # miss
    response_cache_put(model, _msgs(), "缓存的回复内容")
    assert response_cache_get(model, _msgs()) == "缓存的回复内容"  # hit
    assert response_cache_get("other-model", _msgs()) is None  # 模型名参与键


def test_cache_stats_counted():
    model = "test-model-y"
    response_cache_put(model, _msgs(), "v1")
    hits, misses = llm_cache_stats()["hits"], llm_cache_stats()["misses"]
    assert (hits, misses) == (0, 0)  # put 不计数；miss 由 get 未命中累计
    assert response_cache_get(model, _msgs()) == "v1"
    assert llm_cache_stats()["hits"] == 1


def test_cache_disabled_when_size_zero(monkeypatch):
    monkeypatch.setattr(settings, "llm_cache_size", 0)
    model = "test-model-z"
    response_cache_put(model, _msgs(), "不应缓存")
    assert response_cache_get(model, _msgs()) is None


def test_cache_eviction_lru(monkeypatch):
    monkeypatch.setattr(settings, "llm_cache_size", 2)
    clear_response_cache()
    from langchain_core.messages import HumanMessage

    def build(tag):
        return [HumanMessage(content=f"unique-{tag}-" + "x" * 20)]

    m1, m2, m3 = build("a"), build("b"), build("c")
    response_cache_put("m", m1, "1")
    response_cache_put("m", m2, "2")
    response_cache_get("m", m1)  # 触碰 a → LRU 顺序 a, b
    response_cache_put("m", m3, "3")  # 淘汰最久未用的 b
    assert response_cache_get("m", m2) is None  # b 被淘汰
    assert response_cache_get("m", m1) == "1"
    assert response_cache_get("m", m3) == "3"


def test_tool_retry_and_fallback_events():
    """P0-4：工具调用失败退避重试，耗尽后走备用工具链并下发事件。"""
    from tests._p0_helpers import run_retry_scenario

    calls, events, result = asyncio.run(run_retry_scenario())

    assert calls["primary"] == 2  # 首次失败 + 二次失败后降级
    assert calls["backup"] == 1
    assert result == "备用工具结果"
    statuses = [e["status"] for e in events]
    assert "retrying" in statuses and "fallback" in statuses


def test_trace_runner_emits_spans():
    """P0-1：mock 模式下跑一场辩论，runner 收尾事件应含 trace span。"""
    from tests._p0_helpers import run_trace_graph

    run_trace_graph()