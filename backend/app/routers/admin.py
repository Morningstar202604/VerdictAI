# -*- coding: utf-8 -*-
"""管理与可观测性路由（M3.3 / M4 接入层）：
- GET /api/admin/usage   运行用量汇总（场次/调用/字符/审计条数/最近记录）
- GET /api/events        SSE 事件流（heartbeat），供后续实时面板/长连接扩展
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.config import settings

router = APIRouter(prefix="/api", tags=["admin"])
log = logging.getLogger("verdictai")


@router.get("/admin/usage")
def usage_stats():
    """运行用量汇总：遍历辩论记录文件聚合模型调用量与输出字符数，
    并统计提示词审计（audit/）.jsonl 行数。日志量级上千份时直接扫文件整数。"""
    d = os.path.join(settings.data_dir, "debates")
    total_calls = 0
    total_in = 0
    total_out = 0
    sessions = 0
    recent: list = []
    if os.path.isdir(d):
        files = sorted(
            (f for f in os.listdir(d) if f.endswith(".json")),
            key=lambda f: os.path.getmtime(os.path.join(d, f)),
            reverse=True,
        )
        for fn in files[:2000]:
            p = os.path.join(d, fn)
            try:
                with open(p, encoding="utf-8") as fh:
                    rec = json.load(fh)
            except Exception:
                continue
            usg = rec.get("usage") or {}
            total_calls += int(usg.get("calls") or 0)
            total_in += int(usg.get("in_chars") or 0)
            total_out += int(usg.get("out_chars") or 0)
            sessions += 1
            if len(recent) < 6:
                recent.append({
                    "session_id": rec.get("session_id"),
                    "case_title": rec.get("case_title"),
                    "started_at": rec.get("started_at"),
                    "model": rec.get("model"),
                    "rounds": rec.get("rounds"),
                    "calls": int(usg.get("calls") or 0),
                })
    audit_n = 0
    audit_dir = os.path.join(settings.data_dir, "audit")
    if os.path.isdir(audit_dir):
        for fn in os.listdir(audit_dir):
            if fn.endswith(".jsonl"):
                try:
                    with open(os.path.join(audit_dir, fn), encoding="utf-8") as fh:
                        audit_n += sum(1 for _ in fh)
                except Exception:
                    continue
    return {
        "sessions": sessions,
        "calls": total_calls,
        "in_chars": total_in,
        "out_chars": total_out,
        "audit_entries": audit_n,
        "recent": recent,
        "audit_enabled": settings.audit_prompts,
    }


@router.get("/events")
async def events_stream():
    """SSE 事件流（M4 接入层扩展）：周期性 heartbeat，占用连接即断开。
    后续可在此订阅辩论/系统事件推送给第三方面板。"""

    async def gen():
        i = 0
        try:
            while True:
                i += 1
                yield f"event: heartbeat\ndata: {json.dumps({'seq': i, 'ts': __import__('time').time()})}\n\n"
                await asyncio.sleep(15)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )