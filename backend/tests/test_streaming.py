"""真流式输出测试。

stream_or_invoke 的三条铁律：
1. 聚合文本 == 各增量拼接（一字不丢、不重复）；
2. 端点首块前失败 → 记入不支持名单并抛出，调用方可回退非流式；
3. 已流出部分内容后失败 → 直接抛出（重试会导致用户看到重复发言）。
本地引擎 stream:true 必须返回 OpenAI 兼容 SSE。"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.models import llm as L
from app.models.llm import MockChatModel, get_llm, stream_enabled, stream_or_invoke


def test_stream_enabled_auto_is_off_for_mock():
    assert stream_enabled({"llm_provider": "mock"}) is False
    assert stream_enabled({"llm_provider": "openai"}) is True
    assert stream_enabled({"llm_provider": "mock", "stream_experts": "on"}) is True
    assert stream_enabled({"llm_provider": "openai", "stream_experts": "off"}) is False


def test_stream_aggregation_matches_content():
    llm = MockChatModel()
    got = []

    async def run():
        return await stream_or_invoke(llm, [{"role": "user", "content": "任意案情"}], on_chunk=got.append)

    merged = asyncio.run(run())
    assert "".join(got) == merged.text() if hasattr(merged, "text") else "".join(got) == str(merged.content)
    assert "".join(got) != ""  # mock 的 astream 按「，」分片，必有增量


def test_stream_failure_before_first_chunk_marks_unsupported(monkeypatch):
    class BrokenStream:
        async def astream(self, messages):
            raise RuntimeError("no sse support")
            yield  # pragma: no cover

        async def ainvoke(self, messages):
            return "整段结果"

    key = "broken-endpoint"
    monkeypatch.delitem(L._stream_unsupported, key, raising=False)
    with pytest.raises(RuntimeError):
        asyncio.run(stream_or_invoke(BrokenStream(), [], key=key))
    assert key in L._stream_unsupported
    # 回退路径：不支持流式的端点第二次直接走非流式
    out = asyncio.run(stream_or_invoke(BrokenStream(), [], key=key))
    assert out == "整段结果"


def test_partial_stream_failure_does_not_retry(monkeypatch):
    """已流出部分内容后失败：必须抛出（调用方按专家失败处理），不得重试造成重复。"""
    calls = {"n": 0}

    class PartialFail:
        def astream(self, messages):
            calls["n"] += 1
            async def gen():
                yield _mk_chunk("前半段")
                raise RuntimeError("mid-stream drop")
            return gen()

    with pytest.raises(RuntimeError):
        asyncio.run(stream_or_invoke(PartialFail(), []))
    assert calls["n"] == 1  # 只尝试了一次


def _mk_chunk(text):
    from langchain_core.messages import AIMessageChunk

    return AIMessageChunk(content=text)


def test_engine_sse_format():
    from ai_engine.server import app as engine_app

    client = TestClient(engine_app)
    r = client.post(
        "/v1/chat/completions",
        json={"model": "verdict-local", "stream": True,
              "messages": [{"role": "system", "content": "你是法医专家"},
                           {"role": "user", "content": "请发言"}]},
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    assert body.rstrip().endswith("data: [DONE]")
    deltas = []
    for line in body.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            chunk = json.loads(line[len("data: "):])
            piece = chunk["choices"][0]["delta"].get("content")
            if piece:
                deltas.append(piece)
    assert "".join(deltas), "SSE 增量拼接不应为空"


def test_engine_non_stream_still_json():
    from ai_engine.server import app as engine_app

    client = TestClient(engine_app)
    r = client.post(
        "/v1/chat/completions",
        json={"model": "verdict-local",
              "messages": [{"role": "system", "content": "你是法医专家"},
                           {"role": "user", "content": "请发言"}]},
    )
    assert r.status_code == 200
    assert r.json()["choices"][0]["finish_reason"] == "stop"


def test_settings_stream_experts_validated(monkeypatch):
    monkeypatch.setattr(settings, "stream_experts", "bogus")
    from app.config import Settings
    s = Settings(stream_experts="bogus")
    assert s.stream_experts == "auto"
    assert Settings(stream_experts="on").stream_experts == "on"
