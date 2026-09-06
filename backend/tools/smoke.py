# -*- coding: utf-8 -*-
"""一键自检：从零走完整用户旅程并逐项断言（发布前必跑）。

覆盖：健康 → 示例案件生成 → 完整辩论（事件完整性）→ 归档 →
复盘详情 → 裁决质询。任一步失败即非零退出。

用法（在 backend 目录用 .venv 的 python 运行，服务需已启动）：
    python tools/smoke.py
"""
from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, __file__.rsplit("tools", 1)[0])

BASE = "http://localhost:8787"


def _get(path: str):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=15).read())


def _post(path: str, body: dict | None = None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.loads(urllib.request.urlopen(req, timeout=180).read())


def main() -> int:
    checks = []

    def check(name: str, ok: bool, detail: str = ""):
        checks.append((name, ok, detail))
        print(("✓ " if ok else "✗ ") + name + (f" — {detail}" if detail else ""))

    health = _get("/api/health")
    check("健康检查", health.get("status") == "ok", f"v{health.get('version')} · {health.get('provider')}")

    case = _post("/api/cases/generate")["case"]
    check("示例案件生成", bool(case.get("id")), case["id"])

    import asyncio
    import time
    import uuid

    from websockets.client import connect

    async def run_debate():
        session = "smoke" + uuid.uuid4().hex[:8]
        events = []
        async with connect("ws://localhost:8787/ws/" + session) as ws:
            await ws.send(json.dumps({"type": "start", "case_id": case["id"]}))
            deadline = time.time() + 180
            while time.time() < deadline:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                ev = json.loads(raw)
                events.append(ev)
                if ev.get("kind") in ("done", "error"):
                    break
        return events

    events = asyncio.run(run_debate())
    kinds = [e.get("kind") for e in events]
    check("完整辩论", "done" in kinds and "verdict" in kinds and kinds.count("agent_end") >= 7,
          f"{kinds.count('agent_start')} 发言 / {kinds.count('tool')} 工具 / {len(kinds)} 事件")

    debates = _get("/api/debates")
    check("自动归档", len(debates) >= 1, f"{len(debates)} 条")

    detail = _get(f"/api/debates/{debates[0]['session_id']}")
    check("复盘详情", bool(detail.get("final_verdict")) and len(detail.get("events", [])) > 10,
          f"{len(detail.get('events', []))} 事件")

    qa = _post("/api/verdict-qa", {"question": "裁决的核心依据是什么？"})
    check("裁决质询", bool(qa.get("answer")), qa.get("answer", "")[:40])

    failed = [n for n, ok, _ in checks if not ok]
    print()
    print("SMOKE:", "PASS" if not failed else f"FAIL → {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
