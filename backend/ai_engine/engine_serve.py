# -*- coding: utf-8 -*-
"""本地审理引擎守护进程：崩溃自动拉起。跨平台（Windows / Linux / macOS）。
用法：python ai_engine/engine_serve.py
"""
import os
import subprocess
import sys
import time

CWD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
# 优先使用项目虚拟环境，回退到当前解释器
PY = os.path.join(CWD, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = os.path.join(CWD, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable

LOG = os.path.join(CWD, "engine.log")

# Windows 下无控制台窗口；其他平台忽略
creationflags = 0
if sys.platform == "win32":
    creationflags = 0x08000000  # CREATE_NO_WINDOW

while True:
    log = open(LOG, "a", encoding="utf-8")
    log.write("\n=== engine supervisor: starting uvicorn ===\n")
    log.flush()
    p = subprocess.Popen(
        [
            PY, "-u", "-m", "uvicorn",
            "ai_engine.server:app",
            "--host", "127.0.0.1",
            "--port", "9100",
            "--log-level", "warning",
        ],
        cwd=CWD,
        creationflags=creationflags,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    rc = p.wait()
    log.write(f"=== engine supervisor: engine exited rc={rc}, restarting in 3s ===\n")
    log.flush()
    log.close()
    time.sleep(3)
