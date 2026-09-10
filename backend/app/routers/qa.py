# -*- coding: utf-8 -*-
"""裁决质询路由：辩论终结后向审判长追问。"""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.data.store import load_case, validate_id
from app.models.llm import get_llm

router = APIRouter(tags=["qa"])


@router.post("/api/verdict-qa")
async def verdict_qa(payload: dict):
    """裁决质询：辩论终结后，用户可就裁决继续向审判长追问。

    只依据卷宗与裁决内容作答，引用证据编号；供前端「裁决质询」面板使用。"""
    from langchain_core.messages import HumanMessage

    from app.agents.nodes import _retry_ainvoke

    data = payload if isinstance(payload, dict) else {}
    question = str(data.get("question") or "").strip()
    if not question:
        return JSONResponse({"error": "问题不能为空"}, status_code=400)
    verdict = data.get("verdict") or {}
    case_id = str(data.get("case_id") or "")
    case = load_case(case_id) if case_id and validate_id(case_id) else None

    case_facts = {
        "title": (case or {}).get("title", ""),
        "summary": ((case or {}).get("summary") or "")[:800],
        "evidence": [
            {"id": e.get("id"), "type": e.get("type"), "desc": (e.get("desc") or "")[:120]}
            for e in ((case or {}).get("evidence") or [])[:10]
        ],
        "verdict": verdict,
    }
    prompt = (
        "你是审判长。辩论已终结、裁决已作出。现在当事方就裁决提出质询，请以审判长身份答复：\n"
        "- 只依据卷宗与裁决内容，引用证据编号（如 [E-02]）；\n"
        "- 卷宗未覆盖的，明确说明属于待补充侦查/审查事项，不得编造；\n"
        "- 用中文、Markdown、条理清晰，250 字内。\n\n"
        "【裁决与卷宗要点】\n" + json.dumps(case_facts, ensure_ascii=False) +
        "\n\n【质询】\n" + question +
        "\n\n【裁决质询】请直接输出答复。"
    )
    llm = get_llm("审判长", temperature=0.2)
    try:
        resp = await _retry_ainvoke(llm, [HumanMessage(content=prompt)])
        content = resp.content if hasattr(resp, "content") else str(resp)
        answer = content if isinstance(content, str) else str(content)
    except Exception as ex:  # noqa: BLE001
        return JSONResponse({"error": f"质询答复失败：{str(ex)[:200]}"}, status_code=502)
    if not answer.strip():
        return JSONResponse({"error": "模型未返回有效答复"}, status_code=502)
    return {"answer": answer}