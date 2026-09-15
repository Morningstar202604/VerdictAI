# ===== VerdictAI 后端镜像 =====
# FastAPI + uvicorn，自托管静态 UI，提供 /api /ws /static /sandbox
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

# 中文字体（matplotlib 图表 / PDF 渲染需要）+ 基础工具
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-noto-cjk \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖，利用 Docker 层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY app ./app
COPY ai_engine ./ai_engine

# 数据目录：案例库 / 辩论记录 / 沙箱产物（运行时常挂载卷覆盖）
# app/config.py 中 data_dir 相对 app/../data -> /app/data
ENV DATA_DIR=/app/data \
    SANDBOX_OUT_DIR=/app/data/sandbox_out

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:8787/api/health || exit 1

# ── 安全说明（默认仍以 root 运行，避免挂载卷属主不匹配导致写入失败）──────────
# 容器内若 CODE_SANDBOX_BACKEND=auto 且无 docker.sock，专家代码会以本容器用户
# 执行；为降低专家任意代码对宿主的影响，推荐：
#   1) 把沙箱切到 docker 后端：挂载 /var/run/docker.sock 并设
#      CODE_SANDBOX_BACKEND=docker（一次性容器断网 + 512MB 隔离）；或
#   2) CODE_SANDBOX_ENABLED=false 完全关闭沙箱；
#   3) 如需非 root 运行：创建 uid 与挂载卷属主一致的普通用户并在此处加 USER，
#      并确保 ./backend/data 对该用户可写。
# 生产用单 worker；辩论会话为进程内存态，多 worker 需共享存储
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]