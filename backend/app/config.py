from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    # 模型供应商: openai | openai_compatible | ollama | mock
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")

    # 本地 Ollama 默认地址
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")

    # 控制
    max_rounds: int = int(os.getenv("MAX_ROUNDS", "3"))
    human_in_the_loop: bool = os.getenv("HUMAN_IN_THE_LOOP", "false").lower() == "true"
    # 审判长落槌方式：ai=AI 自动裁决；human=由人类法官最终裁决（辩论末会暂停等待人类）
    judge_mode: str = os.getenv("JUDGE_MODE", "ai")
    # 卷宗预处理（意图识别/分派）专用模型：优先选 JSON 输出稳定的模型；留空则用主模型
    intake_model: str = os.getenv("INTAKE_MODEL", "step-3.7-flash")
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))

    # 智能体运行环境（沙箱）——默认开启：专家的计算/图表都在后端隔离子进程中执行
    code_sandbox_enabled: bool = (
        os.getenv("CODE_SANDBOX_ENABLED", "true").lower() == "true"
    )
    code_sandbox_python: str = os.getenv(
        "CODE_SANDBOX_PYTHON", sys.executable or "python3"
    )

    # 服务
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))

    # 数据目录
    data_dir: str = os.getenv(
        "DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")
    )

    # 沙箱生成的图表等产物目录（通过 /sandbox 静态路由对外提供）
    sandbox_out_dir: str = os.getenv(
        "SANDBOX_OUT_DIR", os.path.join(data_dir, "sandbox_out")
    )


settings = Settings()
