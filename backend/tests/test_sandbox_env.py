"""代码沙箱环境隔离测试。

专家生成的代码是任意代码：沙箱/pip 子进程若继承完整环境，LLM 密钥与
访问口令可被直接读出外传。本文件钉死「敏感前缀不进子进程、工具自己
注入的变量（SANDBOX_OUT 等）正常可见」两条边界。"""

import sys

from app.agents.tools import run_code
from app.config import settings


def setup_function():
    settings.code_sandbox_python = sys.executable
    settings.code_sandbox_enabled = True


def test_sandbox_strips_sensitive_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-SUPER-SECRET-123")
    monkeypatch.setenv("LLM_BASE_URL", "https://secret.example/v1")
    monkeypatch.setenv("ACCESS_PASSWORD", "p4ssw0rd-SUPER-SECRET")
    out = run_code.invoke(
        {
            "code": (
                "import os\n"
                "print('KEY_LEAK' if 'LLM_API_KEY' in os.environ else 'KEY_CLEAN')\n"
                "print('PWD_LEAK' if 'ACCESS_PASSWORD' in os.environ else 'PWD_CLEAN')\n"
            )
        }
    )
    assert "KEY_CLEAN" in out and "PWD_CLEAN" in out, out
    assert "sk-SUPER-SECRET-123" not in out
    assert "p4ssw0rd-SUPER-SECRET" not in out


def test_sandbox_keeps_tool_injected_env(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-SUPER-SECRET-123")
    out = run_code.invoke(
        {"code": "import os; print('SANDBOX_OUT=' + str(bool(os.environ.get('SANDBOX_OUT'))))"}
    )
    assert "SANDBOX_OUT=True" in out, out
    assert "sk-SUPER-SECRET-123" not in out
