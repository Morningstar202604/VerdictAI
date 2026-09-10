from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Awaitable, Callable, Dict, List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.roles import ROLES
from app.agents import agent_config
from app.config import debate_snapshot, settings
from app.data.store import validate_id
from app.intake.processor import _extract_json
from app.models.llm import get_llm, is_mock, stream_enabled, stream_or_invoke
from app.models.schemas import clean_contradictions, clean_verdict
from app.models.state import DebateState

log = logging.getLogger("debate.nodes")

# 参与辩论的专家（审判长作为收敛节点单独处理）
DEBATE_ROLES = [
    "scene",
    "forensic",
    "evidence",
    "psych",
    "law",
    "prosecutor",
    "defense",
]

Sink = Callable[[Dict], Awaitable[None]]


def _session_cfg(config) -> dict:
    """取本场辩论的配置快照；未经 runner 直接调用图时回退拍一份当前值。"""
    cfg = config["configurable"].get("cfg")
    return cfg if isinstance(cfg, dict) and cfg else debate_snapshot()


def _parallel_enabled(cfg: dict) -> bool:
    mode = str((cfg or {}).get("parallel_experts") or settings.parallel_experts).lower()
    if mode == "on":
        return True
    if mode == "off":
        return False
    return not is_mock(cfg)  # auto：非 mock 供应商并行


def _to_str(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else str(p) for p in content)
    return str(content)


async def _retry_ainvoke(
    llm, messages, retries: int = 3, base: float = 1.5, timeout: int = None
):
    """对 JSON 关键的 LLM 调用做指数退避重试，吸收瞬时限流（如 1302）。
    timeout 优先取辩论配置快照；未传时回退全局 settings，防引擎挂死拖垮辩论。"""
    if timeout is None:
        timeout = settings.llm_timeout
    last: Exception | None = None
    for i in range(retries):
        try:
            if timeout and timeout > 0:
                return await asyncio.wait_for(llm.ainvoke(messages), timeout=timeout)
            return await llm.ainvoke(messages)
        except Exception as e:  # noqa: BLE001
            last = e
            if i < retries - 1:
                await asyncio.sleep(base * (2**i))
    raise last


def _chunk(text: str, size: int = 12) -> List[str]:
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in "，。；、\n；" or len(buf) >= size:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


async def _run_agent(
    role_key: str,
    role_material: str,
    intensity: str,
    guidance: str,
    history,
    sink: Sink,
    msg_id: str | None = None,
    usage: Dict | None = None,
    cfg: dict | None = None,
    phase_hint: str = "",
    session_id: str = "",
) -> str:
    cfg = cfg or {}
    role = ROLES[role_key]
    sys_prompt = agent_config.effective_prompt(role_key, role_material)
    _cfg = agent_config.load().get(role_key, {})
    llm = get_llm(role["name"], model=(_cfg.get("model") or None), cfg=cfg)
    tools = agent_config.effective_tools(role_key)
    if tools and not is_mock(cfg):
        llm = llm.bind_tools(tools)

    intensity_note = {
        "low": "（思考强度：低）请简明给出要点与结论，避免冗长推理。",
        "medium": "（思考强度：中）请给出有条理、分点的分析并标注依据。",
        "high": "（思考强度：高）请深度逐步推理，充分展开证据比对、反事实推演与不利检验。",
    }.get(intensity, "")
    user_content = (
        "请基于分派给你的卷宗材料（及上文各专家意见）发表你本轮的调查 / 分析结论：\n\n"
        + role_material
        + ("\n\n" + guidance if guidance else "")
        + ("\n\n" + intensity_note if intensity_note else "")
        + ("\n\n" + phase_hint if phase_hint else "")
    )

    context_limit = cfg.get("context_char_limit", settings.context_char_limit)
    if context_limit and context_limit > 0 and len(user_content) > context_limit:
        user_content = user_content[:context_limit] + "\n……[卷宗材料超出上下文上限，已截断；如需更多细节请用工具查询]"
    messages: List = [SystemMessage(content=sys_prompt)] + list(history)
    # 保证末尾存在一条 user 消息，否则 OpenAI/兼容接口会报 "No user query found"
    messages.append(HumanMessage(content=user_content))
    full = ""
    citations: List[str] = []  # 引用溯源（M2.1）：本轮工具检索到的可追溯来源
    final_streamed = False  # 最终答复是否已走真流式下发（避免末尾假分片重复输出）
    stream_on = stream_enabled(cfg)
    endpoint_key = "|".join(str(cfg.get(k) or "") for k in ("llm_provider", "llm_base_url", "llm_model"))
    timeout = cfg.get("llm_timeout")

    async def _stream_once():
        """一次流式尝试：chunk 到达即按增量下发 token（30ms 节流合并）。
        返回 (聚合消息, 是否已实际播出内容)。首块前失败不产生任何输出，
        调用方回退非流式；已播出部分内容后失败则抛出（重试会重复发言）。"""
        emitted = 0
        buf = {"text": "", "last": 0.0}

        async def _on(text: str) -> None:
            nonlocal emitted
            emitted += 1
            buf["text"] += text
            now = time.monotonic()
            if now - buf["last"] >= 0.03 and buf["text"]:
                buf["last"] = now
                piece, buf["text"] = buf["text"], ""
                await sink({"kind": "token", "role": role_key, "text": piece, "id": msg_id})

        agg = await stream_or_invoke(llm, messages, on_chunk=_on, timeout=timeout, key=endpoint_key)
        if buf["text"]:
            await sink({"kind": "token", "role": role_key, "text": buf["text"], "id": msg_id})
        return agg, emitted > 0

    if tools and not is_mock(cfg):
        for _ in range(4):
            final_streamed = False
            try:
                if stream_on:
                    resp, final_streamed = await _stream_once()
                else:
                    resp = await _retry_ainvoke(llm, messages, timeout=timeout)
                    full = _to_str(resp.content)
                    break
            except Exception:
                # 首块前失败：回退整段调用（含既有重试）；已播出部分内容后
                # 失败则不重试（重试会导致重复发言），交给该专家失败兜底
                if final_streamed or not stream_on:
                    raise
                resp = await _retry_ainvoke(llm, messages, timeout=timeout)
                full = _to_str(resp.content)
                break
            if getattr(resp, "tool_calls", None):
                messages.append(resp)
                for tc in resp.tool_calls:
                    fn = next((t for t in tools if t.name == tc["name"]), None)
                    try:
                        raw_args = tc.get("args") or {}
                        if not isinstance(raw_args, dict):
                            raw_args = {}
                        # ainvoke：同步工具（如 run_code 沙箱 subprocess）在线程池执行，
                        # 避免长任务阻塞事件循环导致 WebSocket keepalive 超时断连
                        result = (await fn.ainvoke(raw_args)) if fn else "工具未找到"
                    except Exception as ex:
                        # 工具参数缺失/校验失败等：返回友好错误而非中断整场辩论
                        result = "工具调用失败：" + str(ex)[:300]
                    messages.append(
                        ToolMessage(content=str(result), tool_call_id=tc["id"])
                    )
                    await sink(
                        {
                            "kind": "tool",
                            "role": role_key,
                            "tool": tc["name"],
                            "args": tc["args"],
                            "result": str(result)[:600],
                            "id": msg_id,
                        }
                    )
                    citations.extend(_extract_citations(str(result), tc["name"]))
                continue
            full = _to_str(resp.content)
            break
        else:
            # 4 次工具调用仍未产出最终结论：给兜底提示，避免静默返回空文本
            full = "（该专家经多次工具调用仍未形成明确结论，建议人工复核其证据推导。）"
    else:
        # 无工具角色：最终答复优先走真流式（首字延迟从整段等待降到首块时间）
        try:
            if stream_on:
                resp, final_streamed = await _stream_once()
                full = _to_str(resp.content)
            else:
                resp = await _retry_ainvoke(llm, messages, timeout=timeout)
                full = _to_str(resp.content)
        except Exception:
            if final_streamed or not stream_on:
                raise
            resp = await _retry_ainvoke(llm, messages, timeout=timeout)
            full = _to_str(resp.content)
    if not full.strip():
        role = ROLES.get(role_key, {})
        full = f"（{role.get('name', role_key)}未能生成有效分析，请检查模型可用性。）"
    if not final_streamed:
        # 非流式路径：保留分片下发以维持逐字显示效果
        for seg in _chunk(full):
            await sink({"kind": "token", "role": role_key, "text": seg, "id": msg_id})
            await asyncio.sleep(0.004)
    if usage is not None:
        usage["calls"] = usage.get("calls", 0) + 1
        usage["in_chars"] = usage.get("in_chars", 0) + sum(len(str(m.content)) for m in messages)
        usage["out_chars"] = usage.get("out_chars", 0) + len(full)
    if citations:
        # 引用溯源：随发言下发来源徽标（前端渲染为来源 chips）
        try:
            await sink(
                {"kind": "citations", "role": role_key, "citations": list(dict.fromkeys(citations)), "id": msg_id}
            )
        except Exception:
            pass
    if settings.audit_prompts and session_id and validate_id(session_id):
        # 提示词审计链：每次专家调用落盘一行 JSONL（提示词/响应原文 + 元信息），
        # 供研究复现；data/audit/{session}.jsonl
        try:
            audit_dir = os.path.join(settings.data_dir, "audit")
            os.makedirs(audit_dir, exist_ok=True)
            entry = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "session": session_id,
                "role": role_key,
                "model": str(getattr(llm, "model_name", "") or ""),
                "system": sys_prompt,
                "user": user_content,
                "response": full,
                "phase_hint": phase_hint,
            }
            with open(
                os.path.join(audit_dir, f"{session_id}.jsonl"), "a", encoding="utf-8"
            ) as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            log.warning("审计日志写入失败 session=%s", session_id, exc_info=True)
    return full


_DEVID_RE = __import__("re").compile(r"[EF]-\d{2}")
_DOUBT_KW = (
    "疑",
    "矛盾",
    "冲突",
    "存疑",
    "瑕疵",
    "不足",
    "无法",
    "不能",
    "未证实",
    "伪造",
    "缺失",
)

_CITE_TITLE_RE = re.compile(r"《([^》]{2,40})》")
_CITE_URL_RE = re.compile(r"https?://[^\s\"'<>()）]+")


def _extract_citations(result: str, tool: str) -> List[str]:
    """引用溯源（M2.1）：从工具返回文本提取可追溯来源（法条/知识条目标题、网页 URL）。
    供前端在专家发言中渲染「来源」徽标，实现 grounding。"""
    r = str(result or "")
    out: List[str] = []
    for m in _CITE_TITLE_RE.finditer(r):
        t = m.group(1).strip()
        if t and t not in out:
            out.append(t)
        if len(out) >= 6:
            break
    if tool == "web_search":
        for u in _CITE_URL_RE.findall(r):
            if u not in out:
                out.append(u[:70])
            if len(out) >= 4:
                break
    return out[:6]


def _selfcheck_case(case: Dict, verdict: Dict, contradictions: List) -> Dict:
    """确定性完整性自检（M2.2）：裁决前体检——
    - 证据覆盖：未在裁决中显式解释的证据计数；
    - 矛盾收敛：未解决矛盾计数；
    - 法条引用：裁决是否引用《法条》/第X条。
    同时产出证据链强度分值（M3.2 前置）：覆盖越全、矛盾越少、有法条支撑越高。"""
    evs = case.get("evidence") or []
    total = len(evs)
    text = json.dumps(verdict, ensure_ascii=False)
    covered = [
        e for e in evs
        if (e.get("id") or "") in text or ((e.get("desc") or "")[:18] and (e.get("desc")[:18] in text))
    ]
    unresolved = len(contradictions or [])
    law_hits = len(_CITE_TITLE_RE.findall(text)) + len(
        re.findall(r"第\s*[一二三四五六七八九十0-9]+\s*[条款]", text)
    )
    issues: List[str] = []
    if total and len(covered) < total:
        missing = [str(e.get("id") or "") for e in evs if e not in covered][:5]
        issues.append(f"证据覆盖不完整：{total - len(covered)}/{total} 件未在裁决中显式解释（{', '.join(m for m in missing if m)}）")
    if unresolved:
        issues.append(f"仍有 {unresolved} 条矛盾未解决，建议人类法官复核后再落槌")
    if total and law_hits == 0:
        issues.append("裁决未引用任何法条/知识条目")
    score = round(
        0.35 + 0.40 * (len(covered) / max(total, 1)) + 0.25 * max(0.0, 1.0 - unresolved / 3.0), 2
    )
    return {
        "ok": not issues,
        "issues": issues,
        "covered": len(covered),
        "total": total,
        "unresolved_contradictions": unresolved,
        "legal_citations": law_hits,
        "strength": min(1.0, max(0.0, score)),
    }


async def _summarize_note(
    role_key: str, name: str, text: str, sink: Sink, cfg: dict | None = None
) -> None:
    """在专家发言后台异步生成一条「合议记录」：核心主张 / 证据 / 疑点 / 指向。
    非阻塞（fire-and-forget），AI 失败时回退到确定性抽取，保证右侧面板总有内容。"""
    cfg = cfg or {}
    try:
        note: Dict[str, Any] = {}
        if is_mock(cfg):
            note = {
                "claim": (text or "").strip().split("\n")[0][:90],
                "evidence_ids": _DEVID_RE.findall(text or ""),
            }
        else:
            prompt = (
                "你是合议庭书记员，把某位专家的一段发言提炼成结构化记录（只输出 JSON，禁止额外文字、"
                "禁止代码块、不要转义引号）：\n"
                '{"claim":"该专家最核心的主张（一句话，≤40字）",'
                '"evidence_ids":["提及的证据编号，如E-01，没有则为空数组"],'
                '"doubts":["该专家提出的疑点/存疑事项，没有则空数组"],'
                '"implicates":["本案人物，如周明远，没有则空数组"]}\n\n'
                f"专家身份：{name}\n发言内容：\n{text}"
            )
            llm = get_llm(
                "书记员",
                model=cfg.get("intake_model") or settings.intake_model,
                temperature=0.0,
                cfg=cfg,
            )
            resp = await _retry_ainvoke(
                llm, [HumanMessage(content=prompt)], timeout=cfg.get("llm_timeout")
            )
            parsed = _extract_json(_to_str(resp.content))
            if not isinstance(parsed, dict):
                parsed = {}
            note = {
                "claim": str(parsed.get("claim") or "")[:90],
                "evidence_ids": [
                    str(x) for x in (parsed.get("evidence_ids") or []) if str(x)
                ],
                "doubts": [str(x) for x in (parsed.get("doubts") or []) if str(x)],
                "implicates": [
                    str(x) for x in (parsed.get("implicates") or []) if str(x)
                ],
            }
        if not note.get("claim"):
            note["claim"] = (text or "").strip().split("\n")[0][:90]
        if not note.get("evidence_ids"):
            note["evidence_ids"] = _DEVID_RE.findall(text or "")
        if not note.get("doubts"):
            note["doubts"] = [
                s for s in (text or "").split("。") if any(k in s for k in _DOUBT_KW)
            ][:3]
        await sink({"kind": "agent_note", "role": role_key, "name": name, "note": note})
    except Exception:
        # 尽力而为：失败时也保证有一条基础记录
        await sink(
            {
                "kind": "agent_note",
                "role": role_key,
                "name": name,
                "note": {
                    "claim": (text or "").strip().split("\n")[0][:90],
                    "evidence_ids": _DEVID_RE.findall(text or ""),
                    "doubts": [],
                    "implicates": [],
                },
            }
        )


# ------------------------- 节点 1：多专家发言 -------------------------
def _phase_hint(round_no: int, max_rounds: int) -> str:
    """庭审阶段提示：让多轮辩论有剧本——初勘自由举证、中段交叉质证、
    末轮结辩收束。对本地引擎与真实 LLM 同样生效。"""
    if max_rounds >= 3 and round_no == 2:
        return (
            "（交叉质证轮）请至少点名一位其他专家在上一轮的具体主张，"
            "明确说明你认可或反驳之处，并给出卷宗证据编号依据；"
            "禁止只重申自己上一轮的观点。"
        )
    if max_rounds >= 2 and round_no >= max_rounds:
        return (
            "（结辩轮）请给出最终结论性意见：核心主张一句话、"
            "依据的证据编号清单、以及仍需补充侦查/审查的事项；"
            "不要再抛出新论点。"
        )
    return ""


async def experts_node(state: DebateState, config) -> Dict:
    sink: Sink = config["configurable"]["sink"]
    cfg = _session_cfg(config)
    case = state.get("case", {})
    brief = case.get("brief") or {}
    per_role = brief.get("per_role_material") or {}
    intensity = brief.get("reasoning_intensity", "medium")
    guidance = brief.get("global_guidance", "")
    case_summary = case.get("summary", json.dumps(case, ensure_ascii=False)[:2000])
    new_round = state.get("round", 0) + 1
    # 跨轮记忆：窗口内轮次全文注入；窗口外轮次压缩为滚动摘要（memory_digest），
    # 不直接丢弃——高轮数辩论仍保留早期主张线索。
    summaries_all = state.get("round_summaries") or []
    win = max(0, int(cfg.get("memory_rounds", settings.memory_rounds)))
    kept = summaries_all[-win:] if win else []
    dropped = summaries_all[:-win] if win and len(summaries_all) > win else []
    digest = state.get("memory_digest") or ""
    for d_ in dropped:
        seg = re.sub(r"\s+", " ", d_)[:150]
        digest = (digest + " ▸ " + seg)[:900]
    history: List = []
    if digest:
        history.append(SystemMessage(content="【更早轮次压缩记忆】" + digest))
    for s in kept:
        history.append(SystemMessage(content="【前序轮次专家意见摘要】\n" + s))

    # 中途人工介入：把人类法官发来的意见注入本轮（非阻塞取出，仅一次）
    human_pop = config["configurable"].get("human_pop")
    pending = human_pop() if human_pop else None
    if pending:
        await sink({"kind": "human_inject", "text": pending})
        history = history + [
            HumanMessage(content="【人类法官介入】" + pending, name="human_judge")
        ]

    await sink(
        {
            "kind": "round_start",
            "round": new_round,
            "max_rounds": state.get("max_rounds", settings.max_rounds),
        }
    )
    claims: Dict[str, str] = {}
    all_order = agent_config.debate_order() or DEBATE_ROLES
    requested = state.get("agents") or []
    order = [k for k in all_order if k in requested] if requested else all_order

    async def _run_one(role_key: str):
        role = ROLES[role_key]
        material = per_role.get(role_key) or case_summary
        msg_id = f"{role_key}-{new_round}"
        await sink(
            {
                "kind": "agent_start",
                "id": msg_id,
                "role": role_key,
                "name": role["name"],
            }
        )
        text = await _run_agent(
            role_key, material, intensity, guidance, history, sink, msg_id,
            usage=config["configurable"].get("usage"),
            cfg=cfg,
            phase_hint=_phase_hint(new_round, int(state.get("max_rounds", settings.max_rounds))),
            session_id=str(config["configurable"].get("thread_id") or ""),
        )
        await sink(
            {
                "kind": "agent_end",
                "id": msg_id,
                "role": role_key,
                "name": role["name"],
                "text": text,
            }
        )
        # 后台异步生成「合议记录」，不阻塞本轮辩论；登记到 note_tasks 以便 run_debate 收尾前等待完成
        note_tasks = config["configurable"].get("note_tasks")
        if note_tasks is not None:
            note_tasks.append(
                asyncio.create_task(
                    _summarize_note(role_key, role["name"], text, sink, cfg)
                )
            )
        return role_key, text

    # 同轮专家按辩论顺序依次发言，每人完成后才启动下一位；跨轮记忆由 round_summaries 提供。
    # 单个专家失败（如该角色指定的模型不可用/超时）只影响本人：降级为兜底意见
    # 并继续其余专家，绝不中断整场辩论或产生无人消费的孤儿任务。

    async def _run_one_limited(rk: str):
        try:
            return await _run_one(rk)
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            log.warning("expert %s round %s failed: %s", rk, new_round, ex)
            await sink(
                {
                    "kind": "agent_error",
                    "role": rk,
                    "name": ROLES.get(rk, {}).get("name", rk),
                    "message": str(ex)[:200],
                    "id": f"{rk}-{new_round}",
                }
            )
            return rk, (
                f"（{ROLES.get(rk, {}).get('name', rk)}本轮分析失败："
                f"{str(ex)[:150]}，建议人工复核其证据推导。）"
            )

    results = []
    if _parallel_enabled(cfg):
        # 真实 LLM 下并行发言（README 承诺的 asyncio.gather + 并发上限）：
        # gather 保持传入顺序 → claims 与轮次摘要的顺序确定，与完成先后无关；
        # 信号量钳制并发，防云端限流；mock/本地演示路径仍走串行保持节奏感
        sem = asyncio.Semaphore(max(1, int(cfg.get("max_concurrency") or settings.max_concurrency)))

        async def _bounded(rk: str):
            async with sem:
                return await _run_one_limited(rk)

        results = list(await asyncio.gather(*[_bounded(rk) for rk in order]))
    else:
        results = []
        for rk in order:
            r = await _run_one_limited(rk)
            results.append(r)
    for role_key, text in results:
        claims[role_key] = text

    await sink({"kind": "round_end", "round": new_round})
    round_summary = json.dumps(claims, ensure_ascii=False, indent=1)
    return {
        "round": new_round,
        "memory_digest": digest,
        "claims": claims,
        "messages": [AIMessage(content=f"[第{new_round}轮辩论结束]", name="system")],
        "round_summaries": [round_summary],
        "log": [{"event": "round", "round": new_round}],
    }


# ------------------------- 节点 2：纠错 / 质疑 -------------------------
async def critic_node(state: DebateState, config) -> Dict:
    sink: Sink = config["configurable"]["sink"]
    cfg = _session_cfg(config)
    await sink({"kind": "critic_start"})
    claims = state.get("claims", {})

    new_contradictions: List[Dict] = []
    if is_mock(cfg):
        if state.get("round", 0) < state.get("max_rounds", 3):
            new_contradictions = clean_contradictions(
                [
                    {
                        "round": state.get("round"),
                        "issue": f"第{state.get('round')}轮：关键证据链闭合度仍需交叉验证（如口供与物证时间冲突）",
                        "parties": ["evidence", "psych"],
                    }
                ]
            )
    else:
        prompt = agent_config.prompt_for_critic(
            json.dumps(claims, ensure_ascii=False, indent=2)
        )
        llm = get_llm("纠错官", cfg=cfg)
        try:
            resp = await _retry_ainvoke(
                llm, [HumanMessage(content=prompt)], timeout=cfg.get("llm_timeout")
            )
            parsed = _extract_json(_to_str(resp.content))
            if isinstance(parsed, list):
                new_contradictions = clean_contradictions(parsed)
            elif isinstance(parsed, dict):
                for v in parsed.values():
                    if isinstance(v, list):
                        new_contradictions = clean_contradictions(v)
                        break
        except Exception:
            pass

    await sink({"kind": "critic_end", "contradictions": new_contradictions})
    blackboard = dict(state.get("blackboard", {}))
    blackboard["contradictions"] = state.get("contradictions", []) + new_contradictions
    return {
        "contradictions": new_contradictions,
        "blackboard": blackboard,
        "log": [{"event": "critic", "count": len(new_contradictions)}],
    }


# ------------------------- 节点 2.5：可证伪性审查（Reflexion / M2.3） -------------------------
async def reflect_node(state: DebateState, config) -> Dict:
    """裁决前反思：对每位专家的核心主张给出「反对理由/待核验点」，倒逼批评者先找反证。

    - mock：确定性抽取每角色首行主张，生成需实证检验的反对清单；
    - 真实 LLM：一次调用产出结构化 JSON。失败静默降级（不影响主流程）。"""
    sink: Sink = config["configurable"]["sink"]
    cfg = _session_cfg(config)
    claims = state.get("claims", {})
    contradictions = state.get("contradictions", [])
    reflections: List[Dict] = []

    if is_mock(cfg):
        for role_key, txt in (claims or {}).items():
            first = str(txt or "").strip().splitlines()[0][:70] or "（无主张）"
            reflections.append({
                "role": role_key,
                "subject": first,
                "objection": "该主张当前缺乏可证伪的反证排除：需补充能推翻或支撑它的证据再收敛",
            })
        for c in (contradictions or [])[:2]:
            reflections.append({
                "role": "critic",
                "subject": str(c.get("issue") or "")[:70],
                "objection": "矛盾尚未闭环：建议人类法官在落槌前复核双方依据的原始证据",
            })
    else:
        prompt = (
            "你是庭审反思官。请对以下各专家主张进行可证伪性审查：对每条主张给出最有力的"
            "反对理由或必须补齐的证据（反对理由不得重复），只输出 JSON 数组：\n"
            '[{"role":"角色key","subject":"该条主张(≤40字)","objection":"反对理由/待核验点(≤80字)"}]\n'
            "禁止输出代码块或额外文字。\n\n"
            f"专家主张：\n{json.dumps(claims, ensure_ascii=False, indent=2)}\n\n"
            f"矛盾清单：\n{json.dumps(contradictions, ensure_ascii=False, indent=2)}"
        )
        llm = get_llm("反思官", cfg=cfg)
        try:
            resp = await _retry_ainvoke(
                llm, [HumanMessage(content=prompt)], timeout=cfg.get("llm_timeout")
            )
            parsed = _extract_json(_to_str(resp.content))
            if isinstance(parsed, dict):
                for v in parsed.values():
                    if isinstance(v, list):
                        parsed = v
                        break
            if isinstance(parsed, list):
                reflections = [
                    {
                        "role": str(r.get("role") or "")[:24],
                        "subject": str(r.get("subject") or "")[:70],
                        "objection": str(r.get("objection") or "")[:110],
                    }
                    for r in parsed
                    if isinstance(r, dict) and r.get("objection")
                ][:8]
        except Exception:  # noqa: BLE001
            log.warning("反思节点解析失败，跳过（不影响裁决）")

    await sink({"kind": "reflect", "reflections": reflections})
    return {"reflections": reflections, "log": [{"event": "reflect", "count": len(reflections)}]}


# ------------------------- 节点 3：审判长收敛 / 裁决 -------------------------
async def judge_node(state: DebateState, config) -> Dict:
    sink: Sink = config["configurable"]["sink"]
    cfg = _session_cfg(config)
    await sink({"kind": "judge_start"})
    claims = state.get("claims", {})
    contradictions = state.get("contradictions", [])
    round_no = state.get("round", 0)
    max_rounds = state.get("max_rounds", settings.max_rounds)

    # 收敛约束：至少跑满 min(2,max_rounds) 轮，避免「干净案一轮就结束」；
    # 之后仍按「无矛盾 或 已达上限」判定收敛。
    min_rounds = min(2, max_rounds)
    consensus = (round_no >= min_rounds) and (
        (len(contradictions) == 0) or (round_no >= max_rounds)
    )

    if not consensus:
        await sink({"kind": "judge_end", "consensus": False})
        return {"consensus": False, "log": [{"event": "judge", "consensus": False}]}

    if is_mock(cfg):
        verdict = clean_verdict({
            "truth_hypothesis": "基于现有卷宗，真相推定：案件存在多种可能，需在关键证据（凶器DNA、被告时间线）上进一步确认。",
            "evidence_chain": [
                "现场勘查确定出入口",
                "法医确定死因与时间",
                "物证DNA指向需复核",
                "口供存在矛盾",
            ],
            "doubts": ["被告供述与监控时间冲突", "物证保管链存在瑕疵"],
            "next_steps": [
                "对关键生物检材（凶器DNA）补充复核鉴定",
                "调取监控原始载体并核验完整性（哈希比对）",
                "就口供与监控时间冲突补充讯问并固定笔录",
                "补全证据保管链记录后由人类法官复核定罪",
            ],
            "recommendation": "建议补充DNA复核与监控原始数据，再由人类法官作出最终裁判。",
            "disclaimer": "本结论由AI辅助生成，仅供研究演示，不构成任何法律意见或判决。",
        })
    else:
        prompt = (
            "你是审判长。请综合各专家主张与矛盾清单，输出 JSON："
            '{"truth_hypothesis": "...", "evidence_chain": [...], "doubts": [...], '
            '"recommendation": "...", "next_steps": ["给司法机关的可执行后续流程，3-6条"], '
            '"disclaimer": "..."}。不要输出其他内容。\n\n'
            f"各专家主张：\n{json.dumps(claims, ensure_ascii=False, indent=2)}\n\n"
            f"矛盾清单：\n{json.dumps(contradictions, ensure_ascii=False, indent=2)}"
        )
        llm = get_llm("审判长", cfg=cfg)
        try:
            resp = await _retry_ainvoke(
                llm, [HumanMessage(content=prompt)], timeout=cfg.get("llm_timeout")
            )
            parsed = _extract_json(_to_str(resp.content))
            if isinstance(parsed, dict):
                verdict = clean_verdict(parsed)
            else:
                raise ValueError("审判长未返回有效 JSON")
        except Exception:
            verdict = clean_verdict({
                "truth_hypothesis": "（解析失败，请重试或调整模型）",
                "evidence_chain": [],
                "doubts": [],
                "recommendation": "",
                "next_steps": [],
                "disclaimer": "",
            })

    await sink({"kind": "verdict", "verdict": verdict})
    await sink({"kind": "judge_end", "consensus": True})

    # 完整性自检（M2.2）+ 证据链强度（M3.2 前置）：裁决后确定性体检，
    # 结果随事件下发、落盘复盘；有缺项时在裁决上标记，交人类复核而非静默通过
    selfcheck = _selfcheck_case(state.get("case", {}) or {}, verdict, contradictions)
    verdict["evidence_strength"] = {
        "score": selfcheck["strength"],
        "issues": selfcheck["issues"],
    }
    await sink({"kind": "selfcheck", "selfcheck": selfcheck})

    return {
        "consensus": True,
        "verdict": verdict,
        "selfcheck": selfcheck,
        "log": [{"event": "verdict"}, {"event": "selfcheck", "ok": selfcheck["ok"]}],
    }


# ------------------------- 节点 5：人类审判长落槌 -------------------------
async def human_final_node(state: DebateState, config) -> Dict:
    """人类审判长落槌节点。
    不使用 LangGraph 的 interrupt()（该 API 在 Python 3.10 async 环境下不可用），
    改为通过 config 中的 wait_for_human 回调阻塞等待人类输入，超时自动采纳 AI 草案。"""
    sink: Sink = config["configurable"]["sink"]
    wait_for_human = config["configurable"].get("wait_for_human")
    hitl_timeout = config["configurable"].get("hitl_timeout", 300)
    draft = state.get("verdict") or {}
    await sink({"kind": "awaiting_human", "final": True, "draft": draft})

    human_input: str
    if wait_for_human:
        human_input = await wait_for_human(timeout=float(hitl_timeout or 0))
        if human_input is None:
            await sink({
                "kind": "human_timeout",
                "message": f"人类审判长 {hitl_timeout} 秒内未落槌，系统已采纳 AI 裁决草案并归档。",
            })
            human_input = "confirm"
    else:
        # 无等待回调（如直接调用图而非通过 runner），直接采纳草案
        human_input = "confirm"

    await sink({"kind": "human_done", "input": human_input, "final": True})

    if human_input.strip().lower() in ("confirm", "确认", "ok", "yes"):
        return {"human_input": human_input}

    text = human_input.strip()
    verdict = draft
    if text.startswith("{") and "}" in text:
        try:
            verdict = json.loads(text)
        except Exception:
            verdict = {"truth_hypothesis": text}
    else:
        verdict = {
            "truth_hypothesis": text,
            "evidence_chain": draft.get("evidence_chain", []),
            "doubts": draft.get("doubts", []),
            "recommendation": "（由人类审判长直接裁决）",
            "disclaimer": draft.get("disclaimer", ""),
        }
    await sink({"kind": "verdict", "verdict": verdict, "final": True, "by_human": True})
    return {"human_input": human_input, "verdict": verdict, "consensus": True}
