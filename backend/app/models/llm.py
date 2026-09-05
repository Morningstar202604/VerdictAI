from __future__ import annotations
import asyncio
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
    _QA_MARK = "你是审判长。 辩论已终结、裁决已作出。"

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
    role_hint: str = "expert", model: str = None, temperature: float = None
) -> BaseChatModel:
    provider = settings.llm_provider.lower()
    model = model or settings.llm_model
    temperature = temperature if temperature is not None else settings.temperature

    if provider == "mock":
        m = MockChatModel()
        m.role_hint = role_hint
        return m

    if provider in ("openai", "openai_compatible", "ollama"):
        # 缓存键：同一组参数复用同一个客户端实例
        cache_key = (provider, model, settings.llm_base_url, settings.ollama_base_url, temperature)
        cached = _llm_cache.get(cache_key)
        if cached is not None:
            return cached

        from langchain_openai import ChatOpenAI
        base_url = settings.llm_base_url or None
        if provider == "ollama":
            model = settings.ollama_model
            base_url = settings.ollama_base_url
            api_key = "ollama"
        else:
            api_key = settings.llm_api_key or "EMPTY"
        # langchain-openai 1.6 对 SecretStr 处理有 bug，必须传明文 str
        llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            streaming=False,
            # 思维链类模型（如 gemini 系列）会把大量推理写入 reasoning_content，
            # 若不显式给足 max_tokens，JSON 输出会被截断导致解析失败
            max_tokens=settings.llm_max_tokens or 8000,
        )
        _llm_cache[cache_key] = llm
        return llm

    # 未知 provider 回退到 mock
    m = MockChatModel()
    m.role_hint = role_hint
    return m


def is_mock() -> bool:
    return settings.llm_provider.lower() == "mock"


def clear_llm_cache() -> None:
    """清空 LLM 客户端缓存（设置变更后调用）。"""
    _llm_cache.clear()
