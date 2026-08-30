from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

from app.config import settings

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_\-]+$")


def cases_dir() -> str:
    d = os.path.join(settings.data_dir, "cases")
    os.makedirs(d, exist_ok=True)
    return d


def validate_id(case_id: str) -> bool:
    return bool(_SAFE_ID.match(case_id))


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
