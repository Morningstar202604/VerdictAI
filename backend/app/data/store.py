from __future__ import annotations

import json
import os
from typing import Dict, List

from app.config import settings


def cases_dir() -> str:
    d = os.path.join(settings.data_dir, "cases")
    os.makedirs(d, exist_ok=True)
    return d


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
                    }
                )
            except Exception:
                continue
    return out


def load_case(case_id: str) -> Dict:
    path = os.path.join(cases_dir(), f"{case_id}.json")
    if not os.path.exists(path):
        # 回退到第一个可用案件
        for fn in os.listdir(cases_dir()):
            if fn.endswith(".json"):
                path = os.path.join(cases_dir(), fn)
                break
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
