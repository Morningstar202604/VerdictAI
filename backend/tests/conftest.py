"""pytest 全局环境：必须在任何 app 模块导入之前生效。

app.config.Settings 在导入时读取环境变量，因此 DATA_DIR / LLM_PROVIDER
要在这里先固定：数据写入一次性临时目录（不触碰真实 data/ 下的案件库、
辩论记录与 agent_config），LLM 固定 mock 保证离线可重复。"""

import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="vai-test-data-")
os.environ["LLM_PROVIDER"] = "mock"
