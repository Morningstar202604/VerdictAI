from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

log = logging.getLogger("debate")

from langgraph.types import Command

from app.agents.tools import activate_case
from app.config import settings
from app.graph.builder import build_graph
from app.intake.processor import build_role_material
from app.ws.manager import manager


async def run_debate(
    case: dict,
    session_id: str,
    agents: Optional[list] = None,
    overrides: Optional[dict] = None,
) -> None:
    # 合并前端在开庭前对「意图 / 思考强度 / 提示词」的编辑，并重新分派角色材料
    brief = dict(case.get("brief") or {})
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
            "note_tasks": [],
        }
    }
    inputs = {
        "case_id": case.get("id"),
        "case": case,
        "max_rounds": settings.max_rounds,
        "judge_mode": resolved_judge_mode,
        "agents": agents or [],
    }

    await manager.send(
        session_id,
        {
            "kind": "session_start",
            "case_id": case.get("id"),
            "title": case.get("title"),
        },
    )
    await manager.send(
        session_id,
        {
            "kind": "intake",
            "intent": brief.get("intent"),
            "intent_tags": brief.get("intent_tags"),
            "reasoning_intensity": brief.get("reasoning_intensity"),
            "global_guidance": brief.get("global_guidance"),
            "summary": brief.get("summary"),
            "judge_mode": resolved_judge_mode,
        },
    )

    import traceback

    try:
        await graph.ainvoke(inputs, config=config)
        # 等待后台「合议记录」任务完成，避免 done 先于记录到达，或被事件循环回收时静默丢弃
        await asyncio.gather(
            *config["configurable"].get("note_tasks", []), return_exceptions=True
        )

        # 处理人类审判长落槌中断（仅 judge_mode=human 时触发）
        count = 0
        while count < 5:
            state = await graph.aget_state(config)
            if not state.next:
                break
            await manager.send(
                session_id,
                {"kind": "awaiting_human", "message": "请人类审判长输入最终裁决以继续"},
            )
            human = await manager.wait_for_human(session_id)
            await graph.ainvoke(Command(resume=human), config=config)
            count += 1
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
        # 持久化整场辩论记录，便于复盘（刷新/断线不丢失）
        try:
            debates_dir = os.path.join(settings.data_dir, "debates")
            os.makedirs(debates_dir, exist_ok=True)
            record = {
                "session_id": session_id,
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
