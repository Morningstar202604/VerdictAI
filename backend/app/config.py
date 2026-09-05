from __future__ import annotations
import os
import sys
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


# ── 全局常量 ──────────────────────────────────────────────────────────────────
# 图表/文档处理上限
MAX_CHARTS_PER_CASE = 4
MAX_PDF_PAGES = 50
MAX_PDF_CHARS = 60000
# 辩论轮次上限
MAX_ROUNDS = 6
# 并发与上下文
MAX_CONCURRENCY = 7
MAX_MEMORY_ROUNDS = 6
MIN_CONTEXT_CHAR_LIMIT = 1000
DEFAULT_CONTEXT_CHAR_LIMIT = 12000
# HITL 超时下限（秒）
MIN_HITL_TIMEOUT = 10
DEFAULT_HITL_TIMEOUT = 300
# 请求体大小下限（字节）
MIN_REQUEST_SIZE = 1024 * 1024


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
    # 沙箱后端：auto=有 Docker 用容器（断网+资源上限），否则本机子进程；
    # subprocess=强制本机；docker=强制容器（不可用时报错提示）
    code_sandbox_backend: str = os.getenv("CODE_SANDBOX_BACKEND", "auto")
    code_sandbox_docker_image: str = os.getenv(
        "CODE_SANDBOX_DOCKER_IMAGE", "python:3.12-slim"
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
    # 单次 LLM 调用最大输出 token 数（思维链类模型 reasoning_content 占用 token，
    # 若限制过小会导致 JSON/长分析被截断），0 表示交给平台默认
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "0"))
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
        self.max_rounds = max(1, min(MAX_ROUNDS, int(self.max_rounds)))
        self.temperature = max(0.0, min(2.0, float(self.temperature)))
        if self.judge_mode not in ("ai", "human"):
            self.judge_mode = "ai"
        if self.code_sandbox_backend not in ("auto", "subprocess", "docker"):
            self.code_sandbox_backend = "auto"
        if self.hitl_timeout != 0 and self.hitl_timeout < MIN_HITL_TIMEOUT:
            self.hitl_timeout = DEFAULT_HITL_TIMEOUT
        self.port = max(1, min(65535, int(self.port)))
        self.memory_rounds = max(0, min(MAX_MEMORY_ROUNDS, int(self.memory_rounds)))
        self.max_concurrency = max(1, min(MAX_CONCURRENCY, int(self.max_concurrency)))
        if self.context_char_limit != 0 and self.context_char_limit < MIN_CONTEXT_CHAR_LIMIT:
            self.context_char_limit = DEFAULT_CONTEXT_CHAR_LIMIT
        self.max_request_size = max(MIN_REQUEST_SIZE, int(self.max_request_size))
        if not os.path.isabs(self.data_dir):
            self.data_dir = os.path.normpath(
                os.path.join(os.path.dirname(__file__), "..", self.data_dir)
            )
        if not os.path.isabs(self.sandbox_out_dir):
            self.sandbox_out_dir = os.path.normpath(
                os.path.join(os.path.dirname(__file__), "..", self.sandbox_out_dir)
            )


settings = Settings()


# 辩论运行期会读到的全部可变配置。辩论开场拍快照（debate_snapshot），
# 之后 settings 再被 POST /api/settings 修改也只影响新辩论，
# 正在进行的会话完全不受干扰（见 CONTRIBUTING「Session config」）。
_SNAPSHOT_FIELDS = (
    "llm_provider",
    "llm_api_key",
    "llm_base_url",
    "llm_model",
    "ollama_base_url",
    "ollama_model",
    "temperature",
    "max_rounds",
    "judge_mode",
    "hitl_timeout",
    "memory_rounds",
    "context_char_limit",
    "llm_timeout",
    "llm_max_tokens",
    "web_search_enabled",
    "intake_model",
)


def debate_snapshot() -> dict:
    return {k: getattr(settings, k) for k in _SNAPSHOT_FIELDS}
