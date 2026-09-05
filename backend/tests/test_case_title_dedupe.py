"""案件标题去重回归测试。

修复前的两个症状：
1. 上传接口在判断条件里对同一文件句柄连续 json.load 两次，第二次必因
   文件指针在末尾抛错并被吞掉，同名计数永远为 0，"(副本N)" 后缀从不生成；
2. /api/cases/generate 先落盘模板再统计同源副本，模板把自己计入，
   第一个生成的示例案件就误带 "(副本)" 后缀。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


def _upload(client: TestClient, title: str, cid: str | None = None) -> dict:
    payload = {"title": title, "summary": "标题去重回归测试用案件"}
    if cid:
        payload["id"] = cid
    r = client.post("/api/cases/upload", json=payload)
    assert r.status_code == 200, r.text
    return r.json()["case"]


def test_upload_duplicate_titles_get_numbered_suffixes(client):
    assert _upload(client, "去重回归案件")["title"] == "去重回归案件"
    assert _upload(client, "去重回归案件")["title"] == "去重回归案件 (副本1)"
    assert _upload(client, "去重回归案件")["title"] == "去重回归案件 (副本2)"


def test_upload_same_id_reupload_not_counted_as_duplicate(client):
    """同一 ID 重新上传是覆盖而非新增，不得给自己加副本后缀。"""
    cid = "case_dedup_same"
    _upload(client, "同ID重传案件", cid=cid)
    again = _upload(client, "同ID重传案件", cid=cid)
    assert again["title"] == "同ID重传案件"


def test_generate_first_sample_has_no_duplicate_suffix(client):
    r = client.post("/api/cases/generate")
    assert r.status_code == 200, r.text
    assert "副本" not in r.json()["case"]["title"], r.json()["case"]["title"]


def test_generate_copies_numbered_after_template(client):
    """连续生成的副本编号逐一递增（无后缀 → "(副本)" → "(副本2)" → …）。
    会话级临时 DATA_DIR 可能已含前序用例生成的同题案件，因此只断言
    相对递增关系，不断言绝对后缀。"""
    import re

    def _num(title: str):
        m = re.search(r"\(副本(\d*)\)\s*$", title)
        if not m:
            return 0
        return int(m.group(1)) if m.group(1) else 1

    t1 = client.post("/api/cases/generate").json()["case"]["title"]
    t2 = client.post("/api/cases/generate").json()["case"]["title"]
    t3 = client.post("/api/cases/generate").json()["case"]["title"]
    base = re.sub(r"\s*\(副本\d*\)\s*$", "", t1)
    for prev, nxt in ((t1, t2), (t2, t3)):
        assert re.sub(r"\s*\(副本\d*\)\s*$", "", nxt) == base
        assert _num(nxt) == _num(prev) + 1, (prev, nxt)
