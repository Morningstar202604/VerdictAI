# -*- coding: utf-8 -*-
"""无头辩论回归客户端：直连 WebSocket 驱动一场完整辩论并汇总事件流。

用途：
    回归验证后端与引擎（不依赖浏览器）。支持 AI 落槌、人类落槌（HITL）、
    中途介入三种模式，可指定案件与出场专家。

用法（在 backend 目录用 .venv 的 python 运行）：
    python tools/debate_client.py --case case_001
    python tools/debate_client.py --case case_001 --judge human   # 末轮人类落槌（自动 confirm）
    python tools/debate_client.py --case case_001 --intervene "请重点核对E-02缺失时段" --round2-wait
"""
from __future__ import annotations

import argparse
import asyncio
import http.client
import json
import sys
import time
import uuid

from websockets.client import connect

WS = "ws://localhost:8787/ws"


def _get_json(path: str):
    """健康检查等本机 REST 探测：目标恒为 127.0.0.1:8787。"""
    conn = http.client.HTTPConnection("127.0.0.1", 8787, timeout=10)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return json.loads(resp.read())
    finally:
        conn.close()


async def run(case_id: str, judge_mode: str | None, intervene: str | None,
              confirm_text: str, timeout: float, quiet: bool, no_confirm: bool = False) -> int:
    health = _get_json("/api/health")
    print(f"[health] provider={health['provider']} mock={health['mock']}")

    session = "cli" + uuid.uuid4().hex[:8]
    events: list[dict] = []
    intervene_sent = False
    final_sent = False
    t0 = time.time()
    done = False
    error = None

    async with connect(f"{WS}/{session}", max_size=20 * 1024 * 1024) as ws:
        start_msg: dict = {"type": "start", "case_id": case_id}
        if judge_mode:
            start_msg["judge_mode"] = judge_mode
        await ws.send(json.dumps(start_msg, ensure_ascii=False))

        while True:
            if time.time() - t0 > timeout:
                error = f"超时（>{timeout:.0f}s 未收到 done）"
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=min(15, timeout))
            except asyncio.TimeoutError:
                continue
            ev = json.loads(raw)
            kind = ev.get("kind")
            events.append(ev)
            if not quiet and kind in ("round_start", "critic_end", "judge_end", "verdict",
                                      "awaiting_human", "error", "human_inject", "done",
                                      "agent_start", "tool"):
                if kind == "agent_start":
                    print(f"  [{time.time()-t0:6.1f}s] 发言 {ev.get('name')}")
                elif kind == "tool":
                    print(f"  [{time.time()-t0:6.1f}s] 工具 {ev.get('tool')} {ev.get('args')}")
                elif kind == "round_start":
                    print(f"  [{time.time()-t0:6.1f}s] === 第 {ev.get('round')} 轮 ===")
                elif kind == "critic_end":
                    cs = ev.get("contradictions") or []
                    print(f"  [{time.time()-t0:6.1f}s] 纠错官: {len(cs)} 条矛盾")
                    for c in cs:
                        print("      ⚠ " + (c.get("issue", "")[:60]))
                elif kind == "verdict":
                    v = ev.get("verdict") or {}
                    print(f"  [{time.time()-t0:6.1f}s] 裁决: {(v.get('truth_hypothesis') or '')[:80]}")
                else:
                    print(f"  [{time.time()-t0:6.1f}s] {kind}")

            if kind == "round_start" and intervene and ev.get("round", 0) >= 2 and not intervene_sent:
                await ws.send(json.dumps({"type": "human", "text": intervene, "subtype": "intervene"}, ensure_ascii=False))
                intervene_sent = True
                print(f"  [介入] 已发送插话: {intervene[:40]}")
            if kind == "awaiting_human" and not final_sent:
                if no_confirm:
                    print("  [落槌] --no-confirm：等待超时兜底触发…")
                    final_sent = True
                else:
                    await ws.send(json.dumps({"type": "human", "text": confirm_text, "subtype": "final"}, ensure_ascii=False))
                    final_sent = True
                    print(f"  [落槌] 已提交人类裁决: {confirm_text[:40]}")
            if kind == "done":
                done = True
                break
            if kind == "error":
                error = ev.get("message", "未知错误")
                break

    kinds = [e["kind"] for e in events]
    summary = {
        "ok": done and not error,
        "error": error,
        "rounds": kinds.count("round_start"),
        "statements": kinds.count("agent_start"),
        "tool_calls": kinds.count("tool"),
        "contradictions": sum(len(e.get("contradictions") or []) for e in events if e["kind"] == "critic_end"),
        "verdict": sum(1 for e in events if e["kind"] == "verdict"),
        "notes": kinds.count("agent_note"),
        "human_inject": kinds.count("human_inject"),
        "intake_recorded": "intake" in kinds,
        "elapsed": round(time.time() - t0, 1),
    }
    print("\n[summary] " + json.dumps(summary, ensure_ascii=False))
    return 0 if summary["ok"] else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="case_001")
    ap.add_argument("--judge", choices=["ai", "human"], default=None)
    ap.add_argument("--intervene", default=None, help="第2轮开始时插话内容")
    ap.add_argument("--confirm", default="confirm", help="人类落槌提交内容（默认 confirm 采纳草案）")
    ap.add_argument("--no-confirm", action="store_true", help="等待超时兜底（不提交落槌）")
    ap.add_argument("--timeout", type=float, default=240)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    return asyncio.run(run(a.case, a.judge, a.intervene, a.confirm, a.timeout, a.quiet, a.no_confirm))


if __name__ == "__main__":
    sys.exit(main())
