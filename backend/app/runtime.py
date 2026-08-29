from __future__ import annotations

import os

from app.config import settings

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")

_MAP = {
    "llm_provider": "LLM_PROVIDER",
    "llm_api_key": "LLM_API_KEY",
    "llm_base_url": "LLM_BASE_URL",
    "llm_model": "LLM_MODEL",
    "ollama_base_url": "OLLAMA_BASE_URL",
    "ollama_model": "OLLAMA_MODEL",
    "temperature": "LLM_TEMPERATURE",
    "max_rounds": "MAX_ROUNDS",
    "human_in_the_loop": "HUMAN_IN_THE_LOOP",
    "judge_mode": "JUDGE_MODE",
    "intake_model": "INTAKE_MODEL",
    "code_sandbox_enabled": "CODE_SANDBOX_ENABLED",
    "code_sandbox_python": "CODE_SANDBOX_PYTHON",
}


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
        "intake_model": settings.intake_model,
        "code_sandbox_enabled": settings.code_sandbox_enabled,
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
            setattr(settings, f, str(payload[f]))

    if "temperature" in payload and payload["temperature"] is not None:
        try:
            settings.temperature = float(payload["temperature"])
        except (TypeError, ValueError):
            pass

    if "max_rounds" in payload and payload["max_rounds"] is not None:
        try:
            settings.max_rounds = max(1, min(10, int(payload["max_rounds"])))
        except (TypeError, ValueError):
            pass

    if "human_in_the_loop" in payload and payload["human_in_the_loop"] is not None:
        settings.human_in_the_loop = bool(payload["human_in_the_loop"])

    if "judge_mode" in payload and payload["judge_mode"] is not None:
        v = str(payload["judge_mode"]).strip().lower()
        settings.judge_mode = "human" if v == "human" else "ai"

    if "intake_model" in payload and payload["intake_model"] is not None:
        settings.intake_model = str(payload["intake_model"]).strip() or "step-3.7-flash"

    if (
        "code_sandbox_enabled" in payload
        and payload["code_sandbox_enabled"] is not None
    ):
        settings.code_sandbox_enabled = bool(payload["code_sandbox_enabled"])
    if "code_sandbox_python" in payload and payload["code_sandbox_python"] is not None:
        settings.code_sandbox_python = (
            str(payload["code_sandbox_python"]).strip() or "python3"
        )

    _persist()
    return current()


def _persist() -> None:
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
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

    tmp = ENV_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, ENV_PATH)
