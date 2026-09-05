"""存储索引缓存测试：列表接口按 (mtime, size) 增量缓存，
文件修改/删除后自动失效；辩论列表按开始时间排序、容忍损坏文件。"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.data.store import atomic_write_json
from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


def _upload(client, cid, title):
    r = client.post(
        "/api/cases/upload", json={"id": cid, "title": title, "summary": "索引测试"}
    )
    assert r.status_code == 200, r.text


def test_cases_list_reflects_update_and_delete(client):
    _upload(client, "case_idx_a", "索引案件A")
    _upload(client, "case_idx_b", "索引案件B")
    titles = {c["id"]: c["title"] for c in client.get("/api/cases").json()["cases"]}
    assert titles["case_idx_a"] == "索引案件A"

    # 覆盖同一 ID（mtime 变化）：缓存必须失效并反映新标题
    _upload(client, "case_idx_a", "索引案件A改")
    titles = {c["id"]: c["title"] for c in client.get("/api/cases").json()["cases"]}
    assert titles["case_idx_a"] == "索引案件A改"

    # 删除后从列表消失（缓存被清理）
    r = client.delete("/api/cases/case_idx_a")
    assert r.status_code == 200, r.text
    ids = {c["id"] for c in client.get("/api/cases").json()["cases"]}
    assert "case_idx_a" not in ids
    assert "case_idx_b" in ids


def _write_debate(session_id, started_at):
    atomic_write_json(
        os.path.join(settings.data_dir, "debates", f"{session_id}.json"),
        {
            "session_id": session_id,
            "case_title": f"案件-{session_id}",
            "started_at": started_at,
            "model": "mock",
            "rounds": 2,
            "final_verdict": {"truth_hypothesis": "推定"},
            "events": [],
        },
        indent=None,
    )


def test_debates_list_sorted_by_started_at(client):
    os.makedirs(os.path.join(settings.data_dir, "debates"), exist_ok=True)
    _write_debate("sessidx0001", "2026-09-06T10:00:00Z")
    _write_debate("sessidx0002", "2026-09-06T11:00:00Z")
    rows = client.get("/api/debates").json()
    ids = [r["session_id"] for r in rows if r["session_id"].startswith("sessidx")]
    assert ids.index("sessidx0002") < ids.index("sessidx0001")


def test_debates_list_ignores_corrupt_file(client):
    debates_dir = Path(settings.data_dir) / "debates"
    debates_dir.mkdir(parents=True, exist_ok=True)
    # 半截 JSON：列表必须跳过而不是抛错
    (debates_dir / "sesscorrupt.json").write_text(
        '{"session_id": "sesscorrupt", "started_at"', encoding="utf-8"
    )
    rows = client.get("/api/debates").json()
    assert all(r["session_id"] != "sesscorrupt" for r in rows)


def test_debates_limit_respected(client):
    os.makedirs(os.path.join(settings.data_dir, "debates"), exist_ok=True)
    for i in range(3):
        _write_debate(f"sesslim{i:04d}", f"2026-09-06T12:0{i}:00Z")
    rows = client.get("/api/debates?limit=2").json()
    mine = [r["session_id"] for r in rows if r["session_id"].startswith("sesslim")]
    assert len(mine) == 2
