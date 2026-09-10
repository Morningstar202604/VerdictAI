from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from app.config import settings

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_\-]+$")


def cases_dir() -> str:
    d = os.path.join(settings.data_dir, "cases")
    os.makedirs(d, exist_ok=True)
    return d


def validate_id(case_id: str) -> bool:
    return bool(_SAFE_ID.match(case_id))


def atomic_write_json(path: str, data, indent: int | None = 2) -> None:
    """全部 JSON 存储的统一落盘咽喉点：先写临时文件再原子替换。

    进程中断或断电会留下半截文件，而读取侧普遍只容忍 FileNotFoundError，
    损坏文件会让对应功能整体不可用（如 agent_config.json 损坏会拖垮全部
    辩论）。写入目标规范化后必须仍落在 DATA_DIR 内，父目录逃逸一律拒绝。"""
    resolved = Path(path).resolve()
    root = Path(settings.data_dir).resolve()
    resolved.relative_to(root)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp = resolved.with_name(resolved.name + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8"
    )
    tmp.replace(resolved)


def list_cases(
    q: str = "", has_brief: bool | None = None, tag: str = ""
) -> List[Dict]:
    """列出案件；支持筛选：q=标题/摘要关键词，has_brief=是否已预处理，
    tag=按案由/意图标签（brief.cause / intent_tags）过滤。"""
    d = cases_dir()
    out = []
    q = (q or "").strip().lower()
    tag = (tag or "").strip().lower()
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(d, fn)
        try:
            st = os.stat(path)
        except OSError:
            continue
        # 按 (mtime, size) 缓存每份案件的摘要：案件数量上百时避免
        # 每次列表请求都全量读盘解析；文件变化自动失效
        key = (st.st_mtime_ns, st.st_size)
        cached = _cases_index.get(fn)
        if cached is not None and cached[0] == key:
            item = cached[1]
        else:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    c = json.load(f)
                brief = c.get("brief") or {}
                item = {
                    "id": c.get("id"),
                    "title": c.get("title"),
                    "summary": c.get("summary", "")[:120],
                    # 列表统计：人员/证据/时间线数量，供前端案例库直接展示
                    "persons": c.get("persons") or [],
                    "evidence": c.get("evidence") or [],
                    "timeline": c.get("timeline") or [],
                    # 前端案例库用 brief.intake_done 显示「已预处理」标记
                    "brief": {
                        "intake_done": bool(brief.get("intake_done"))
                    },
                    # 标签：案由 + 意图标签，供案例库筛选
                    "cause": brief.get("cause") or "",
                    "intent": brief.get("intent") or "",
                    "intent_tags": brief.get("intent_tags") or [],
                }
            except Exception:
                continue
            _cases_index[fn] = (key, item)
        if item is None:
            continue
        # ---- 筛选 ----
        if q:
            hay = ((item.get("title") or "") + " " + (item.get("summary") or "")).lower()
            if q not in hay:
                continue
        if has_brief is not None and bool(brief_ok(item)) != has_brief:
            continue
        if tag:
            tags = [t.lower() for t in (item.get("intent_tags") or [])]
            if tag not in tags and tag not in (item.get("cause") or "").lower():
                continue
        out.append(item)
    # 清理已删除案件的缓存，防无限增长
    live = {fn for fn in os.listdir(d) if fn.endswith(".json")}
    for fn in [k for k in _cases_index if k not in live]:
        _cases_index.pop(fn, None)
    return out


def brief_ok(item: Dict) -> bool:
    """案件是否已预处理（兼容带 brief 的对象与列表摘要形态）。"""
    b = item.get("brief") or {}
    if isinstance(b, dict):
        return bool(b.get("intake_done"))
    return False


_cases_index: dict = {}


def load_case(case_id: str) -> Optional[Dict]:
    if not validate_id(case_id):
        return None
    path = os.path.join(cases_dir(), f"{case_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
