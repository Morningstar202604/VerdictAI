# -*- coding: utf-8 -*-
"""工具级指标：失败调用也必须累计调用数，否则 usage 面板成功率失真。"""

from app.agents import tools as _t


def test_tool_stats_counts_calls_on_error():
    _t.TOOL_STATS.clear()
    _t.tool_stats_record("demo", True, 10.0)  # calls=1, ok=1
    _t.tool_stats_record_error("demo", "boom")  # 修复后 calls=2, fail=1
    snap = _t.tool_stats_snapshot()["tools"]["demo"]
    assert snap["calls"] == 2
    assert snap["ok"] == 1
    assert snap["fail"] == 1
    # 修复前 fail 不累计 calls，success_rate 会被虚高到 1.0
    assert abs(snap["success_rate"] - 0.5) < 1e-6
    _t.TOOL_STATS.clear()
