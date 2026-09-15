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
    # 默认直连自带本地推理引擎（tools/start_all.py 一键拉起，端口 9100）：
    # 展示的是确定性引擎对卷宗的真实分析，而非 mock 占位文本。
    # 需要云端模型时改 LLM_BASE_URL/LLM_API_KEY；离线兜底调试可显式切 mock。
    llm_provider: str = os.getenv("LLM_PROVIDER", "openai_compatible")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://127.0.0.1:9100/v1")
    llm_model: str = os.getenv("LLM_MODEL", "verdict-local")
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
    # 卷宗预处理专用模型（引擎按此名走"分案法官"确定性抽取）
    intake_model: str = os.getenv("INTAKE_MODEL", "")
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
    # 沙箱静态命令黑名单（M3.5 审批约束）：子进程模式缺容器网络隔离，
    # 解析执行前先做静态检查，命中以下命令前缀即拒绝（逗号分隔，忽略空白项）。
    code_sandbox_deny_cmds: str = os.getenv(
        "CODE_SANDBOX_DENY_CMDS",
        # 联网/子进程/破坏性命令 + 运行时代码执行与逃逸入口（__import__/compile/
        # exec/eval/importlib/ctypes 等）。subprocess 模式缺容器网络隔离，
        # 正则层拦明显字样，tools._sandbox_ast_check 再补 AST 语义层拦拼接绕过。
        "socket,urllib,requests,httpx,http.client,curl,wget,subprocess,os.system,os.popen,os.remove,os.unlink,os.rmdir,pty,shutil.rmtree,importlib,__import__,compile,exec,eval,ctypes",
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
    # API 限流（P2-4）：按客户端 IP 在窗口内的最大请求数；0=关闭。
    # 大厂 Agent 平台的标配——防脚本滥用/打爆模型额度，登录页与健康检查豁免。
    rate_limit_max: int = int(os.getenv("RATE_LIMIT_MAX", "0"))
    rate_limit_window: int = int(os.getenv("RATE_LIMIT_WINDOW", "60"))
    # 成本核算（P2-6）：每千 token 单价（美元/千 token），用于用量面板换算成本。
    # 默认 0=不核算（用户可评估后填入，如 agnes-flash 类低价模型可填 0.15/0.60）
    llm_cost_per_1k_in: float = float(os.getenv("LLM_COST_PER_1K_IN", "0"))
    llm_cost_per_1k_out: float = float(os.getenv("LLM_COST_PER_1K_OUT", "0"))
    # 字符→token 估算系数（中文约 1字≈1.5 token；英文比例更低）
    llm_chars_per_token: float = float(os.getenv("LLM_CHARS_PER_TOKEN", "1.5"))
    # Agent 工程
    memory_rounds: int = int(os.getenv("MEMORY_ROUNDS", "2"))
    context_char_limit: int = int(os.getenv("CONTEXT_CHAR_LIMIT", "12000"))
    max_concurrency: int = int(os.getenv("MAX_CONCURRENCY", "4"))
    llm_timeout: int = int(os.getenv("LLM_TIMEOUT", "180"))
    # 单次 LLM 调用最大输出 token 数（思维链类模型 reasoning_content 占用 token，
    # 若限制过小会导致 JSON/长分析被截断），0 表示交给平台默认
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "0"))
    # LLM 响应 LRU 缓存（条数）：同一 prompt 命中直接回放，降本提速；0=关闭
    llm_cache_size: int = int(os.getenv("LLM_CACHE_SIZE", "0"))
    # 专家发言流式输出：auto=非 mock 供应商启用（端点不支持自动回退），on=强制，off=关闭
    stream_experts: str = os.getenv("STREAM_EXPERTS", "auto")
    # 同轮专家并行：auto=非 mock 供应商并行（真实 LLM 耗时降为 1/4~1/6），on=强制，off=串行
    parallel_experts: str = os.getenv("PARALLEL_EXPERTS", "auto")
    # WebSocket 脱离宽限期（秒）：断线后辩论保活等待重连，宽限期内 resume
    # 可续看且不重跑，排队中的介入/落槌不丢；0=断开立即取消（旧行为）
    ws_detach_grace: int = int(os.getenv("WS_DETACH_GRACE", "120"))
    # 提示词审计：开启后把每次专家调用的提示词/响应原文落盘到 data/audit/
    audit_prompts: bool = os.getenv("AUDIT_PROMPTS", "false").lower() == "true"
    web_search_enabled: bool = os.getenv("WEB_SEARCH_ENABLED", "true").lower() == "true"
    # 联网搜索实现：searxng（自托管默认，无需 API Key）| bing_html（抓取兜底）| tavily（可选 API）
    search_provider: str = os.getenv("SEARCH_PROVIDER", "searxng")
    search_base_url: str = os.getenv("SEARCH_BASE_URL", "http://127.0.0.1:8888")
    search_timeout: int = int(os.getenv("SEARCH_TIMEOUT", "12"))
    # 扫描件/图片 OCR（RapidOCR onnx 本地，无需联网）；false 时扫描件仅返回文本说明
    ocr_enabled: bool = os.getenv("OCR_ENABLED", "true").lower() == "true"
    # 知识库语义检索嵌入模型：bge-small-zh（本地，免联网）| off（关闭语义检索，退回关键词）
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "bge-small-zh")
    embedding_device: str = os.getenv("EMBEDDING_DEVICE", "cpu")
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
        if self.stream_experts not in ("auto", "on", "off"):
            self.stream_experts = "auto"
        if self.parallel_experts not in ("auto", "on", "off"):
            self.parallel_experts = "auto"
        self.ws_detach_grace = max(0, min(600, int(self.ws_detach_grace)))
        if self.hitl_timeout != 0 and self.hitl_timeout < MIN_HITL_TIMEOUT:
            self.hitl_timeout = DEFAULT_HITL_TIMEOUT
        self.port = max(1, min(65535, int(self.port)))
        self.memory_rounds = max(0, min(MAX_MEMORY_ROUNDS, int(self.memory_rounds)))
        self.max_concurrency = max(1, min(MAX_CONCURRENCY, int(self.max_concurrency)))
        if self.context_char_limit != 0 and self.context_char_limit < MIN_CONTEXT_CHAR_LIMIT:
            self.context_char_limit = DEFAULT_CONTEXT_CHAR_LIMIT
        self.max_request_size = max(MIN_REQUEST_SIZE, int(self.max_request_size))
        self.llm_cache_size = max(0, min(100000, int(self.llm_cache_size)))
        self.rate_limit_max = max(0, min(100000, int(self.rate_limit_max)))
        self.rate_limit_window = max(1, min(86400, int(self.rate_limit_window)))
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
    "max_concurrency",
    "llm_timeout",
    "llm_max_tokens",
    "llm_cache_size",
    "web_search_enabled",
    "intake_model",
    "parallel_experts",
)


def debate_snapshot() -> dict:
    return {k: getattr(settings, k) for k in _SNAPSHOT_FIELDS}
