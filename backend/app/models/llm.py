from __future__ import annotations
import asyncio
from typing import Any, AsyncIterator, List, Optional
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from app.config import settings

# LLM 客户端缓存：按 (provider, model, base_url, temperature) 复用实例，
# 避免每场辩论 7 专家 × N 轮创建数十个 HTTP 客户端。
_llm_cache: dict = {}


class MockChatModel(BaseChatModel):
    """离线可用的大模型替身：在没有 API Key 时保证整套系统完整跑通。
    会依据 system 中的角色名生成结构化占位陈述，用于演示多智能体辩论流程。"""
    model_config = {"arbitrary_types_allowed": True}
    role_hint: str = "expert"

    @property
    def _llm_type(self) -> str:
        return "mock-chat-model"

    def _build(self, messages: List[BaseMessage]) -> str:
        role = self.role_hint
        # 从最近的 user 消息中提取案件关键词，让模拟陈述更贴合案情
        case_hint = ""
        for m in reversed(messages):
            if isinstance(m, HumanMessage) and m.content:
                text = str(m.content)
                # 取前 60 字作为案件上下文提示
                case_hint = text[:60].replace("\n", " ")
                break
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
        return self._generate(messages, stop, run_manager, **kwargs)

    async def astream(
        self, input: Any, config=None, **kwargs
    ) -> AsyncIterator[AIMessageChunk]:
        messages = input if isinstance(input, list) else [input]
        text = self._build(messages)
        for chunk in text.split("，"):
            yield AIMessageChunk(content=chunk + "，")
            await asyncio.sleep(0.01)


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
