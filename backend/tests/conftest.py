"""pytest 全局环境：必须在任何 app 模块导入之前生效。

app.config.Settings 在导入时读取环境变量，因此 DATA_DIR / LLM_PROVIDER
要在这里先固定：数据写入一次性临时目录（不触碰真实 data/ 下的案件库、
辩论记录与 agent_config），LLM 固定 mock 保证离线可重复。"""

import os
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="vai-test-data-")
os.environ["LLM_PROVIDER"] = "mock"
# 测试环境不受本地 .env 影响：流式/并行/缓存等开关以默认值运行
os.environ["STREAM_EXPERTS"] = "auto"
os.environ["PARALLEL_EXPERTS"] = "auto"
os.environ["LLM_CACHE_SIZE"] = "0"
# 测试默认开放模式（无访问口令）；登录/RBAC 用例自行 monkeypatch 口令
os.environ["ACCESS_PASSWORD"] = ""

# runtime 的设置持久化会改写 backend/.env：测试必须指向临时文件，
# 否则跑一次测试就会把开发者/部署的真实 .env 覆盖成 mock 配置
from app import runtime as _runtime  # noqa: E402

_runtime.ENV_PATH = Path(os.environ["DATA_DIR"]) / ".env"
