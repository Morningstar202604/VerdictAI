"""P2 平台对标基础设施测试：
- 结构化输出统一设施（structured_call：schema 路径 + 契约修复路径）
- 工具并行编排（多 tool_calls gather 执行且事件完整）
- 工具级指标（tool_stats_snapshot）
- API 限流（rate_limit_middleware 429）
- 成本核算（estimate_cost）
- 提示词版本 registry（prompts.resolve / agent_config 持久化）
- 评测集加载（evaluate.py --dataset 关联函数）
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config import settings


# ------------------------- P2-1 结构化输出 -------------------------


class _StubModel:
    """模拟无结构化输出能力的普通模型：只走契约+修复路径。"""

    model_name = "stub"
    calls = 0

    def __init__(self, good=None):
        self.good = good or '{"claim": "测试主张", "evidence_ids": ["E-01"], "doubts": [], "implicates": []}'

    async def ainvoke(self, messages):
        type(self).calls += 1
        if type(self).calls == 1:
            return type("R", (), {"content": "不是 JSON"})()
        return type("R", (), {"content": self.good})()


def test_structured_call_contract_repair():
    """契约路径：首次解析失败 → 自动修复一次后成功（Self-Correct）。"""
    from langchain_core.messages import HumanMessage

    from app.models.llm import structured_call

    def _notes(text):
        import json

        obj = json.loads(text)
        if not isinstance(obj, dict) or "claim" not in obj:
            raise ValueError("需要 claim 字段")
        return obj

    _StubModel.calls = 0
    events = []

    async def sink(e):
        events.append(e)

    out = asyncio.run(
        structured_call(
            _StubModel(),
            [HumanMessage(content="做笔记")],
            parse=_notes,
            repair_hint="请输出 JSON 对象",
            sink=sink,
            role_key="note",
        )
    )
    assert out and out.get("claim") == "测试主张"
    statuses = [(e["kind"], e.get("ok")) for e in events if e["kind"] == "structured"]
    assert ("structured", True) in statuses


def test_structured_call_with_schema_path():
    """schema 路径：Pydantic 契约强制（返回 model_dump dict）。"""
    from langchain_core.messages import HumanMessage

    from app.models.llm import structured_call
    from app.models.schemas import NoteItem

    class _SchemaModel:
        model_name = "schema-stub"

        def with_structured_output(self, schema):
            class _Bound:
                async def ainvoke(self, messages):
                    return NoteItem(
                        claim="结构化主张", evidence_ids=["E-02"]
                    )

            return _Bound()

    out = asyncio.run(
        structured_call(
            _SchemaModel(),
            [HumanMessage(content="做笔记")],
            parse=lambda t: t,
            with_schema=NoteItem,
        )
    )
    assert out and out.get("claim") == "结构化主张"
    assert out.get("evidence_ids") == ["E-02"]


def test_parse_helpers_strict():
    """严格解析：非法结构抛异常（供自动修复触发）。"""
    from app.agents.nodes import _parse_contradictions, _parse_verdict

    with pytest.raises(ValueError):
        _parse_verdict("不是 JSON")
    with pytest.raises(ValueError):
        _parse_verdict("[1,2,3]")
    bad = _parse_contradictions('[{"issue":"a","parties":["evidence"]}]')
    assert bad and bad[0]["issue"] == "a"
    with pytest.raises(ValueError):
        _parse_contradictions('{"foo": 1}')  # 对象里没有数组字段


# ------------------------- P2-3 工具级指标 -------------------------


def test_tool_stats_record_and_snapshot():
    from app.agents.tools import (
        TOOL_STATS,
        tool_stats_record,
        tool_stats_record_error,
        tool_stats_snapshot,
    )

    TOOL_STATS.clear()
    tool_stats_record("web_search", True, 120.0)
    tool_stats_record("web_search", True, 80.0)
    tool_stats_record("web_search", False, 200.0)
    tool_stats_record_error("run_code", "boom")
    snap = tool_stats_snapshot()
    ws = snap["tools"]["web_search"]
    assert ws["calls"] == 3 and ws["ok"] == 2 and ws["fail"] == 1
    assert ws["success_rate"] == pytest.approx(2 / 3, abs=0.01)
    assert ws["avg_ms"] == pytest.approx(133.33, abs=0.1)
    rc = snap["tools"]["run_code"]
    assert rc["fail"] == 1 and rc["last_err"] == "boom"
    assert snap["slowest"]["tool"] == "web_search"
    TOOL_STATS.clear()


# ------------------------- P2-2 工具并行编排 -------------------------


def test_tool_parallel_batch_runs_concurrently():
    """多个 tool_call 在同一轮 gather 并发执行；借用 _p0_helpers 场景补充。"""
    from tests._p0_helpers import run_tool_batch_scenario

    calls, events, results = asyncio.run(run_tool_batch_scenario())
    # 两个工具都各执行一次
    assert calls == {"alpha": 1, "beta": 1}
    assert "alpha" in results[0] and "beta" in results[1]
    kinds = {e["kind"] for e in events}
    assert "tool_batch" in kinds  # 批量事件下发
    assert "tool" in kinds


# ------------------------- P2-4 限流 -------------------------


@pytest.mark.parametrize("limit", [0, 2])
def test_rate_limit_middleware(monkeypatch, limit):
    from app.main import app as test_app
    from app.auth import reset_rate_limits

    reset_rate_limits()
    monkeypatch.setattr(settings, "rate_limit_max", limit)
    monkeypatch.setattr(settings, "rate_limit_window", 60)
    c = TestClient(test_app)
    # /api/health 在限流豁免名单里，这里用 /api/cases 做被测端点
    if limit == 0:
        for _ in range(3):
            r = c.get("/api/cases")
            assert r.status_code == 200
        return
    r1 = c.get("/api/cases")
    assert r1.status_code == 200
    r2 = c.get("/api/cases")
    assert r2.status_code == 200
    r3 = c.get("/api/cases")  # 超过上限
    assert r3.status_code == 429
    assert r3.headers.get("Retry-After")
    reset_rate_limits()
    monkeypatch.setattr(settings, "rate_limit_max", 0)


# ------------------------- P2-6 成本核算 -------------------------


def test_estimate_cost(monkeypatch):
    from app.models.llm import estimate_cost

    monkeypatch.setattr(settings, "llm_cost_per_1k_in", 0.5)
    monkeypatch.setattr(settings, "llm_cost_per_1k_out", 1.0)
    monkeypatch.setattr(settings, "llm_chars_per_token", 1.5)
    c = estimate_cost(1500, 3000)  # 1000 in-token + 2000 out-token
    assert c["in_tokens"] == 1000
    assert c["out_tokens"] == 2000
    assert abs(c["cost_usd"] - (0.5 + 2.0)) < 1e-5  # 0.5 + 2.0
    assert c["priced"] is True
    monkeypatch.setattr(settings, "llm_cost_per_1k_in", 0)
    monkeypatch.setattr(settings, "llm_cost_per_1k_out", 0)


# ------------------------- P2-5 提示词版本 -------------------------


def test_prompt_registry_versions_and_resolve():
    from app.agents import prompts

    assert prompts.prompt_latest("judge") == 2  # judge 登记了 v1/v2
    assert prompts.prompt_versions("judge") == [1, 2]
    body, ver = prompts.resolve("judge", 1)
    assert ver == 1 and "truth_hypothesis" in body
    body2, ver2 = prompts.resolve("judge", None)
    assert ver2 == 2 and "错误事实" in body2
    # 非法版本回退最新
    body3, ver3 = prompts.resolve("judge", 99)
    assert ver3 == 2


def test_agent_config_prompt_version_persist(monkeypatch):
    from app.agents import agent_config
    from app.config import settings
    import os

    # 配置文件必须位于 data_dir 内（atomic_write_json 校验子路径），
    # 用测试数据目录下的独立文件名，避免污染真实配置
    cfg_path = os.path.join(settings.data_dir, "agent_config_p2_test.json")
    monkeypatch.setattr(agent_config, "CONFIG_PATH", cfg_path)
    saved = agent_config.save({"scene": {"enabled": True, "prompt_version": 1}})
    scene = next(s for s in saved if s["key"] == "scene")
    assert scene.get("prompt_version") == 1
    monkeypatch.setattr(agent_config, "CONFIG_PATH", os.path.join(settings.data_dir, "agent_config.json"))


def test_effective_prompt_uses_version_and_few_shot(monkeypatch):
    from app.agents import agent_config
    from app.config import settings
    import os

    cfg_path = os.path.join(settings.data_dir, "agent_config_p2_test2.json")
    monkeypatch.setattr(agent_config, "CONFIG_PATH", cfg_path)
    cfg = {
        "scene": {
            "enabled": True,
            "system_prompt": None,
            "prompt_version": 1,
            "few_shot": [
                {"role": "user", "content": "卷宗A"},
                {"role": "assistant", "content": "结论：...（理想输出风格）"},
            ],
        }
    }
    agent_config.save(cfg)
    text, ver = agent_config.effective_prompt("scene", "某案件")
    assert ver == 1
    assert "案发现场" in text and "卷宗摘要" in text
    assert "参考示例" in text and "理想输出风格" in text
    monkeypatch.setattr(agent_config, "CONFIG_PATH", os.path.join(settings.data_dir, "agent_config.json"))


# ------------------------- P2-7 评测集 -------------------------


def test_eval_dataset_loader_and_batch(tmp_path, monkeypatch):
    """评测集应能从 data/evals/<name>.json 加载多场景。"""
    import tools.evaluate as ev

    # EVALS_DIR 是模块级常量（导入时由 settings.data_dir 计算），
    # 这里直接指向临时目录，避免依赖导入顺序
    evals_dir = tmp_path / "evals"
    evals_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(ev, "EVALS_DIR", str(evals_dir))
    monkeypatch.setattr(ev, "EVALS_RESULTS_DIR", str(evals_dir / "results"))
    with open(evals_dir / "regression.json", "w", encoding="utf-8") as f:
        f.write(
            '{"name":"regression","cases":['
            '{"id":"c1","title":"盗窃","text":"深夜入室盗窃"},'
            '{"id":"c2","title":"合同","text":"合同违约"}]}'
        )
    ds = ev._load_dataset("regression")
    assert len(ds["cases"]) == 2
    c = ev._case_from_scene(ds["cases"][0], ds["template"])
    assert c["id"] == "c1" and "深夜入室盗窃" in c["text"]