"""静态数据暴露面测试：只有案件图表资产可被浏览器取到，
data/ 下的私有存储（agent_config、知识库、辩论记录、presets）
必须没有任何 URL 可直达。"""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


def test_case_chart_asset_served(client):
    r = client.post("/api/cases/generate")
    assert r.status_code == 200, r.text
    charts = r.json()["case"].get("charts") or {}
    assert charts, "示例案件应生成图表"
    for _, url in charts.items():
        assert client.get(url).status_code == 200, url


def test_private_stores_not_reachable(client):
    # 无口令（开放模式）下也必须 404：这些文件此前挂在 /static/data 下可被整目录拉走
    for path in (
        "/static/data/agent_config.json",
        "/static/data/knowledge_base.json",
        "/static/data/presets.json",
        "/static/data/debates/whatever.json",
        "/static/data/cases/some_case.json",
    ):
        assert client.get(path).status_code == 404, path


def test_upload_case_chart_served_after_upload(client):
    r = client.post(
        "/api/cases/upload",
        json={
            "title": "暴露面测试案件",
            "summary": "验证上传案件的图表可被访问",
            "timeline": [{"time": "10:00", "event": "事件", "source": "测试"}],
        },
    )
    assert r.status_code == 200, r.text
    for _, url in (r.json()["case"].get("charts") or {}).items():
        assert client.get(url).status_code == 200, url
