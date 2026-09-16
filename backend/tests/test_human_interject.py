# -*- coding: utf-8 -*-
"""人工介入（插话）投递语义测试。

背景：插话此前存在"静默丢弃"——辩论未开始/已终结时队列不存在，
`push_human` 直接 return，用户以为插进去了，实际毫无反馈。
现要求 push_human 返回投递结果，调用方据此回执。
"""
from __future__ import annotations

import asyncio

from app.ws.manager import ConnectionManager


def test_push_human_returns_false_when_no_session():
    """无进行中辩论时投递失败，必须返回 False（供上层回执）。"""
    m = ConnectionManager()

    async def run():
        return await m.push_human("no-such-session", "请核查保管链")

    assert asyncio.run(run()) is False


def test_push_human_returns_true_and_enqueues():
    """辩论进行中投递成功，返回 True 且可被取出。"""
    m = ConnectionManager()
    sid = "s1"
    m.human_queues[sid] = asyncio.Queue()

    async def run():
        ok = await m.push_human(sid, "请评估替代解释")
        return ok, m.pop_human(sid)

    ok, got = asyncio.run(run())
    assert ok is True
    assert got == "请评估替代解释"


def test_pop_human_is_nonblocking_and_drains_once():
    """pop_human 非阻塞；取完后再次调用返回 None（仅消费一次）。"""
    m = ConnectionManager()
    sid = "s2"
    m.human_queues[sid] = asyncio.Queue()

    async def run():
        await m.push_human(sid, "one")
        await m.push_human(sid, "two")
        return m.pop_human(sid), m.pop_human(sid), m.pop_human(sid)

    first, second, third = asyncio.run(run())
    assert (first, second, third) == ("one", "two", None)


def test_drain_human_returns_all_and_empties():
    """终结时 drain_human 取走全部未消费消息，用于提示用户。"""
    m = ConnectionManager()
    sid = "s3"
    m.human_queues[sid] = asyncio.Queue()

    async def run():
        for t in ("a", "b", "c"):
            await m.push_human(sid, t)
        drained = m.drain_human(sid)
        after = m.drain_human(sid)
        return drained, after

    drained, after = asyncio.run(run())
    assert drained == ["a", "b", "c"]
    assert after == []


def test_drain_human_no_session_is_safe():
    m = ConnectionManager()
    assert m.drain_human("missing") == []


def test_push_final_uses_separate_queue():
    """subtype=final 走落槌队列，与中途插话队列互不干扰。"""
    m = ConnectionManager()
    sid = "s4"
    m.human_queues[sid] = asyncio.Queue()
    m.final_queues[sid] = asyncio.Queue()

    async def run():
        await m.push_human(sid, "中途意见", "intervene")
        await m.push_human(sid, "最终裁决", "final")
        return m.pop_human(sid), m.final_queues[sid].get_nowait()

    mid, final = asyncio.run(run())
    assert mid == "中途意见"
    assert final == "最终裁决"
