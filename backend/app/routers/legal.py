# -*- coding: utf-8 -*-
"""法条引用核查路由：引用信号灯数据源（对标 2026 法律 AI 引用可回溯设计）。

- GET  /api/legal/known-statutes  已知法条索引（案件卷宗 + 内置法条库），
  前端据此在专家发言/裁决中渲染 ✓已核实 / ⚠待人工核对 信号灯；
- POST /api/legal/cite-check      批量核查文本中的法条引用（报告附录 / 外部调用）。

全部为确定性本地匹配，无模型调用、毫秒级返回。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.data.store import load_case
from app.legal.cite_check import check_texts, known_statute_index

router = APIRouter(prefix="/api/legal", tags=["legal"])


@router.get("/known-statutes")
def get_known_statutes(case_id: str = ""):
    """已知法条索引：内置法条库 +（可选）指定案件的卷宗法条。"""
    case_statutes = []
    case_count = 0
    if case_id.strip():
        case = load_case(case_id.strip())
        if case is None:
            return JSONResponse({"error": "未找到该案件"}, status_code=404)
        case_statutes = case.get("statutes") or []
        case_count = len(case_statutes)
    index = known_statute_index(case_statutes)
    return {
        "statutes": [
            {"key": k, "name": v["name"], "source": v["source"]}
            for k, v in sorted(index.items())
        ],
        "case_count": case_count,
        "builtin_count": len(index) - case_count,
    }


@router.post("/cite-check")
def post_cite_check(payload: dict):
    """批量核查文本中的法条引用。body: {texts: [...], case_id?: str}"""
    data = payload if isinstance(payload, dict) else {}
    texts = data.get("texts")
    if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
        return JSONResponse({"error": "texts 须为字符串数组"}, status_code=400)
    texts = [t[:50000] for t in texts]
    case_statutes = None
    cid = str(data.get("case_id") or "").strip()
    if cid:
        case = load_case(cid)
        if case is None:
            return JSONResponse({"error": "未找到该案件"}, status_code=404)
        case_statutes = case.get("statutes") or []
    return check_texts(texts, case_statutes)
