from __future__ import annotations

import os
from pathlib import Path

from app.config import settings, MAX_ROUNDS

ENV_PATH = Path(os.path.dirname(os.path.dirname(__file__)), ".env")

# 设置字段 → .env 键名：除 temperature 外全部与字段大写一致，
# 显式列出避免手工映射漏项
_MAP = {k: k.upper() for k in (
    "llm_provider",
    "llm_api_key",
    "llm_base_url",
    "llm_model",
    "ollama_base_url",
    "ollama_model",
    "max_rounds",
    "human_in_the_loop",
    "judge_mode",
    "hitl_timeout",
    "memory_rounds",
    "context_char_limit",
    "max_concurrency",
    "llm_timeout",
    "llm_max_tokens",
    "web_search_enabled",
    "intake_model",
    "code_sandbox_enabled",
    "code_sandbox_backend",
    "code_sandbox_docker_image",
    "code_sandbox_python",
)}
_MAP["temperature"] = "LLM_TEMPERATURE"


def current() -> dict:
    return {
        "llm_provider": settings.llm_provider,
        "llm_api_key": settings.llm_api_key,
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
        "ollama_base_url": settings.ollama_base_url,
        "ollama_model": settings.ollama_model,
        "temperature": settings.temperature,
        "max_rounds": settings.max_rounds,
        "human_in_the_loop": settings.human_in_the_loop,
        "judge_mode": settings.judge_mode,
        "hitl_timeout": settings.hitl_timeout,
        "memory_rounds": settings.memory_rounds,
        "context_char_limit": settings.context_char_limit,
        "max_concurrency": settings.max_concurrency,
        "llm_timeout": settings.llm_timeout,
        "llm_max_tokens": settings.llm_max_tokens,
        "web_search_enabled": settings.web_search_enabled,
        "intake_model": settings.intake_model,
        "code_sandbox_enabled": settings.code_sandbox_enabled,
        "code_sandbox_backend": settings.code_sandbox_backend,
        "code_sandbox_docker_image": settings.code_sandbox_docker_image,
        "code_sandbox_python": settings.code_sandbox_python,
    }


def update(payload: dict) -> dict:
    for f in (
        "llm_provider",
        "llm_api_key",
        "llm_base_url",
        "llm_model",
        "ollama_base_url",
        "ollama_model",
    ):
        if f in payload and payload[f] is not None:
            v = str(payload[f])
            if f == "llm_provider":
                v = v.strip().lower()
                if v not in ("mock", "openai", "openai_compatible", "ollama"):
                    v = "mock"  # 非法值回退到 mock，避免静默使用未知 provider
            setattr(settings, f, v)

    if "temperature" in payload and payload["temperature"] is not None:
        try:
            settings.temperature = float(payload["temperature"])
        except (TypeError, ValueError):
            pass

    if "max_rounds" in payload and payload["max_rounds"] is not None:
        try:
            settings.max_rounds = max(1, min(MAX_ROUNDS, int(payload["max_rounds"])))
        except (TypeError, ValueError):
            pass

    if "human_in_the_loop" in payload and payload["human_in_the_loop"] is not None:
        settings.human_in_the_loop = bool(payload["human_in_the_loop"])

    if "judge_mode" in payload and payload["judge_mode"] is not None:
        v = str(payload["judge_mode"]).strip().lower()
        settings.judge_mode = "human" if v == "human" else "ai"

    if "hitl_timeout" in payload and payload["hitl_timeout"] is not None:
        try:
            settings.hitl_timeout = max(0, min(86400, int(payload["hitl_timeout"])))
        except (TypeError, ValueError):
            pass
    if "web_search_enabled" in payload and payload["web_search_enabled"] is not None:
        settings.web_search_enabled = bool(payload["web_search_enabled"])
    for _f in ("memory_rounds", "context_char_limit", "max_concurrency", "llm_timeout", "llm_max_tokens"):
        if _f in payload and payload[_f] is not None:
            try:
                setattr(settings, _f, max(0, min(50000, int(payload[_f]))))
            except (TypeError, ValueError):
                pass

    if "intake_model" in payload and payload["intake_model"] is not None:
        settings.intake_model = str(payload["intake_model"]).strip() or "step-3.7-flash"

    if (
        "code_sandbox_enabled" in payload
        and payload["code_sandbox_enabled"] is not None
    ):
        settings.code_sandbox_enabled = bool(payload["code_sandbox_enabled"])
    if "code_sandbox_backend" in payload and payload["code_sandbox_backend"] is not None:
        v = str(payload["code_sandbox_backend"]).strip().lower()
        settings.code_sandbox_backend = v if v in ("auto", "subprocess", "docker") else "auto"
    if (
        "code_sandbox_docker_image" in payload
        and payload["code_sandbox_docker_image"] is not None
    ):
        settings.code_sandbox_docker_image = (
            str(payload["code_sandbox_docker_image"]).strip() or "python:3.12-slim"
        )
    if "code_sandbox_python" in payload and payload["code_sandbox_python"] is not None:
        settings.code_sandbox_python = (
            str(payload["code_sandbox_python"]).strip() or "python3"
        )

    # 模型相关配置变更后清空 LLM 客户端缓存，避免复用旧连接
    if any(k in payload for k in ("llm_provider", "llm_api_key", "llm_base_url", "llm_model", "ollama_base_url", "ollama_model", "temperature")):
        try:
            from app.models.llm import clear_llm_cache
            clear_llm_cache()
        except Exception:
            pass

    _persist()
    return current()


def _persist() -> None:
    try:
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []

    env: dict[str, str] = {}
    for line in lines:
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

    values = {
        "LLM_PROVIDER": settings.llm_provider,
        "LLM_API_KEY": settings.llm_api_key,
        "LLM_BASE_URL": settings.llm_base_url,
        "LLM_MODEL": settings.llm_model,
        "OLLAMA_BASE_URL": settings.ollama_base_url,
        "OLLAMA_MODEL": settings.ollama_model,
        "LLM_TEMPERATURE": str(settings.temperature),
        "MAX_ROUNDS": str(settings.max_rounds),
        "HUMAN_IN_THE_LOOP": "true" if settings.human_in_the_loop else "false",
        "JUDGE_MODE": settings.judge_mode,
        "HITL_TIMEOUT": str(settings.hitl_timeout),
        "MEMORY_ROUNDS": str(settings.memory_rounds),
        "CONTEXT_CHAR_LIMIT": str(settings.context_char_limit),
        "MAX_CONCURRENCY": str(settings.max_concurrency),
        "LLM_TIMEOUT": str(settings.llm_timeout),
        "LLM_MAX_TOKENS": str(settings.llm_max_tokens),
        "WEB_SEARCH_ENABLED": "true" if settings.web_search_enabled else "false",
        "INTAKE_MODEL": settings.intake_model,
        "CODE_SANDBOX_ENABLED": "true" if settings.code_sandbox_enabled else "false",
        "CODE_SANDBOX_PYTHON": settings.code_sandbox_python,
    }

    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if "=" in line:
            k = line.partition("=")[0].strip()
            if k in values:
                if k not in seen:
                    out.append(f"{k}={values[k]}")
                    seen.add(k)
                continue
        out.append(line)
    for k, v in values.items():
        if k not in seen:
            out.append(f"{k}={v}")

    # 原子替换：中断不会留下半截 .env 让下次启动读到损坏配置
    tmp = ENV_PATH.with_name(ENV_PATH.name + ".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.replace(ENV_PATH)
