# -*- coding: utf-8 -*-
"""法条引用核查引擎 + 路由测试（引用信号灯 / 幻觉防火墙）。"""

from app.legal.cite_check import (
    check_text,
    check_texts,
    chn_to_int,
    extract_citations,
    known_statute_index,
    normalize_law,
    statute_key,
)
from app.routers.legal import router as legal_router  # noqa: F401 保证路由可导入


# ---------------- 中文数字 ----------------

def test_chn_to_int_basic():
    assert chn_to_int("266") == 266
    assert chn_to_int("二百六十六") == 266
    assert chn_to_int("十") == 10
    assert chn_to_int("十五") == 15
    assert chn_to_int("五十") == 50
    assert chn_to_int("一千二百六十") == 1260
    assert chn_to_int("二百九十九") == 299
    assert chn_to_int("〇") == 0
    assert chn_to_int("abc") is None
    assert chn_to_int("") is None


# ---------------- 规范化 ----------------

def test_normalize_law():
    assert normalize_law("《中华人民共和国刑法》") == "刑法"
    assert normalize_law("刑法") == "刑法"
    assert normalize_law("《 刑事诉讼法 》") == "刑事诉讼法"
    assert normalize_law("刑诉法") == "刑事诉讼法"
    assert normalize_law("中华人民共和国民法典") == "民法典"


def test_statute_key():
    assert statute_key("《中华人民共和国刑法》", "第二百六十六") == "刑法|第266条"
    assert statute_key("刑法", "266") == "刑法|第266条"
    assert statute_key("刑诉法", "五十五") == "刑事诉讼法|第55条"
    assert statute_key("刑法", "一百九十一", "之一") == "刑法|第191条之一"
    assert statute_key("", "5") == ""
    assert statute_key("刑法", "abc") == ""


# ---------------- 引用提取 ----------------

def test_extract_citations_mixed_styles():
    text = ("依据《中华人民共和国刑法》第266条构成诈骗；"
            "同时刑法第191条之一适用洗钱；"
            "程序上参照《刑事诉讼法》第55条的证明标准，"
            "并引用刑诉法第56条排除规则。")
    cites = extract_citations(text)
    keys = [c["key"] for c in cites]
    assert keys == ["刑法|第266条", "刑法|第191条之一",
                    "刑事诉讼法|第55条", "刑事诉讼法|第56条"]
    # 保序去重
    dup = extract_citations("刑法第266条……《刑法》第二百六十六条")
    assert len(dup) == 1
    assert dup[0]["article"] == 266


def test_extract_citations_ignores_non_law():
    assert extract_citations("第三人称视角，普通人第10条街道") == []
    assert extract_citations("") == []


# ---------------- 已知法条索引与核查 ----------------

CASE_STATUTES = [
    {"id": "S-01", "name": "《刑法》第266条", "text": "诈骗……"},
    {"id": "S-02", "name": "《刑法》第191条", "text": "洗钱……"},
]


def test_known_index_contains_case_and_builtin():
    idx = known_statute_index(CASE_STATUTES)
    assert idx["刑法|第266条"]["source"] == "case"
    assert idx["刑法|第191条"]["source"] == "case"
    # 内置库：刑事诉讼法第50/55/56条、刑法第232条等
    assert idx["刑事诉讼法|第55条"]["source"] == "builtin"
    assert idx["刑法|第232条"]["source"] == "builtin"


def test_check_text_signal_lights():
    idx = known_statute_index(CASE_STATUTES)
    r = check_text("依《刑法》第266条定诈骗，另涉《刑法》第999条（虚构）", idx)
    by_key = {c["key"]: c for c in r["citations"]}
    assert by_key["刑法|第266条"]["status"] == "verified"
    assert by_key["刑法|第266条"]["source"] == "case"
    assert by_key["刑法|第999条"]["status"] == "unverified"
    assert r["verified"] == 1 and r["unverified"] == 1


def test_check_texts_summary():
    out = check_texts(["刑法第266条", "刑事诉讼法第55条", "无引用文本"], CASE_STATUTES)
    assert out["stats"]["texts"] == 3
    assert out["stats"]["verified"] == 2
    assert out["stats"]["unverified"] == 0
    assert out["stats"]["unique_citations"] == 2


# ---------------- 路由 ----------------

def test_cite_check_endpoints():
    from fastapi.testclient import TestClient
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(legal_router)
    client = TestClient(app)

    # known-statutes：无 case_id
    r = client.get("/api/legal/known-statutes")
    assert r.status_code == 200
    body = r.json()
    assert body["builtin_count"] > 0
    keys = {s["key"] for s in body["statutes"]}
    assert "刑事诉讼法|第55条" in keys

    # known-statutes：不存在的案件
    r = client.get("/api/legal/known-statutes", params={"case_id": "no_such_case"})
    assert r.status_code == 404

    # cite-check：正常（内置库命中 → verified）
    r = client.post("/api/legal/cite-check",
                    json={"texts": ["依据《刑事诉讼法》第55条"], "case_id": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["stats"]["verified"] == 1
    # 卷宗法条命中走 check_texts 单元测试覆盖（test_check_texts_summary）

    # cite-check：参数错误
    assert client.post("/api/legal/cite-check", json={"texts": "bad"}).status_code == 400
    assert client.post("/api/legal/cite-check",
                       json={"texts": ["x"], "case_id": "no_such_case"}).status_code == 404
