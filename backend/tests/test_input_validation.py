"""外部输入到文件系统的边界测试。

案件 ID / 会话 ID 会参与服务端文件名拼接（cases/*.json、debates/*.json），
一律须经 validate_id；否则 "../" 类值可写出数据目录之外（路径穿越）。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.mark.parametrize(
    "bad_id",
    ["../../evil", "a/b", "..", "case..001", "case-../x"],
)
def test_upload_rejects_unsafe_case_id(client, bad_id):
    r = client.post("/api/cases/upload", json={"id": bad_id, "title": "穿越测试"})
    assert r.status_code == 400, r.text
    # 被拒绝的 ID 不应产生任何落盘文件
    listing = client.get("/api/cases").json()["cases"]
    assert all(c["id"] != bad_id for c in listing)


def test_upload_accepts_safe_custom_id(client):
    r = client.post("/api/cases/upload", json={"id": "case_custom01", "title": "自定义ID"})
    assert r.status_code == 200, r.text
    assert r.json()["case"]["id"] == "case_custom01"


def test_upload_generates_id_when_missing(client):
    r = client.post("/api/cases/upload", json={"title": "无ID案件"})
    assert r.status_code == 200, r.text
    assert r.json()["case"]["id"].startswith("case_")
