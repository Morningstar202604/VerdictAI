"""API 冒烟测试：与 .github/workflows/ci.yml 的 smoke 断言保持同一覆盖面。

CONTRIBUTING 规定推送前必须跑 pytest，本文件让该规定覆盖到 CI 已有的
最低保证；更细的行为回归放在同目录其他测试文件中。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["mock"] is True


def test_cases_list_shape(client):
    r = client.get("/api/cases")
    assert r.status_code == 200
    assert "cases" in r.json()


def test_presets_builtin(client):
    r = client.get("/api/presets")
    assert r.status_code == 200
    presets = r.json()["presets"]
    assert "刑事·严格证据攻防" in presets
    assert "民事·责任划分" in presets


def test_knowledge_builtin_entries(client):
    r = client.get("/api/knowledge")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert entries
    assert all(e.get("title") and e.get("text") for e in entries)


def test_roles_roster(client):
    r = client.get("/api/roles")
    assert r.status_code == 200
    keys = {x["key"] for x in r.json()["roles"]}
    assert {
        "scene",
        "forensic",
        "evidence",
        "psych",
        "law",
        "prosecutor",
        "defense",
        "judge",
    } <= keys
