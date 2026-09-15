from __future__ import annotations
import asyncio
import hashlib
import json
from collections import OrderedDict
from typing import Any, AsyncIterator, List
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from app.config import settings

# LLM 客户端缓存：按 (provider, model, base_url, temperature) 复用实例，
# 避免每场辩论 7 专家 × N 轮创建数十个 HTTP 客户端。
_llm_cache: dict = {}

# 浏览器 UA：规避部分 OpenAI 兼容中转的 WAF 按 openai SDK 默认 UA 拦截（403）
_BROWSER_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}

# LLM 响应缓存（P0-2）：同一 prompt（模型+消息序列哈希）命中直接回放，
# 大幅降低重复推理的 API 成本与首字延迟；LRU 上限由 settings.llm_cache_size 控制。
_response_cache: "OrderedDict[str, str]" = OrderedDict()
_cache_stats: dict = {"hits": 0, "misses": 0}


def llm_cache_stats() -> dict:
    return dict(_cache_stats)


def llm_cache_enabled() -> bool:
    return settings.llm_cache_size > 0


def _cache_key(model: str, messages: List[BaseMessage]) -> str:
    """响应缓存键：模型名 + 每条消息的类型/名称/内容（JSON 序列化）。"""
    parts: List[str] = [model or ""]
    for m in messages:
        seg = type(m).__name__
        if getattr(m, "name", None):
            seg += "|" + str(m.name)
        try:
            seg += "|" + json.dumps(m.content, ensure_ascii=False, default=str)
        except Exception:
            seg += "|" + str(m.content)
        parts.append(seg)
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def response_cache_get(model: str, messages: List[BaseMessage]) -> str | None:
    """命中返回缓存文本；未命中返回 None 并累计 miss 计数。上限 0 时关闭。"""
    if not llm_cache_enabled() or not messages:
        return None
    key = _cache_key(model, messages)
    text = _response_cache.get(key)
    if text is None:
        _cache_stats["misses"] += 1
        return None
    _cache_stats["hits"] += 1
    _response_cache.move_to_end(key)  # LRU：命中提升到末尾
    return text


def response_cache_put(model: str, messages: List[BaseMessage], text: str) -> None:
    if not llm_cache_enabled() or not messages or not text:
        return
    key = _cache_key(model, messages)
    _response_cache[key] = text
    _response_cache.move_to_end(key)
    while len(_response_cache) > settings.llm_cache_size:
        _response_cache.popitem(last=False)  # 淘汰最久未用


def clear_response_cache() -> None:
    _response_cache.clear()
    _cache_stats["hits"] = 0
    _cache_stats["misses"] = 0


class MockChatModel(BaseChatModel):
    """离线可用的大模型替身：在没有 API Key 时保证整套系统完整跑通。
    会依据 system 中的角色名生成结构化占位陈述，用于演示多智能体辩论流程。
    当收到"卷宗预处理（意图识别/结构化抽取）"类提示词时，引擎侧会真正执行
    意图分类与人员/证据/时间线/法条抽取，输出与真实 LLM 相同的 JSON 契约，
    确保 AI 自主预处理链路（PDF 上传 → 抽取 → 分派）完整运转。"""
    model_config = {"arbitrary_types_allowed": True}
    role_hint: str = "expert"
    _INTAKE_MARK = "只输出一个 JSON 对象"
    _IMG_MARK = "请简要描述这张图片中与案件相关的信息"
    _QA_MARK = "你是审判长。辩论已终结、裁决已作出。"

    @property
    def _llm_type(self) -> str:
        return "mock-chat-model"

    # ---------- 引擎侧 AI 自主能力 ----------

    def _last_user_text(self, messages) -> str:
        for m in reversed(messages):
            if isinstance(m, HumanMessage) and m.content:
                if isinstance(m.content, list):
                    parts = [str(x.get("text", "")) for x in m.content if isinstance(x, dict) and x.get("type") == "text"]
                    return "\n".join(parts)
                return str(m.content)
        return ""

    def _mock_intake_json(self, text: str) -> str:
        """引擎按 prompt 契约自主执行：意图识别 + 分类 + 结构化抽取，输出 JSON。"""
        import json as _json
        import re as _re

        def find(pred, default=""):
            for line in text.splitlines():
                line = line.strip()
                if line and pred(line):
                    return line
            return default

        def is_intent_line(line):
            return any(w in line for w in ("意图", "目的", "本案", "案件", "纠纷", "审查"))

        def is_person_line(line):
            roles = ("嫌疑人", "被害人", "证人", "被告", "原告", "死者", "丈夫", "妻子", "儿子", "女儿", "合伙人", "联系人", "司机")
            return any(r in line for r in roles)

        ROLE_PREFIX = ("嫌疑人", "被害人", "证人", "被告", "原告", "死者")

        def is_evidence_line(line):
            marks = ("证据", "物证", "书证", "DNA", "指纹", "监控", "法医", "尸检", "血迹", "凶器", "笔录", "短信", "微信", "通话", "转账", "E-", "鉴定")
            return any(m in line for m in marks)

        def is_time_line(line):
            return bool(_re.search(r"(\d{4}年|\d{1,2}月|\d{1,2}日|凌晨|上午|下午|晚间|\d{2}[:：]\d{2})", line))

        def is_law_line(line):
            return bool(_re.search(r"《[^》]+》第[一二三四五六七八九十百0-9]+条", line))

        # 1) 意图识别/分类（优先级：经济犯罪 → 暴力/命案 → 刑事一般 → 民事 → 行政）
        intent_src = find(is_intent_line)
        if any(w in text for w in ("诈骗", "骗取", "货款", "虚开", "洗钱", "挪用", "职务侵占", "伪造")):
            intent = "刑事案件·经济犯罪审查（涉嫌诈骗/伪造类）"
        elif any(w in text for w in ("故意杀", "命案", "他杀", "尸检", "猝死", "窒息")):
            intent = "刑事案件·真相还原（涉嫌故意杀人）"
        elif any(w in text for w in ("刑事案件", "侦查", "刑拘", "逮捕", "公诉")):
            intent = "刑事案件·事实还原与责任认定"
        elif any(w in text for w in ("民事", "合同", "违约", "借贷", "侵权", "赔偿", "欠款")):
            intent = "民事纠纷·责任划分"
        elif any(w in text for w in ("行政", "处罚", "复议", "许可", "征收")):
            intent = "行政争议·合法性审查"
        else:
            intent = "综合研判·事实与责任厘清"
        tags = []
        for k, v in (("合同", "合同纠纷"), ("杀", "刑事命案"), ("债", "债权债务"), ("赔", "侵权赔偿"), ("诈", "涉嫌诈骗")):
            if k in text:
                tags.append(v)
        tags = tags[:4] or ["事实调查"]
        intensity = "high" if any(w in text for w in ("重大", "命案", "复杂", "争议大", "存疑")) else "medium"
        guide = "请以证据为中心客观分析，严格区分事实与推测；逐项核验关键证据的可靠性、保管链与时间线一致性，避免先入为主；对不利解释做反事实检验。"
        summary = (intent_src or text.splitlines()[0] if text.strip() else "无材料")[:280]

        # 2) 结构化抽取
        persons, evidence, timeline, statutes = [], [], [], []
        seen = set()
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("图片材料") or line.startswith("（"):
                continue
            if is_person_line(line) and len(line) < 120:
                key = "p:" + line[:24]
                if key not in seen:
                    seen.add(key)
                    name = line
                    for rp in ROLE_PREFIX:
                        if name.startswith(rp):
                            name = name[len(rp):].lstrip("，,、 ：:")
                            break
                    name = name.split("，")[0].split(",")[0].split("，")[0][:14]
                    persons.append({"name": name, "role": next((r for r in ("嫌疑人", "被害人", "证人", "被告", "原告", "死者", "合伙人") if r in line), "涉案人员"), "desc": line[:80]})
            if is_evidence_line(line) and len(line) < 200:
                key = "e:" + line[:24]
                if key not in seen:
                    seen.add(key)
                    evid = _re.search(r"\[?E-?\d{2}\]?", line)
                    evidence.append({"id": evid.group(0).strip("[]") if evid else f"E-{len(evidence)+1:02d}", "type": next((t for t in ("DNA", "指纹", "监控", "物证", "书证", "法医", "尸检", "血迹", "凶器", "笔录", "微信", "短信", "鉴定") if t in line), "物证"), "desc": line[:120]})
            if is_time_line(line):
                key = "t:" + line[:24]
                if key not in seen:
                    seen.add(key)
                    mt = _re.match(r"^(?:([^，。；\s]{2,18})[，。；]?)?([^，。；]{2,40})", line)
                    timeline.append({"time": mt.group(1) if mt and _re.search(r"(\d|凌晨|上午|下午|晚间|月|日)", mt.group(1)) else (mt.group(1) or "待核"), "event": (mt.group(2) if mt else line)[:80], "source": "上传卷宗"})
            if is_law_line(line):
                key = "l:" + line[:24]
                if key not in seen:
                    seen.add(key)
                    law = _re.search(r"《[^》]+》第[一二三四五六七八九十百0-9]+条", line)
                    statutes.append({"topic": law.group(0) if law else "相关法条", "text": line[:100]})
        # 去重前 N 条
        persons, evidence, timeline, statutes = persons[:12], evidence[:16], timeline[:16], statutes[:6]

        out = {
            "intent": intent,
            "intent_tags": tags,
            "reasoning_intensity": intensity,
            "global_guidance": guide,
            "summary": summary,
            "extracted": {"persons": persons, "evidence": evidence, "timeline": timeline, "statutes": statutes, "finance": []},
        }
        return _json.dumps(out, ensure_ascii=False)

    def _mock_image_caption(self, text: str) -> str:
        name = ""
        for m_ in reversed(text.splitlines()):
            if "图片" in m_ or ".png" in m_.lower() or ".jpg" in m_.lower():
                name = m_.strip()
                break
        return f"{name}：（引擎已识别该图片材料，将在辩论中交由相关专家结合卷宗分析痕迹/文书内容）" if name else "（引擎已登记该图片材料，供专家结合卷宗分析）"

    def _mock_qa(self, case_hint: str) -> str:
        return (
            f"【审判长·模拟陈述】基于卷宗材料（{case_hint}…），针对该问题：现有证据关于该争议点"
            f"主要依赖言词证据与部分实物证据，可靠性与保管链仍需补强；建议补充复核鉴定并以客观证据为主、"
            f"言词证据为辅综合认定。（模拟模式：未调用真实大模型）"
        )

    def _build(self, messages: List[BaseMessage]) -> str:
        role = self.role_hint
        user_text = self._last_user_text(messages)
        # 分案法官 → 卷宗预处理（意图识别/分类/抽取）
        if self._INTAKE_MARK in user_text:
            return self._mock_intake_json(user_text)
        # 图片识别（分案法官发送图片时）
        if self._IMG_MARK in user_text and any(isinstance(ct, dict) and ct.get("type") == "image_url" for m_ in messages if isinstance(m_, HumanMessage) for ct in (m_.content if isinstance(m_.content, list) else [])):
            return self._mock_image_caption(user_text)
        # 裁决质询（审判长追问）
        if self._QA_MARK in user_text:
            return self._mock_qa(user_text[:60].replace("\n", " "))
        # 从最近的 user 消息中提取案件关键词，让模拟陈述更贴合案情
        case_hint = user_text[:60].replace("\n", " ")
        prefix = f"【{role}·模拟陈述】"
        if case_hint:
            return (
                f"{prefix}基于卷宗材料（{case_hint}…），我的判断是：必须让物证、口供与时间线"
                f"三者交叉验证。本案目前证据链尚未完全闭合，存在若干需澄清的可疑点，"
                f"建议下一轮聚焦核实关键证据的一致性。（模拟模式：未调用真实大模型）"
            )
        return (
            f"{prefix}基于当前卷宗，我的判断是：必须让物证、口供与时间线"
            f"三者交叉验证。本案目前证据链尚未完全闭合，存在若干需澄清的可疑点，"
            f"建议下一轮聚焦核实关键证据的一致性。（模拟模式：未调用真实大模型）"
        )

    def _generate(
        self, messages, stop=None, run_manager: Any = None, **kwargs
    ) -> ChatResult:
        text = self._build(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _agenerate(
        self, messages, stop=None, run_manager=None, **kwargs
    ) -> ChatResult:
        text = self._build(messages)
        # 模拟真实 LLM 的推理耗时：按内容长度估算，使多智能体辩论有可感知、
        # 可操作的进行时长（真实用户可在期间观察、插话、停止）
        await asyncio.sleep(min(2.5, 0.45 + len(text) * 0.01))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def astream(
        self, input: Any, config=None, **kwargs
    ) -> AsyncIterator[AIMessageChunk]:
        messages = input if isinstance(input, list) else [input]
        text = self._build(messages)
        for chunk in text.split("，"):
            yield AIMessageChunk(content=chunk + "，")
            await asyncio.sleep(0.06)


def get_llm(
    role_hint: str = "expert",
    model: str = None,
    temperature: float = None,
    cfg: dict = None,
) -> BaseChatModel:
    """cfg 是辩论开场拍的配置快照（app.config.debate_snapshot）：
    传入时模型选择完全由快照决定，与全局 settings 的后续变更解耦；
    不传（辩论外的端点）沿用全局配置。"""
    c = cfg or {}
    provider = str(c.get("llm_provider") or settings.llm_provider).lower()
    model = model or c.get("llm_model") or settings.llm_model
    if temperature is None:
        temperature = c.get("temperature", settings.temperature)

    if provider == "mock":
        m = MockChatModel()
        m.role_hint = role_hint
        return m

    if provider in ("openai", "openai_compatible", "ollama"):
        base_url = c.get("llm_base_url") or settings.llm_base_url or None
        ollama_base_url = c.get("ollama_base_url") or settings.ollama_base_url
        max_tokens = c.get("llm_max_tokens", settings.llm_max_tokens)
        # 缓存键：同一组参数复用同一个客户端实例（max_tokens 参与键，
        # 避免不同快照间复用截断配置不同的客户端）
        cache_key = (
            provider,
            model,
            base_url,
            ollama_base_url,
            temperature,
            max_tokens if provider != "ollama" else 0,
        )
        cached = _llm_cache.get(cache_key)
        if cached is not None:
            return cached

        from langchain_openai import ChatOpenAI

        if provider == "ollama":
            model = c.get("ollama_model") or settings.ollama_model
            base_url = ollama_base_url
            api_key = "ollama"
        else:
            api_key = c.get("llm_api_key") or settings.llm_api_key or "EMPTY"
        # langchain-openai 1.6 对 SecretStr 处理有 bug，必须传明文 str
        llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            streaming=False,
            default_headers=_BROWSER_UA,
            # 思维链类模型（如 gemini 系列）会把大量推理写入 reasoning_content，
            # 若不显式给足 max_tokens，JSON 输出会被截断导致解析失败
            max_tokens=max_tokens or 8000,
        )
        _llm_cache[cache_key] = llm
        return llm

    # 未知 provider 回退到 mock
    m = MockChatModel()
    m.role_hint = role_hint
    return m


def is_mock(cfg: dict = None) -> bool:
    provider = (cfg or {}).get("llm_provider") or settings.llm_provider
    return str(provider).lower() == "mock"


def stream_enabled(cfg: dict = None) -> bool:
    mode = (cfg or {}).get("stream_experts") or settings.stream_experts
    mode = str(mode).lower()
    if mode == "off":
        return False
    if mode == "on":
        return True
    return not is_mock(cfg)  # auto：非 mock 供应商启用


# 端点流式支持缓存：首块前失败的端点本次进程内不再尝试流式
_stream_unsupported: set = set()


async def stream_or_invoke(llm, messages, on_chunk=None, timeout=None, key: str = ""):
    """优先真流式：chunk 到达即回调 on_chunk(文本增量)，返回聚合后的消息对象
    （AIMessageChunk 聚合体，含 content / tool_calls，语义与整段返回一致）。

    首块之前失败视为端点不支持流式：记入 _stream_unsupported 并抛出，
    由调用方回退非流式重试（此时没有任何字节发出，重试不会重复输出）；
    已经流出部分内容后的失败同样抛出——调用方按该专家失败处理，
    绝不重试，否则用户会看到重复发言。"""
    if key and key in _stream_unsupported:
        return await llm.ainvoke(messages)

    merged = None
    emitted = False

    async def _consume():
        nonlocal merged, emitted
        async for chunk in llm.astream(messages):
            emitted = True
            merged = chunk if merged is None else merged + chunk
            text = chunk.text() if hasattr(chunk, "text") else str(chunk.content or "")
            if text and on_chunk:
                r = on_chunk(text)
                # 回调可为同步或异步函数（nodes.py 传的是 async _on）
                if asyncio.iscoroutine(r):
                    await r

    try:
        if timeout and timeout > 0:
            await asyncio.wait_for(_consume(), timeout=timeout)
        else:
            await _consume()
    except Exception:
        if not emitted:
            if key:
                _stream_unsupported.add(key)
        raise
    if merged is None:
        if key:
            _stream_unsupported.add(key)
        return await llm.ainvoke(messages)
    return merged


def clear_llm_cache() -> None:
    """清空 LLM 客户端缓存（设置变更后调用）。"""
    _llm_cache.clear()


# ------------------------- 成本核算（P2-6） -------------------------
# 用量面板/辩论记录把字符数换算为 token 与费用（USD）：默认单价 0=不核算。
# 对标大厂 Agent 平台的成本观测（OpenAI/LangSmith usage.cost）。


def estimate_cost(in_chars: int, out_chars: int) -> dict:
    """按配置单价估算一场/一次调用成本；单价为 0 时返回 cost=0（未核算）。"""
    cpt = max(0.1, float(getattr(settings, "llm_chars_per_token", 1.5)))
    in_tk = max(0, int(in_chars or 0)) / cpt
    out_tk = max(0, int(out_chars or 0)) / cpt
    p_in = float(getattr(settings, "llm_cost_per_1k_in", 0) or 0)
    p_out = float(getattr(settings, "llm_cost_per_1k_out", 0) or 0)
    return {
        "in_tokens": round(in_tk),
        "out_tokens": round(out_tk),
        "cost_usd": round((in_tk / 1000 * p_in) + (out_tk / 1000 * p_out), 6),
        "priced": bool(p_in or p_out),
    }


# ------------------------- 结构化输出统一设施（P2-1） -------------------------
# 大厂 Agent 的标准做法：输出必须强制 schema，而不是「提示词里写一句 + 正则碰运气」。
# 两级策略：
#   1) 模型侧原生结构化输出（with_structured_output Pydantic schema 强制解析）——
#      OpenAI/兼容端点用 function/tool calling 或 json_object 模式，模型侧保证结构；
#   2) 失败/不支持时回退「契约 + 严格解析 + 失败自动修复」：把解析错误回喂模型，
#      让模型在有错误提示的情况下自行修正一次（对标 DSPy/Self-Correction）。
# 全部失败返回 None，由调用方按节点既有降级策略处理，绝不中断辩论。


def _to_str_llm(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else str(p) for p in content)
    return str(content)


Sink = Any


async def structured_call(
    llm,
    messages: List[BaseMessage],
    parse: callable,  # 输入模型文本 -> 输出结构化对象；解析失败抛异常
    repair_hint: str = "",  # 修复提示词模板，可用 {error} 占位；
    fix_messages_builder: callable = None,  # 可覆盖默认修复消息构造（默认 原消息+解析失败+提示）
    with_schema: Any = None,  # Pydantic schema：开启模型侧结构化输出
    retries: int = 1,  # 契约路径的自动修复轮数
    timeout: int = None,
    sink: Sink = None,
    role_key: str = "",
    cache: bool = True,
):
    """结构化输出统一设施：优先 with_structured_output，回退契约+修复。
    返回 parse 的产物（dict/list），全部失败返回 None。"""
    if timeout is None:
        timeout = settings.llm_timeout
    model = getattr(llm, "model_name", "") or ""
    cacheable = (
        cache
        and bool(model)
        and type(llm).__name__ != "MockChatModel"
        and settings.llm_cache_size > 0
    )
    if cacheable:
        hit = response_cache_get(model, messages)
        if hit is not None:
            try:
                obj = parse(hit)
                if sink is not None:
                    try:
                        await sink(
                            {"kind": "llm_cache", "role": role_key, "hit": True, "model": model}
                        )
                    except Exception:
                        pass
                return obj
            except Exception:
                pass  # 缓存内容结构异常：按未命中重新生成

    async def _emit(kind: str, **kw) -> None:
        if sink is None:
            return
        try:
            await sink({"kind": kind, **kw})
        except Exception:
            pass

    # ── 路径 A：模型侧结构化输出（schema 强制） ──
    if with_schema is not None:
        try:
            sllm = llm.with_structured_output(with_schema)
            resp = await asyncio.wait_for(
                sllm.ainvoke(messages), timeout=timeout
            ) if timeout and timeout > 0 else await sllm.ainvoke(messages)
            if resp is None:
                raise ValueError("结构化输出返回空")
            # with_structured_output 返回 Pydantic 或 list[Pydantic]
            if hasattr(resp, "model_dump"):
                obj = resp.model_dump()
            elif isinstance(resp, list):
                obj = [m.model_dump() if hasattr(m, "model_dump") else m for m in resp]
            else:
                obj = resp
            if cacheable:
                try:
                    response_cache_put(model, messages, json.dumps(obj, ensure_ascii=False, default=str))
                except Exception:
                    pass
            await _emit("structured", role=role_key, method="schema", ok=True)
            return obj
        except Exception as e:  # noqa: BLE001
            # 端点不支持 tool calling / json_object：回退契约路径
            await _emit("structured", role=role_key, method="schema", ok=False, error=str(e)[:120])

    # ── 路径 B：契约 + 严格解析 + 自动修复 ──
    last_text = ""
    try:
        if timeout and timeout > 0:
            resp = await asyncio.wait_for(llm.ainvoke(messages), timeout=timeout)
        else:
            resp = await llm.ainvoke(messages)
        last_text = _to_str_llm(resp.content)
    except Exception as e:  # noqa: BLE001
        await _emit("structured", role=role_key, method="contract", ok=False, error=str(e)[:120])
        return None

    for attempt in range(retries + 1):
        if last_text and last_text.strip():
            try:
                obj = parse(last_text)
                if cacheable:
                    try:
                        response_cache_put(model, messages, last_text)
                    except Exception:
                        pass
                await _emit("structured", role=role_key, method="contract", ok=True, attempts=attempt + 1)
                return obj
            except Exception as pe:  # noqa: BLE001
                err = str(pe)[:200]
                if attempt >= retries:
                    await _emit(
                        "structured", role=role_key, method="contract", ok=False,
                        error=f"解析失败：{err}", attempts=attempt + 1,
                    )
                    return None
        else:
            err = "模型返回空内容"
        # 自动修复：把解析失败原因回喂模型让它自己修正（Self-Correct 路径）
        try:
            if fix_messages_builder is not None:
                fix_msgs = fix_messages_builder(last_text, err)
            else:
                # 括号保证三元表达式整段先求值，再与核心指令拼接——
                # 否则 Python「+ 高于条件表达式」的优先级会让 repair_hint
                # 分支丢掉「重新输出合法 JSON」指令，自动修复退化。
                fix_prompt = (
                    ((repair_hint + "\n\n") if repair_hint else "")
                    + "你上一轮输出的结构无法解析：{error}\n"
                    "请重新输出，只包含合法的 JSON（不要代码块、不要额外文字）。"
                )
                fix_msgs = messages + [
                    AIMessage(content=last_text or "（空）"),
                    HumanMessage(content=fix_prompt.replace("{error}", err)),
                ]
            if timeout and timeout > 0:
                resp = await asyncio.wait_for(llm.ainvoke(fix_msgs), timeout=timeout)
            else:
                resp = await llm.ainvoke(fix_msgs)
            last_text = _to_str_llm(resp.content)
        except Exception:  # noqa: BLE001
            return None
    return None
