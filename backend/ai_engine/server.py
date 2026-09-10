# -*- coding: utf-8 -*-
"""VerdictAI 本地推理引擎服务入口。

OpenAI 兼容的聊天补全服务，用确定性的案件分析逻辑替代外部大模型：
- 分案法官 / 书记员 / 纠错官 / 审判长 / 裁决质询节点输出严格 JSON；
- 各专家角色生成有依据、分点、跨轮相互参照的 Markdown 陈述，支持工具回环；
- 支持 streaming（SSE）与 tool_calls（read_evidence / timeline_check /
  search_case_law / run_code，沙箱图表可渲染到笔录）。

启动：python -m uvicorn ai_engine.server:app --host 127.0.0.1 --port 9100
后端切换：POST /api/settings {"llm_base_url":"http://127.0.0.1:9100/v1"}
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ai_engine.intake import intake_json
from ai_engine.nodes import clerk_json, critic_json, judge_json, qa_answer
from ai_engine.parsing import Case, _has_image, _section, _text_of
from ai_engine.state import LOCK, STATE, _refresh_case, _reset_critic, _round_for
from ai_engine.statements import (
    _detect_role,
    _human_intervention,
    _maybe_tool_call,
    _prev_from_history,
    _statement,
)

app = FastAPI(title="VerdictAI Local Engine", version="0.8.0")

MODELS = {"object": "list", "data": [{"id": "verdict-local", "object": "model"}, {"id": "verdict-local-intake", "object": "model"}]}


@app.get("/healthz")
def healthz():
    return {"ok": True, "engine": "zcode-local-1"}


@app.get("/v1/models")
def models():
    return MODELS


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages: List[dict] = body.get("messages") or []
    req_tools: List[dict] = body.get("tools") or []
    model = body.get("model", "verdict-local")
    want_stream = bool(body.get("stream"))

    texts = [_text_of(m.get("content")) for m in messages]
    joined = "\n".join(texts)
    sys_text = next((t for t, m in zip(texts, messages) if m.get("role") == "system"), "")
    has_tool_msg = any(m.get("role") == "tool" for m in messages)

    def _payload(content: str, finish: str = "stop", extra: Optional[dict] = None) -> dict:
        msg: Dict[str, Any] = {"role": "assistant", "content": content}
        if extra:
            msg.update(extra)
        return {
            "id": f"chatcmpl-local-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
            "usage": {
                "prompt_tokens": max(1, len(joined) // 3),
                "completion_tokens": max(1, len(content) // 3),
                "total_tokens": (len(joined) + len(content)) // 3,
            },
        }

    def _reply(content: str, finish: str = "stop", extra: Optional[dict] = None):
        payload = _payload(content, finish, extra)
        if not want_stream:
            return JSONResponse(payload)
        # OpenAI 兼容 SSE：内容分块下发，末帧带 finish_reason，再以 [DONE] 结束
        from fastapi.responses import StreamingResponse

        async def gen():
            piece = ""
            for ch in content:
                piece += ch
                if len(piece) >= 48:
                    yield "data: " + json.dumps(
                        {"id": payload["id"], "object": "chat.completion.chunk",
                         "created": payload["created"], "model": model,
                         "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]},
                        ensure_ascii=False) + "\n\n"
                    piece = ""
            if piece:
                yield "data: " + json.dumps(
                    {"id": payload["id"], "object": "chat.completion.chunk",
                     "created": payload["created"], "model": model,
                     "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]},
                    ensure_ascii=False) + "\n\n"
            tail = {"id": payload["id"], "object": "chat.completion.chunk",
                    "created": payload["created"], "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}
            yield "data: " + json.dumps(tail, ensure_ascii=False) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    # 1) 多模态图片描述（本地引擎不做视觉识别，如实说明）
    if _has_image(messages):
        return _reply("图片材料：包含与案件相关的场景/文字信息。本地引擎暂不具备视觉识别能力，建议专家结合卷宗原文与工具核验。")

    # 2) 分案法官（intake）
    if "严格的 JSON 生成器" in joined:
        obj = intake_json(joined)
        with LOCK:
            found = re.findall(r"-\s*([\u4e00-\u9fa5]{2,4})[（(]", _section(joined, "涉案人员"))
            STATE["names"] = list(dict.fromkeys(STATE["names"] + found))[:12]
        return _reply(json.dumps(obj, ensure_ascii=False))

    # 3) 书记员
    if "合议庭书记员" in joined:
        stmt = joined.split("发言内容：", 1)[-1]
        return _reply(json.dumps(clerk_json(stmt), ensure_ascii=False))

    # 4) 纠错官
    if "辩论纠错官" in joined:
        return _reply(json.dumps(critic_json(), ensure_ascii=False))

    # 5) 裁决质询（辩论终结后，就裁决继续追问）
    #    注意：必须先于裁决分支判断——质询提示词里也含「你是审判长」与 truth_hypothesis
    if "【裁决质询】" in joined:
        case = STATE.get("last_case") or Case(joined)
        verdict: Dict[str, Any] = {}
        facts: Dict[str, Any] = {}
        try:
            m = re.search(r"【裁决与卷宗要点】\n(\{.*?\})\n\n【质询】", joined, re.S)
            if m:
                facts = json.loads(m.group(1))
                verdict = facts.get("verdict") or {}
        except Exception:
            verdict = STATE.get("last_verdict") or {}
        qm = re.search(r"【质询】\n(.+?)\n\n【裁决质询】", joined, re.S)
        question = qm.group(1).strip() if qm else joined[-200:]
        return _reply(qa_answer(case, verdict, question, facts))

    # 6) 审判长（verdict）
    if "你是审判长" in joined and "truth_hypothesis" in joined:
        case = STATE.get("last_case") or Case(joined)
        verdict_obj = judge_json(case)
        with LOCK:
            STATE["last_verdict"] = verdict_obj
        return _reply(json.dumps(verdict_obj, ensure_ascii=False))

    # 7) 专家陈述
    role = _detect_role(sys_text) if sys_text else "expert"
    material = sys_text if ("案件概要" in sys_text) else joined
    case = _refresh_case(material, hash_basis=sys_text[:200])
    with LOCK:
        STATE["last_case"] = case
        STATE["names"] = list(dict.fromkeys(STATE["names"] + case.names))[:12]
    _prev_from_history(messages, role, case)
    case.human_note = _human_intervention(messages)

    if has_tool_msg:
        # 工具回环：上一条是工具返回，给最终结论
        round_no = STATE["rounds_by_case"].get(case.hash, {}).get(role, 1)
        tool_res = next((_text_of(m.get("content")) for m in reversed(messages) if m.get("role") == "tool"), "")
        note = re.sub(r"\s+", " ", tool_res)[:120]
        return _reply(_statement(role, case, round_no, note))

    _reset_critic(case.hash, messages)
    round_no = _round_for(case.hash, role, messages)
    if req_tools:
        pick = _maybe_tool_call(role, case, round_no, req_tools)
        if pick:
            name, args = pick
            return _reply(
                "",
                finish="tool_calls",
                extra={"tool_calls": [{
                    "id": f"call-{uuid.uuid4().hex[:10]}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
                }]},
            )
    return _reply(_statement(role, case, round_no, ""))