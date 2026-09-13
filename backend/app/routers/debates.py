# -*- coding: utf-8 -*-
"""辩论记录路由：列表与单条读取（复盘 / 回放）。"""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.auth import require_admin
from app.config import settings
from app.data.store import atomic_write_json, validate_id

router = APIRouter(prefix="/api/debates", tags=["debates"])

# 摘要缓存：{文件名: (mtime_ns, size, item)}，文件变更自动失效
_debates_index: dict = {}


def _debate_summary(path: str) -> dict | None:
    """解析单份辩论记录的列表摘要；损坏文件返回 None（重试到下次修改为止）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
    except Exception:
        return None
    return {
        "session_id": rec.get("session_id"),
        "case_title": rec.get("case_title"),
        "started_at": rec.get("started_at"),
        "model": rec.get("model"),
        "rounds": rec.get("rounds"),
        "truth": (rec.get("final_verdict") or {}).get("findings_of_fact")
        or (rec.get("final_verdict") or {}).get("truth_hypothesis", ""),
        "usage": rec.get("usage") or {},
    }


@router.get("")
def list_debates(limit: int = 50):
    """列出已落盘的辩论记录，供复盘。默认最多返回最近 50 条（按开始时间排序）。
    摘要按文件 (mtime, size) 缓存：记录上千份时列表请求不再全量解析。"""
    d = os.path.join(settings.data_dir, "debates")
    if not os.path.isdir(d):
        return []
    limit = max(1, min(200, int(limit)))
    entries = []
    for fn in os.listdir(d):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(d, fn)
        try:
            st = os.stat(p)
        except OSError:
            continue
        key = (st.st_mtime_ns, st.st_size)
        cached = _debates_index.get(fn)
        if cached is not None and cached[0] == key:
            item = cached[1]
        else:
            item = _debate_summary(p)
            _debates_index[fn] = (key, item)
        if item is not None:
            entries.append(item)
    # 清理已删除记录的缓存
    live = {fn for fn in os.listdir(d) if fn.endswith(".json")}
    for fn in [k for k in _debates_index if k not in live]:
        _debates_index.pop(fn, None)
    entries.sort(key=lambda e: e.get("started_at") or "", reverse=True)
    return entries[:limit]


@router.get("/{session_id}")
def get_debate(session_id: str):
    if not validate_id(session_id):
        return JSONResponse({"error": "无效的会话 ID"}, status_code=400)
    p = os.path.join(settings.data_dir, "debates", f"{session_id}.json")
    if not os.path.exists(p):
        return JSONResponse({"error": "未找到该辩论记录"}, status_code=404)
    with open(p, encoding="utf-8") as fh:
        return JSONResponse(json.load(fh))


@router.post("/{session_id}/next-steps")
def update_next_steps(session_id: str, payload: dict, _: dict = Depends(require_admin)):
    """持久化「后续流程清单」勾选状态：刷新/断线/重新开庭后清单不丢。

    只接受 0..N 的整数索引数组；越界或非法值丢弃。只改清单相关字段，
    不触碰裁决主体（真相推定/证据链等），避免误改定论。"""
    if not validate_id(session_id):
        return JSONResponse({"error": "无效的会话 ID"}, status_code=400)
    p = os.path.join(settings.data_dir, "debates", f"{session_id}.json")
    if not os.path.exists(p):
        return JSONResponse({"error": "未找到该辩论记录"}, status_code=404)
    try:
        with open(p, encoding="utf-8") as fh:
            rec = json.load(fh)
    except Exception:
        return JSONResponse({"error": "记录文件损坏"}, status_code=500)
    raw = payload.get("done") if isinstance(payload, dict) else None
    n_steps = len((rec.get("final_verdict") or {}).get("next_steps") or [])
    done = sorted({int(x) for x in (raw or []) if isinstance(x, (int, str)) and str(x).lstrip("-").isdigit() and 0 <= int(x) < n_steps}) if raw is not None else []
    rec["ns_done"] = done
    atomic_write_json(p, rec, indent=None)
    return {"ok": True, "done": done}