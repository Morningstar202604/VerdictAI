"""0.8.0 新特性测试：庭审阶段剧本（举证质证/交叉质证/最后陈述）与证据一键核验端点。"""

import pytest
from fastapi.testclient import TestClient

from app.agents.nodes import _phase_hint
from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


# ---------------- 阶段提示 ----------------

def test_round1_is_evidence_examination():
    h = _phase_hint(1, 3)
    assert "法庭调查" in h and "质证" in h and "E-0" in h


def test_round2_is_cross_exam():
    h = _phase_hint(2, 3)
    assert "交叉质证" in h and "点名" in h


def test_final_round_is_closing():
    h = _phase_hint(3, 3)
    assert "最后陈述" in h and "最终结论性意见" in h and "新论点" in h


def test_two_round_debate_has_no_cross_exam():
    # max_rounds=2 时第 2 轮即最后陈述，不设交叉质证
    assert _phase_hint(2, 2).startswith("（最后陈述·评议轮）")


# ---------------- 证据一键核验 ----------------

def test_evidence_audit_ok_case(client):
    r = client.post(
        "/api/cases/upload",
        json={
            "title": "核验正常案件",
            "summary": "摘要",
            "evidence": [
                {"id": "E-01", "type": "物证", "desc": "刀", "reliability": 0.9, "chain_intact": True},
                {"id": "E-02", "type": "书证", "desc": "合同", "reliability": 0.8, "chain_intact": True},
            ],
            "timeline": [{"time": "2026年3月12日 10:30", "event": "签约", "source": "卷宗"}],
        },
    )
    assert r.status_code == 200, r.text
    cid = r.json()["case"]["id"]
    a = client.get(f"/api/cases/{cid}/evidence-audit").json()
    assert a["ok"] is True and a["issues"] == []
    assert a["stats"]["count"] == 2
    assert a["stats"]["chain_flawed"] == 0
    assert a["stats"]["unparseable_time"] == 0


def test_evidence_audit_flags_problems(client):
    r = client.post(
        "/api/cases/upload",
        json={
            "title": "核验缺陷案件",
            "summary": "摘要",
            "evidence": [
                {"id": "E-01", "type": "物证", "desc": "刀", "reliability": 0.9, "chain_intact": False},
                {"id": "E-01", "type": "书证", "desc": "", "reliability": 0.5, "chain_intact": True},
                {"id": "X7", "type": "物证", "desc": "来源不明", "reliability": 0.4, "chain_intact": True},
            ],
            "timeline": [{"time": "案发当晚", "event": "事发", "source": "卷宗"}],
        },
    )
    assert r.status_code == 200, r.text
    cid = r.json()["case"]["id"]
    a = client.get(f"/api/cases/{cid}/evidence-audit").json()
    assert a["ok"] is False
    msgs = " | ".join(i["msg"] for i in a["issues"])
    assert "重复" in msgs          # E-01 重复
    assert "E-NN" in msgs          # X7 格式
    assert "缺少证据描述" in msgs
    assert a["stats"]["chain_flawed"] == 1
    assert a["stats"]["unparseable_time"] == 1


def test_evidence_audit_404_and_bad_id(client):
    assert client.get("/api/cases/no_such_case/evidence-audit").status_code == 404
    assert client.get("/api/cases/../evil/evidence-audit").status_code in (400, 404)
