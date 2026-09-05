"""核心纯逻辑单测：原子落盘、agent_config 容错、辩论收敛与文本分片。

这些都是驱动每场辩论的确定性逻辑，此前只有端到端冒烟兜底；
钉死行为后，后续改动（如收敛策略调整）有了回归保护。"""

import json
import os
from pathlib import Path

import pytest

from app.agents import agent_config
from app.agents.nodes import _chunk
from app.config import settings
from app.data.store import atomic_write_json, validate_id
from app.graph.builder import should_continue


# ---------------- atomic_write_json ----------------

@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """atomic_write_json 钳制目标是 settings.data_dir，测试内先指到临时目录。"""
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    return Path(str(tmp_path))


def test_atomic_write_roundtrip(data_dir):
    target = str(data_dir / "nested" / "x.json")
    atomic_write_json(target, {"a": 1})
    with open(target, encoding="utf-8") as f:
        assert json.load(f) == {"a": 1}
    # 不留临时文件
    assert not os.path.exists(target + ".tmp")


def test_atomic_write_rejects_escape_from_data_dir(data_dir, tmp_path):
    outside = str(tmp_path.parent / "escape.json")
    with pytest.raises(ValueError):
        atomic_write_json(outside, {"a": 1})
    assert not os.path.exists(outside)


def test_atomic_write_replaces_existing(data_dir):
    target = str(data_dir / "y.json")
    atomic_write_json(target, {"v": 1})
    atomic_write_json(target, {"v": 2})
    with open(target, encoding="utf-8") as f:
        assert json.load(f) == {"v": 2}


# ---------------- agent_config 损坏容忍 ----------------

def test_agent_config_falls_back_on_corrupt_json(tmp_path, monkeypatch):
    cfg_path = Path(str(tmp_path), "agent_config.json")
    cfg_path.write_text('{"scene": {"enabled": tru', encoding="utf-8")  # 半截文件
    monkeypatch.setattr(agent_config, "CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    cfg = agent_config.load()
    # 内置默认全部在场：损坏文件只影响自定义部分
    assert set(cfg) >= {"scene", "forensic", "evidence", "psych", "law",
                        "prosecutor", "defense", "judge", "critic"}
    assert agent_config.debate_order()  # 辩论照常可开


def test_agent_config_roundtrip_save_load(tmp_path, monkeypatch):
    cfg_path = Path(str(tmp_path), "agent_config.json")
    monkeypatch.setattr(agent_config, "CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    agent_config.save({"defense": {"enabled": False, "order": 3,
                                   "system_prompt": "x", "tools": [], "model": None}})
    cfg = agent_config.load()
    assert cfg["defense"]["enabled"] is False
    assert "defense" not in agent_config.debate_order()


# ---------------- 收敛判定（should_continue） ----------------

def _state(**kw):
    base = {"round": 1, "max_rounds": 3, "consensus": False, "judge_mode": "ai"}
    base.update(kw)
    return base


def test_continue_when_below_min_rounds():
    assert should_continue(_state(round=1, max_rounds=3)) == "experts"


def test_continue_while_contradictions_unresolved():
    # round>=2 且未收敛（矛盾仍存、未达上限）→ 继续
    assert should_continue(_state(round=2, max_rounds=3)) == "experts"


def test_end_at_max_rounds_without_consensus():
    assert should_continue(_state(round=3, max_rounds=3)) == "end"


def test_end_on_consensus():
    assert should_continue(_state(round=2, consensus=True)) == "end"


def test_human_final_when_judge_mode_human():
    assert should_continue(_state(round=3, judge_mode="human")) == "human_final"


# ---------------- 文本分片（流式 token 下发） ----------------

def test_chunk_splits_on_punctuation():
    out = _chunk("第一句。第二句。", size=12)
    assert "".join(out) == "第一句。第二句。"
    assert len(out) == 2


def test_chunk_flushes_tail_without_punct():
    out = _chunk("无标点短句", size=2)
    assert "".join(out) == "无标点短句"
    assert all(len(c) <= 2 for c in out)


def test_validate_id_boundary():
    assert validate_id("case_001")
    assert not validate_id("../x")
    assert not validate_id("a b")
