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
    # 审判长落槌方式：ai=AI 自动裁决；human=由人类法官最终裁决
    judge_mode: str = os.getenv("JUDGE_MODE", "ai")
    # 人类审判长落槌等待超时（秒）：0=不限时
    hitl_timeout: int = int(os.getenv("HITL_TIMEOUT", "300"))
    # 卷宗预处理专用模型
    intake_model: str = os.getenv("INTAKE_MODEL", "step-3.7-flash")
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    # 智能体运行环境（沙箱）
    code_sandbox_enabled: bool = (
        os.getenv("CODE_SANDBOX_ENABLED", "true").lower() == "true"
    )
    code_sandbox_python: str = os.getenv(
        "CODE_SANDBOX_PYTHON", sys.executable or "python3"
    )
    # 服务
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8787"))
    cors_origins: str = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:8787,http://127.0.0.1:8787,http://localhost:5173,http://127.0.0.1:5173",
    )
    max_request_size: int = int(os.getenv("MAX_REQUEST_SIZE", str(25 * 1024 * 1024)))
    access_password: str = os.getenv("ACCESS_PASSWORD", "")
    # Agent 工程
    memory_rounds: int = int(os.getenv("MEMORY_ROUNDS", "2"))
    context_char_limit: int = int(os.getenv("CONTEXT_CHAR_LIMIT", "12000"))
    max_concurrency: int = int(os.getenv("MAX_CONCURRENCY", "4"))
    llm_timeout: int = int(os.getenv("LLM_TIMEOUT", "180"))
    web_search_enabled: bool = os.getenv("WEB_SEARCH_ENABLED", "true").lower() == "true"
    # 数据目录
    data_dir: str = os.getenv(
        "DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data")
    )
    sandbox_out_dir: str = os.getenv(
        "SANDBOX_OUT_DIR", os.path.join(data_dir, "sandbox_out")
    )

    def __post_init__(self):
        """配置校验与合理范围钳制，避免非法值导致运行时崩溃。"""
        import warnings

        valid_providers = ("mock", "openai", "openai_compatible", "ollama")
        if self.llm_provider.lower() not in valid_providers:
            warnings.warn(f"未知 LLM_PROVIDER='{self.llm_provider}'，已回退为 mock")
            self.llm_provider = "mock"
        self.max_rounds = max(1, min(6, int(self.max_rounds)))
        self.temperature = max(0.0, min(2.0, float(self.temperature)))
        if self.judge_mode not in ("ai", "human"):
            self.judge_mode = "ai"
        if self.hitl_timeout != 0 and self.hitl_timeout < 10:
            self.hitl_timeout = 300
        self.port = max(1, min(65535, int(self.port)))
        self.memory_rounds = max(0, min(6, int(self.memory_rounds)))
        self.max_concurrency = max(1, min(7, int(self.max_concurrency)))
        if self.context_char_limit != 0 and self.context_char_limit < 1000:
            self.context_char_limit = 12000
        self.max_request_size = max(1024 * 1024, int(self.max_request_size))
        if not os.path.isabs(self.data_dir):
            self.data_dir = os.path.normpath(
                os.path.join(os.path.dirname(__file__), "..", self.data_dir)
            )
        if not os.path.isabs(self.sandbox_out_dir):
            self.sandbox_out_dir = os.path.normpath(
                os.path.join(os.path.dirname(__file__), "..", self.sandbox_out_dir)
            )


settings = Settings()
