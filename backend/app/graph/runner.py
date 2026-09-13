from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

from app.agents.tools import activate_case
from app.config import debate_snapshot, settings
from app.data.store import atomic_write_json, validate_id
from app.graph.builder import build_graph
from app.intake.processor import build_role_material, preprocess
from app.models.llm import estimate_cost
from app.ws.manager import manager

log = logging.getLogger("debate")


async def run_debate(
    case: dict,
    session_id: str,
    agents: Optional[list] = None,
    overrides: Optional[dict] = None,
) -> None:
    if not case:
        await manager.send(session_id, {"kind": "error", "message": "案件不存在或已被删除，请刷新后重新选择。"})
        return

    # 开场拍配置快照：本场辩论全程只读快照，POST /api/settings 的后续变更
    # 只影响新辩论，不干扰进行中的会话（并发会话互不污染）。
    cfg = debate_snapshot()

    # 存量案件可能没有 brief（如直接放入 cases 目录、或旧版本生成）：
    # 开庭时自动补跑一次卷宗预处理，保证专家拿到结构化分案材料。
    if not (case.get("brief") or {}).get("intake_done"):
        try:
            case["brief"] = await preprocess(case, cfg=cfg)
        except Exception as ex:
            case["brief"] = {"intake_done": False, "error": str(ex)[:300]}

    # 合并前端在开庭前对「意图 / 思考强度 / 提示词」的编辑，并重新分派角色材料
    brief = dict(case.get("brief") or {})
    if brief.get("error"):
        await manager.send(
            session_id,
            {
                "kind": "error",
                "message": "卷宗预处理失败："
                + str(brief.get("error"))[:200]
                + "，请重新上传案件",
            },
        )
        return
    # judge_mode 按会话隔离（不再改写全局 settings，避免并发会话互相污染）
    resolved_judge_mode = (
        overrides.get("judge_mode")
        if overrides and overrides.get("judge_mode")
        else cfg["judge_mode"]
    )
    if overrides:
        changed = False
        for k in ("intent", "reasoning_intensity", "global_guidance"):
            if overrides.get(k) is not None:
                brief[k] = overrides[k]
                changed = True
        if changed:
            brief["reasoning_intensity"] = brief.get("reasoning_intensity", "medium")
            brief["per_role_material"] = build_role_material(
                case,
                brief.get("intent", "未指定"),
                brief.get("global_guidance", ""),
                brief.get("contradictions"),
            )
    case = dict(case)
    case["brief"] = brief

    activate_case(case)
    graph = build_graph()
    start_ts = time.time()
    round_ts: dict = {}
    event_count = 0
    transcript: list = []
    final_verdict: dict | None = None
    # 会话 Trace（P0-1）：记录每个审判节点的耗时/用量 span，随 done 事件下发。
    open_spans: dict = {}  # span_id -> {"ts": float, "usage": dict}
    trace_spans: list = []  # 已闭合的 span，按开始时间排序

    def _usage_snap() -> dict:
        u = config["configurable"].get("usage") or {}
        return {"calls": u.get("calls", 0), "in_chars": u.get("in_chars", 0), "out_chars": u.get("out_chars", 0)}

    def _close_span(span_id: str, end_ts: float) -> None:
        opened = open_spans.pop(span_id, None)
        if not opened:
            return
        us = opened["usage"]
        ue = _usage_snap()
        trace_spans.append(
            {
                "span": span_id,
                "kind": span_id.split("|")[0],
                "start": opened["ts"],
                "end": end_ts,
                "ms": round((end_ts - opened["ts"]) * 1000, 1),
                "usage": {
                    "calls": max(0, ue["calls"] - us["calls"]),
                    "in_chars": max(0, ue["in_chars"] - us["in_chars"]),
                    "out_chars": max(0, ue["out_chars"] - us["out_chars"]),
                },
            }
        )

    async def sink(event: dict) -> None:
        nonlocal event_count, final_verdict
        event_count += 1
        now = time.time()
        kind = event.get("kind")
        if kind == "round_start":
            round_ts[event.get("round")] = {"start": now}
            open_spans[f"round|{event.get('round')}"] = {"ts": now, "usage": _usage_snap()}
        elif kind == "round_end":
            r = event.get("round")
            if r in round_ts:
                round_ts[r]["end"] = now
            _close_span(f"round|{r}", now)
        elif kind == "critic_start":
            open_spans["critic"] = {"ts": now, "usage": _usage_snap()}
        elif kind == "critic_end":
            _close_span("critic", now)
        elif kind == "reflect_start":
            open_spans["reflect"] = {"ts": now, "usage": _usage_snap()}
        elif kind == "reflect":
            _close_span("reflect", now)
        elif kind == "judge_start":
            open_spans["judge"] = {"ts": now, "usage": _usage_snap()}
        elif kind == "judge_end":
            _close_span("judge", now)
        elif kind == "awaiting_human":
            open_spans["human"] = {"ts": now, "usage": _usage_snap()}
        elif kind == "human_done" or kind == "human_timeout":
            _close_span("human", now)
        elif kind == "verdict":
            final_verdict = event.get("verdict")
        transcript.append(event)
        await manager.send(session_id, event)

    config = {
        "configurable": {
            "thread_id": session_id,
            "cfg": cfg,
            "sink": sink,
            "human_pop": lambda: manager.pop_human(session_id),
            # 人类审判长落槌等待回调（替代 LangGraph interrupt()，兼容 Python 3.10）
            "wait_for_human": lambda timeout=0: manager.wait_for_human(session_id, timeout=timeout),
            "hitl_timeout": cfg["hitl_timeout"],
            "note_tasks": [],
            "usage": {"calls": 0, "in_chars": 0, "out_chars": 0},
        }
    }
    inputs = {
        "case_id": case.get("id"),
        "case": case,
        "max_rounds": cfg["max_rounds"],
        "judge_mode": resolved_judge_mode,
        "agents": agents or [],
    }

    # 经 sink 发送，使 session_start/intake 一并进入转录（复盘记录完整可回放）
    await sink(
        {
            "kind": "session_start",
            "case_id": case.get("id"),
            "title": case.get("title"),
        }
    )
    await sink(
        {
            "kind": "intake",
            "intent": brief.get("intent"),
            "intent_tags": brief.get("intent_tags"),
            "reasoning_intensity": brief.get("reasoning_intensity"),
            "global_guidance": brief.get("global_guidance"),
            "summary": brief.get("summary"),
            "investigation_plan": brief.get("investigation_plan") or [],
            "judge_mode": resolved_judge_mode,
        }
    )

    import traceback

    try:
        await graph.ainvoke(inputs, config=config)
        # 等待后台「合议记录」任务完成，避免 done 先于记录到达，或被事件循环回收时静默丢弃
        await asyncio.gather(
            *config["configurable"].get("note_tasks", []), return_exceptions=True
        )
    except Exception as e:
        traceback.print_exc()
        await manager.send(
            session_id,
            {"kind": "error", "message": (str(e) or "辩论过程中发生未知错误")},
        )
    finally:
        elapsed = time.time() - start_ts
        for r, t in round_ts.items():
            if "end" in t:
                log.info(
                    "[debate %s] round %s 耗时 %.1fs",
                    session_id,
                    r,
                    t["end"] - t["start"],
                )
        log.info(
            "[debate %s] 结束：总耗时 %.1fs，事件数 %d，模型 %s",
            session_id,
            elapsed,
            event_count,
            cfg["llm_model"],
        )
        # 会话 Trace 下发：审判节点时间线（含每节点 LLM 调用数/字数量），
        # 前端据此渲染时间线视图，也随记录落盘供复盘回放。
        try:
            await manager.send(
                session_id,
                {
                    "kind": "trace",
                    "spans": trace_spans,
                    "total_ms": round(elapsed * 1000, 1),
                },
            )
        except Exception:
            pass
        # 用量统计随辩论落盘，供复盘与成本评估（P2-6：附 token/费用换算）
        try:
            _usage = config["configurable"].get("usage") or {}
            _usage_payload = dict(_usage)
            _usage_payload["cost"] = estimate_cost(
                _usage.get("in_chars", 0), _usage.get("out_chars", 0)
            )
            await manager.send(session_id, {"kind": "usage", "usage": _usage_payload})
        except Exception:
            pass
        # 持久化整场辩论记录，便于复盘（刷新/断线不丢失）；原子替换，
        # 中断不会留下半截记录让复盘页解析失败
        try:
            _usage = config["configurable"].get("usage") or {}
            record = {
                "session_id": session_id,
                "usage": _usage,
                "cost": estimate_cost(_usage.get("in_chars", 0), _usage.get("out_chars", 0)),
                "case_id": case.get("id"),
                "case_title": case.get("title"),
                "started_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_ts)
                ),
                "model": cfg["llm_model"],
                "rounds": sum(1 for e in transcript if e.get("kind") == "round_start"),
                "final_verdict": final_verdict,
                "trace": {"spans": trace_spans, "total_ms": round((time.time() - start_ts) * 1000, 1)},
                "events": transcript,
            }
            debates_dir = os.path.join(settings.data_dir, "debates")
            atomic_write_json(
                os.path.join(debates_dir, f"{session_id}.json"), record, indent=None
            )
        except Exception:
            log.warning("[debate %s] 辩论记录落盘失败", session_id, exc_info=True)

        # 案例沉淀（M2.5）：把本场最终裁决回填案件文件，作为「类案/判决」沉淀，
        # 供案例库检索、相似案例推荐与后续庭审参考（长期记忆留痕）
        if final_verdict:
            try:
                case_id = case.get("id") or ""
                if validate_id(case_id):
                    case_path = os.path.join(
                        settings.data_dir, "cases", f"{case_id}.json"
                    )
                    if os.path.exists(case_path):
                        with open(case_path, encoding="utf-8") as fh:
                            stored = json.load(fh)
                        stored["last_verdict"] = final_verdict
                        stored["last_verdict_at"] = time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_ts)
                        )
                        atomic_write_json(case_path, stored, indent=None)
            except Exception:
                log.warning("[debate %s] 案例沉淀回填失败", session_id, exc_info=True)
        # 庭审结束仍有未消费的人工介入：明确告知而不是静默丢弃
        try:
            _q = manager.human_queues.get(session_id)
            if _q is not None and not _q.empty():
                await manager.send(
                    session_id,
                    {
                        "kind": "intervention_dropped",
                        "count": _q.qsize(),
                        "message": "庭审已结束，仍有插话未送达合议庭。",
                    },
                )
        except Exception:
            pass
        await manager.send(session_id, {"kind": "done"})
