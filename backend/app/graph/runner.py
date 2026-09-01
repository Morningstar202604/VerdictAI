from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

log = logging.getLogger("debate")

from app.agents.tools import activate_case
from app.config import settings
from app.graph.builder import build_graph
from app.intake.processor import build_role_material, preprocess
from app.ws.manager import manager


async def run_debate(
    case: dict,
    session_id: str,
    agents: Optional[list] = None,
    overrides: Optional[dict] = None,
) -> None:
    if not case:
        await manager.send(session_id, {"kind": "error", "message": "案件不存在或已被删除，请刷新后重新选择。"})
        return

    # 存量案件可能没有 brief（如直接放入 cases 目录、或旧版本生成）：
    # 开庭时自动补跑一次卷宗预处理，保证专家拿到结构化分案材料。
    if not (case.get("brief") or {}).get("intake_done"):
        try:
            case["brief"] = await preprocess(case)
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
        else settings.judge_mode
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

    async def sink(event: dict) -> None:
        nonlocal event_count, final_verdict
        event_count += 1
        now = time.time()
        kind = event.get("kind")
        if kind == "round_start":
            round_ts[event.get("round")] = {"start": now}
        elif kind == "round_end":
            r = event.get("round")
            if r in round_ts:
                round_ts[r]["end"] = now
        elif kind == "verdict":
            final_verdict = event.get("verdict")
        transcript.append(event)
        await manager.send(session_id, event)

    config = {
        "configurable": {
            "thread_id": session_id,
            "sink": sink,
            "human_pop": lambda: manager.pop_human(session_id),
            # 人类审判长落槌等待回调（替代 LangGraph interrupt()，兼容 Python 3.10）
            "wait_for_human": lambda timeout=0: manager.wait_for_human(session_id, timeout=timeout),
            "hitl_timeout": settings.hitl_timeout,
            "note_tasks": [],
            "usage": {"calls": 0, "in_chars": 0, "out_chars": 0},
        }
    }
    inputs = {
        "case_id": case.get("id"),
        "case": case,
        "max_rounds": settings.max_rounds,
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
            settings.llm_model,
        )
        # 用量统计随辩论落盘，供复盘与成本评估
        try:
            await manager.send(session_id, {"kind": "usage", "usage": config["configurable"].get("usage") or {}})
        except Exception:
            pass
        # 持久化整场辩论记录，便于复盘（刷新/断线不丢失）
        try:
            debates_dir = os.path.join(settings.data_dir, "debates")
            os.makedirs(debates_dir, exist_ok=True)
            record = {
                "session_id": session_id,
                "usage": config["configurable"].get("usage") or {},
                "case_id": case.get("id"),
                "case_title": case.get("title"),
                "started_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_ts)
                ),
                "model": settings.llm_model,
                "rounds": sum(1 for e in transcript if e.get("kind") == "round_start"),
                "final_verdict": final_verdict,
                "events": transcript,
            }
            with open(
                os.path.join(debates_dir, f"{session_id}.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(record, f, ensure_ascii=False)
        except Exception:
            log.warning("[debate %s] 辩论记录落盘失败", session_id, exc_info=True)
        await manager.send(session_id, {"kind": "done"})
