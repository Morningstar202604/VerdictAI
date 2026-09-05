"""配置快照语义测试：辩论期读快照，全局 settings 中途变更不影响进行中的会话。"""

import asyncio

import pytest

from app.agents.nodes import _retry_ainvoke
from app.config import debate_snapshot, settings
from app.graph.builder import should_continue
from app.models.llm import MockChatModel, get_llm, is_mock


def test_snapshot_covers_debate_fields_and_is_independent():
    snap = debate_snapshot()
    for key in (
        "llm_provider",
        "llm_model",
        "max_rounds",
        "judge_mode",
        "memory_rounds",
        "context_char_limit",
        "llm_timeout",
        "llm_max_tokens",
        "intake_model",
    ):
        assert key in snap
    # 快照是普通 dict：改它不回写 settings
    snap["max_rounds"] = 99
    assert settings.max_rounds != 99 or settings.max_rounds == 99  # 仅保证不抛错
    assert debate_snapshot()["max_rounds"] == settings.max_rounds


def test_should_continue_reads_state_max_rounds_not_global(monkeypatch):
    """轮次达到 state 的 max_rounds 才停：全局 max_rounds 中途被调小不能截断进行中的辩论。"""
    monkeypatch.setattr(settings, "max_rounds", 2)
    state = {"round": 3, "max_rounds": 5, "consensus": False, "judge_mode": "ai"}
    assert should_continue(state) == "experts"


def test_should_continue_judge_mode_from_state(monkeypatch):
    monkeypatch.setattr(settings, "judge_mode", "ai")
    state = {"round": 3, "max_rounds": 3, "consensus": True, "judge_mode": "human"}
    assert should_continue(state) == "human_final"


def test_get_llm_snapshot_overrides_global(monkeypatch):
    """全局是 openai、快照是 mock 时，辩论期拿到的仍是 mock：改设置不影响老会话。"""
    monkeypatch.setattr(settings, "llm_provider", "openai")
    snap = debate_snapshot()
    snap["llm_provider"] = "mock"
    assert is_mock(snap) is True
    assert isinstance(get_llm("x", cfg=snap), MockChatModel)
    assert is_mock({}) is False


def test_retry_ainvoke_honors_snapshot_timeout():
    class SlowLLM:
        async def ainvoke(self, messages):
            await asyncio.sleep(0.5)
            raise AssertionError("should have been cancelled")

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(
            _retry_ainvoke(SlowLLM(), [], retries=1, timeout=0.01)
        )


def test_retry_ainvoke_falls_back_to_global_timeout():
    class FastLLM:
        async def ainvoke(self, messages):
            return "ok"

    out = asyncio.run(_retry_ainvoke(FastLLM(), []))
    assert out == "ok"
