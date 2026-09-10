# -*- coding: utf-8 -*-
"""M1.5 评估回归集（golden assertions）。

覆盖 M1.5 六项新增能力的确定性断言，全部离线、无模型调用：
1.5.1 意图路由（门禁/案由/置信度/实体槽位）
1.5.2 报告导出（markdown 组装幂等、DOCX 缺失降级不报错）
1.5.3 证据时间线（确定性排序 + 端点契约）
1.5.4 相似案例推荐（无其他案例时安全空返回 + 端点契约）
1.5.5 结构清洗回归（坏结构不抛异常）
1.5.6 搜索缓存与 URL 去重（同一查询命中缓存、归一化去重）
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.data import generate_case

THEFT_TEXT = "被告人张三于2026年3月14日深夜潜入位于西山区滨江别墅，窃取现金3万元与两部手机"


# ---------------- 1.5.1 意图路由 ----------------

def test_intent_router_theft():
    from app.models.schemas import intent_router

    r = intent_router(THEFT_TEXT)
    assert r["relevant"] is True
    assert r["cause"] == "盗窃案"
    assert r["suggested_preset"]
    assert r["confidence"] >= 0.7
    assert r["entities"]["parties"] == ["张三"]


def test_intent_router_gate_rejects_smalltalk():
    from app.models.schemas import intent_router

    for t in ("你好", "谢谢", "哈哈", "测试一下"):
        r = intent_router(t)
        assert r["relevant"] is False, t
        assert r["reject_reason"]


def test_extract_entity_slots():
    from app.models.schemas import extract_entities

    e = extract_entities(THEFT_TEXT)
    assert "张三" in e["parties"]
    assert any("2026" in d for d in e["datetimes"])
    assert any(a.endswith(("万", "元", "万元", "块")) for a in e["amounts"])
    assert any("西山区" in p or "别墅" in p for p in e["places"])


def test_mixed_input_kept_relevant():
    """含案件关键词的输入即使包含无关词也应判相关（宽松策略）。"""
    from app.models.schemas import intent_router

    r = intent_router("早上好，我有个案子：邻居半夜殴打我父亲致轻伤")
    assert r["relevant"] is True
    assert r["cause"] == "故意伤害案"


# ---------------- 1.5.5 结构清洗回归 ----------------

def test_clean_contradictions_tolerates_bad_party_field():
    from app.models.schemas import clean_contradictions

    out = clean_contradictions([{"round": 1, "issue": "A 与 B 陈述矛盾", "parties": "bad_type"}])
    assert out == [{"round": 1, "issue": "A 与 B 陈述矛盾", "parties": []}]


def test_clean_verdict_falls_back_on_garbage():
    from app.models.schemas import clean_verdict

    out = clean_verdict({"truth_hypothesis": None, "evidence_chain": "oops"})
    assert isinstance(out["evidence_chain"], list)
    assert out["disclaimer"]


# ---------------- 1.5.2 报告导出 ----------------

def _make_case():
    """生成一份可落盘的示例案件（写进测试临时 DATA_DIR）。"""
    path = generate_case.generate()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_report_markdown_smoke():
    from app.routers.reports import render_markdown

    case = _make_case()
    fake = {
        "case_title": case.get("title"),
        "started_at": "2026-09-10T00:00:00Z",
        "model": "mock",
        "rounds": 3,
        "usage": {"calls": 6},
        "final_verdict": {
            "truth_hypothesis": "真相假设",
            "evidence_chain": ["E-01 支撑"],
            "doubts": ["存疑"],
            "recommendation": "建议",
            "disclaimer": "免责",
        },
        "events": [
            {"kind": "agent_note", "role": "field", "name": "现场勘查官",
             "note": {"claim": "现场有争议"}},
            {"kind": "critic_end", "round": 1,
             "contradictions": [{"issue": "监控时间与供述不符"}]},
            {"kind": "verdict", "verdict": {"evidence_chain": []}},
        ],
    }
    md = render_markdown(fake)
    for token in ("庭审核查报告", "现场勘查官", "监控时间与供述不符", "真相假设", "免责"):
        assert token in md, token


def test_report_docx_fallback_never_raises():
    """DOCX 渲染缺失 python-docx 时返回 None；有则返回 bytes。"""
    from app.routers.reports import render_docx

    out = render_docx({"case_title": "x", "final_verdict": {}, "events": []})
    assert out is None or isinstance(out, bytes)


# ---------------- 1.5.3 / 1.5.4 端点契约 ----------------

def test_timeline_and_similar_endpoints():
    from app.main import app

    case = _make_case()
    cid = case.get("id") or "case_001"
    client = TestClient(app)

    r = client.get(f"/api/cases/{cid}/timeline")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "timeline" in body
    times = [t["time"] for t in body["timeline"] if t.get("time")]
    assert times == sorted(times)

    r = client.get(f"/api/cases/{cid}/similar")
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["similar"], list)


# ---------------- 1.5.6 搜索缓存与去重 ----------------

def test_search_cache_hit_and_url_dedup(monkeypatch):
    import app.agents.search as search_mod

    fetched = {"n": 0}

    def fake_searxng(q, timeout):
        fetched["n"] += 1
        return [
            {"title": "a", "url": "https://x.com/a?src=1", "snippet": "s1"},
            {"title": "b", "url": "https://x.com/a", "snippet": "s2"},  # 同源不同串 → 去重
            {"title": "c", "url": "https://x.com/c", "snippet": "s3"},
        ]

    monkeypatch.setattr(search_mod, "search_searxng", fake_searxng)
    monkeypatch.setattr(search_mod, "search_bing_html", lambda q, t: [])
    monkeypatch.setattr(search_mod.settings, "search_provider", "searxng")
    search_mod._CACHE.clear()

    first = search_mod.web_search("正当防卫 区分", limit=5)
    assert len(first) == 2  # b 被合并，只留 a、c
    assert fetched["n"] == 1
    second = search_mod.web_search("正当防卫 区分", limit=5)
    assert fetched["n"] == 1  # 命中缓存，未再抓取
    assert second == first
    search_mod._CACHE.clear()