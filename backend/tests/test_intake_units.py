"""纯函数单测：JSON 容错解析、案件 ID 校验与知识库检索。

_extract_json 的数组分支是纠错官节点的生命线——它只输出 JSON 数组，
解析层若只认 dict，矛盾清单会被静默清空。"""

from app.data.store import validate_id
from app.intake.processor import _extract_json
from app.legal.knowledge import search_knowledge


def test_extract_json_plain_object():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_code_block():
    assert _extract_json('```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}


def test_extract_json_double_encoded():
    assert _extract_json('{\\"a\\": \\"b\\"}') == {"a": "b"}


def test_extract_json_garbage_returns_none():
    assert _extract_json("完全不是 JSON 的内容") is None
    assert _extract_json("") is None


def test_validate_id_accepts_safe_ids():
    assert validate_id("case_001")
    assert validate_id("case-ab12CD")


def test_validate_id_rejects_path_traversal():
    assert not validate_id("../secret")
    assert not validate_id("a/b")
    assert not validate_id("")
    assert not validate_id("case..001")


def test_knowledge_search_hits_builtin():
    hits = search_knowledge("非法证据")
    assert hits
    assert any("第56条" in h["title"] for h in hits)


def test_knowledge_search_miss_returns_empty():
    assert search_knowledge("绝不存在的关键词xyz123") == []
    assert search_knowledge("") == []
