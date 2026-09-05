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
    tmp = resolved.with_name(resolved.name + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=indent), encoding="utf-8"
    )
    tmp.replace(resolved)


def list_cases() -> List[Dict]:
    d = cases_dir()
    out = []
    for fn in os.listdir(d):
        if fn.endswith(".json"):
            try:
                with open(os.path.join(d, fn), "r", encoding="utf-8") as f:
                    c = json.load(f)
                out.append(
                    {
                        "id": c.get("id"),
                        "title": c.get("title"),
                        "summary": c.get("summary", "")[:120],
                        # 列表统计：人员/证据/时间线数量，供前端案例库直接展示
                        "persons": c.get("persons") or [],
                        "evidence": c.get("evidence") or [],
                        "timeline": c.get("timeline") or [],
                        # 前端案例库用 brief.intake_done 显示「已预处理」标记
                        "brief": {
                            "intake_done": bool(
                                (c.get("brief") or {}).get("intake_done")
                            )
                        },
                    }
                )
            except Exception:
                continue
    return out


def load_case(case_id: str) -> Optional[Dict]:
    if not validate_id(case_id):
        return None
    path = os.path.join(cases_dir(), f"{case_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
