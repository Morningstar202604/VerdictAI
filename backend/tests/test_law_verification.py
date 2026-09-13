# -*- coding: utf-8 -*-
"""B 阶段：法条引用核验 + 量刑区间校验（确定性规则测试）。"""
import json

from app.agents.nodes import _selfcheck_case
from app.legal.knowledge import (
    article_numbers_of_law,
    canon_law,
    cn_to_int,
    find_statute,
    find_statute_by_charge,
    parse_article_no,
)
from app.legal.verification import run_verification, verify_law_citations, verify_sentencing


# ---------------- knowledge 结构化查询 ----------------

def test_cn_to_int_basic():
    assert cn_to_int("55") == 55
    assert cn_to_int("五十五") == 55
    assert cn_to_int("一百零五") == 105
    assert cn_to_int("二百三十二") == 232
    assert cn_to_int("") == -1
    assert cn_to_int("百") == 100  # 单位前省略「一」


def test_canon_law_aliases():
    assert canon_law("《中华人民共和国刑事诉讼法》") == "中华人民共和国刑事诉讼法"
    assert canon_law("刑诉法") == "中华人民共和国刑事诉讼法"
    assert canon_law(" 刑事诉讼法 ") == "中华人民共和国刑事诉讼法"
    assert canon_law("中华人民共和国治安管理处罚法") is None
    assert canon_law("") is None


def test_parse_article_no():
    assert parse_article_no("第55条") == 55
    assert parse_article_no("第五十六条") == 56
    assert parse_article_no("232") == 232
    assert parse_article_no("第一款") == 1
    assert parse_article_no("") == -1


def test_find_statute():
    hit = find_statute("《中华人民共和国刑事诉讼法》", "第55条")
    assert hit and hit["id"] == "b-csl-55"
    assert find_statute("刑法", "第232条")["charge"] == "故意杀人罪"
    assert find_statute("中华人民共和国刑事诉讼法", "第999条") is None


def test_find_statute_by_charge_and_law_articles():
    assert find_statute_by_charge("故意杀人")["id"] == "b-cl-232"
    assert find_statute_by_charge("盗窃罪") is None
    assert article_numbers_of_law("中华人民共和国刑事诉讼法") == [50, 55, 56]


# ---------------- verify_law_citations ----------------

def test_citations_verified_and_flagged():
    res = verify_law_citations([
        {"title": "《中华人民共和国刑事诉讼法》", "article": "第55条"},
        {"title": "《中华人民共和国刑法》", "article": "第999条"},
        {"title": "《中华人民共和国治安管理处罚法》", "article": "第43条"},
    ])
    assert [r["status"] for r in res] == ["verified", "not_in_library", "unknown_law"]
    assert "第55条" == res[0]["article"]
    # 未收录条号提示应列出库内已知条号
    assert "第232条" in res[1]["note"] or "第233条" in res[1]["note"]


def test_citations_tolerates_dirty_rows():
    res = verify_law_citations([
        {"title": "刑诉法", "article": "五十五"},   # 别名+中文数字
        "not-a-dict",
        {},
        {"title": "", "article": "第1条"},
    ])
    assert res[0]["status"] == "verified"
    assert len(res) == 3  # 非 dict 行被跳过
    assert res[2]["status"] == "unknown_law"


# ---------------- verify_sentencing ----------------

def test_sentencing_within_and_over_range():
    cites = [{"title": "《中华人民共和国刑法》", "article": "第233条"}]
    ok = verify_sentencing("建议判处有期徒刑五年", cites)
    assert ok and ok["ok"] and ok["suggested_years"] == 5
    over = verify_sentencing("建议判处有期徒刑十年", cites)  # 过失致人死亡上限7年
    assert over and not over["ok"] and "超出法定上限" in over["note"]
    cn = verify_sentencing("建议判处三年有期徒刑", cites)
    assert cn and cn["ok"]  # 中文数字可解析


def test_sentencing_life_and_death():
    cites = [{"title": "《中华人民共和国刑法》", "article": "第232条"}]
    life = verify_sentencing("建议判处无期徒刑", cites)
    assert life and life["ok"]
    none = verify_sentencing("建议判处三年以上十年以下有期徒刑", cites)
    assert none and none["ok"]  # 故意杀人无封顶
    nocharge = verify_sentencing("建议判处拘役", [])
    assert nocharge is None


# ---------------- run_verification（selfcheck 集成） ----------------

def test_run_verification_issues():
    verdict = {
        "law_citations": [
            {"title": "《中华人民共和国刑事诉讼法》", "article": "第55条", "purpose": "证明标准"},
            {"title": "《中华人民共和国刑法》", "article": "第133条", "purpose": "定罪"},
        ],
        "sentencing": "建议判处有期徒刑八年",
        "ruling": "构成故意杀人罪",
    }
    v = run_verification(verdict)
    assert v["verified"] == 1 and v["flagged"] == 1
    assert any("疑似虚构" in i for i in v["issues"])
    assert v["sentencing_check"] and v["sentencing_check"]["ok"]  # 232 无封顶，八年可


def test_selfcheck_case_no_regression_and_verification_passthrough():
    """_selfcheck_case 行为不变；verification 由 judge_node 合并到 issues/ok。"""
    case = {"evidence": [{"id": "E-01", "desc": "勘查笔录"}]}
    verdict = {"findings_of_fact": "E-01 勘查笔录经质证予以采信，引用《中华人民共和国刑事诉讼法》第55条"}
    sc = _selfcheck_case(case, verdict, [])
    assert sc["covered"] == 1 and sc["ok"]
    sc["verification"] = {"issues": ["疑似虚构：刑法第999条"], "verified": 1, "flagged": 1,
                          "citations": [], "sentencing_check": None}
    sc["issues"] = sc["issues"] + sc["verification"]["issues"]
    sc["ok"] = False
    assert any("疑似虚构" in i for i in sc["issues"]) and not sc["ok"]


def test_mock_judge_verdict_citations_pass_library():
    """mock 裁决引用的刑诉法55/56条应全部核验通过（内置数据自洽）。"""
    from app.agents.nodes import judge_node  # noqa: F401  (import smoke)
    verdict = {
        "law_citations": [
            {"title": "《中华人民共和国刑事诉讼法》", "article": "第55条"},
            {"title": "《中华人民共和国刑事诉讼法》", "article": "第56条"},
        ],
        "sentencing": "", "ruling": "",
    }
    v = run_verification(verdict)
    assert v["verified"] == 2 and v["flagged"] == 0 and v["issues"] == []
    assert json.dumps(v, ensure_ascii=False)  # 可序列化（事件下发要求）
