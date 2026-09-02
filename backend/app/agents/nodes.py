from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable, Dict, List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.roles import ROLES, build_system_prompt
from app.agents.tools import tools_for_role
from app.agents import agent_config
from app.config import settings
from app.intake.processor import _extract_json
from app.models.llm import get_llm, is_mock
from app.models.state import DebateState

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


def _to_str(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else str(p) for p in content)
    return str(content)


async def _retry_ainvoke(llm, messages, retries: int = 3, base: float = 1.5):
    """对 JSON 关键的 LLM 调用做指数退避重试，吸收瞬时限流（如 1302）。
    settings.llm_timeout > 0 时单次调用限时，防止引擎挂死拖垮整场辩论。"""
    last: Exception | None = None
    for i in range(retries):
        try:
            if settings.llm_timeout and settings.llm_timeout > 0:
                return await asyncio.wait_for(llm.ainvoke(messages), timeout=settings.llm_timeout)
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
) -> str:
    role = ROLES[role_key]
    sys_prompt = agent_config.effective_prompt(role_key, role_material)
    _cfg = agent_config.load().get(role_key, {})
    llm = get_llm(role["name"], model=(_cfg.get("model") or None))
    tools = agent_config.effective_tools(role_key)
    if tools and not is_mock():
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
    )

    if settings.context_char_limit and settings.context_char_limit > 0 and len(user_content) > settings.context_char_limit:
        user_content = user_content[: settings.context_char_limit] + "\n……[卷宗材料超出上下文上限，已截断；如需更多细节请用工具查询]"
    messages: List = [SystemMessage(content=sys_prompt)] + list(history)
    # 保证末尾存在一条 user 消息，否则 OpenAI/兼容接口会报 "No user query found"
    messages.append(HumanMessage(content=user_content))
    full = ""

    if tools and not is_mock():
        for _ in range(4):
            resp = await _retry_ainvoke(llm, messages)
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
                continue
            full = _to_str(resp.content)
            break
        else:
            # 4 次工具调用仍未产出最终结论：给兜底提示，避免静默返回空文本
            full = "（该专家经多次工具调用仍未形成明确结论，建议人工复核其证据推导。）"
    else:
        # 无工具角色：直接一次性生成（不依赖模型流式能力，跨模型更稳；
        # 仍按 token 分片下发以保留逐字显示效果）
        resp = await _retry_ainvoke(llm, messages)
        full = _to_str(resp.content)
    if not full.strip():
        role = ROLES.get(role_key, {})
        full = f"（{role.get('name', role_key)}未能生成有效分析，请检查模型可用性。）"
    for seg in _chunk(full):
        await sink({"kind": "token", "role": role_key, "text": seg, "id": msg_id})
        await asyncio.sleep(0.004)
    if usage is not None:
        usage["calls"] = usage.get("calls", 0) + 1
        usage["in_chars"] = usage.get("in_chars", 0) + sum(len(str(m.content)) for m in messages)
        usage["out_chars"] = usage.get("out_chars", 0) + len(full)
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


async def _summarize_note(role_key: str, name: str, text: str, sink: Sink) -> None:
    """在专家发言后台异步生成一条「合议记录」：核心主张 / 证据 / 疑点 / 指向。
    非阻塞（fire-and-forget），AI 失败时回退到确定性抽取，保证右侧面板总有内容。"""
    try:
        note: Dict[str, Any] = {}
        if is_mock():
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
            llm = get_llm("书记员", model=settings.intake_model, temperature=0.0)
            resp = await _retry_ainvoke(llm, [HumanMessage(content=prompt)])
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
async def experts_node(state: DebateState, config) -> Dict:
    sink: Sink = config["configurable"]["sink"]
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
    win = max(0, settings.memory_rounds)
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
                asyncio.create_task(_summarize_note(role_key, role["name"], text, sink))
            )
        return role_key, text

    # 同轮专家相互独立，并行执行以大幅缩短单轮耗时；跨轮记忆由 round_summaries 提供，
    # 同轮内不再互相可见（避免串行等待）。并行上限可配置（真实 API 限流保护）。
    _sem = asyncio.Semaphore(max(1, settings.max_concurrency))

    async def _run_one_limited(rk: str):
        async with _sem:
            return await _run_one(rk)

    results = await asyncio.gather(*[_run_one_limited(rk) for rk in order])
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
    await sink({"kind": "critic_start"})
    claims = state.get("claims", {})

    new_contradictions: List[Dict] = []
    if is_mock():
        if state.get("round", 0) < state.get("max_rounds", 3):
            new_contradictions.append(
                {
                    "round": state.get("round"),
                    "issue": f"第{state.get('round')}轮：关键证据链闭合度仍需交叉验证（如口供与物证时间冲突）",
                    "parties": ["evidence", "psych"],
                }
            )
    else:
        prompt = agent_config.prompt_for_critic(
            json.dumps(claims, ensure_ascii=False, indent=2)
        )
        llm = get_llm("纠错官")
        try:
            resp = await _retry_ainvoke(llm, [HumanMessage(content=prompt)])
            parsed = _extract_json(_to_str(resp.content))
            if isinstance(parsed, list):
                new_contradictions = parsed
            elif isinstance(parsed, dict):
                for v in parsed.values():
                    if isinstance(v, list):
                        new_contradictions = v
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


# ------------------------- 节点 3：审判长收敛 / 裁决 -------------------------
async def judge_node(state: DebateState, config) -> Dict:
    sink: Sink = config["configurable"]["sink"]
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

    if is_mock():
        verdict = {
            "truth_hypothesis": "基于现有卷宗，真相推定：案件存在多种可能，需在关键证据（凶器DNA、被告时间线）上进一步确认。",
            "evidence_chain": [
                "现场勘查确定出入口",
                "法医确定死因与时间",
                "物证DNA指向需复核",
                "口供存在矛盾",
            ],
            "doubts": ["被告供述与监控时间冲突", "物证保管链存在瑕疵"],
            "recommendation": "建议补充DNA复核与监控原始数据，再由人类法官作出最终裁判。",
            "disclaimer": "本结论由AI辅助生成，仅供研究演示，不构成任何法律意见或判决。",
        }
    else:
        prompt = (
            "你是审判长。请综合各专家主张与矛盾清单，输出 JSON："
            '{"truth_hypothesis": "...", "evidence_chain": [...], "doubts": [...], '
            '"recommendation": "...", "next_steps": ["给司法机关的可执行后续流程，3-6条"], '
            '"disclaimer": "..."}。不要输出其他内容。\n\n'
            f"各专家主张：\n{json.dumps(claims, ensure_ascii=False, indent=2)}\n\n"
            f"矛盾清单：\n{json.dumps(contradictions, ensure_ascii=False, indent=2)}"
        )
        llm = get_llm("审判长")
        try:
            resp = await _retry_ainvoke(llm, [HumanMessage(content=prompt)])
            parsed = _extract_json(_to_str(resp.content))
            if isinstance(parsed, dict):
                verdict = parsed
                verdict.setdefault(
                    "disclaimer",
                    "本结论由AI辅助生成，仅供研究演示，不构成任何法律意见或判决。",
                )
                verdict.setdefault("next_steps", [])
            else:
                raise ValueError("审判长未返回有效 JSON")
        except Exception:
            verdict = {
                "truth_hypothesis": "（解析失败，请重试或调整模型）",
                "evidence_chain": [],
                "doubts": [],
                "recommendation": "",
                "next_steps": [],
                "disclaimer": "",
            }

    await sink({"kind": "verdict", "verdict": verdict})
    await sink({"kind": "judge_end", "consensus": True})
    return {"consensus": True, "verdict": verdict, "log": [{"event": "verdict"}]}


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
