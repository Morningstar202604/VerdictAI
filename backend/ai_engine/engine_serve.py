# -*- coding: utf-8 -*-
"""本地审理引擎守护进程：崩溃自动拉起，全程无控制台窗口。

用法：python tools/start_all.py（推荐，会同时拉起后端与本引擎）
      或单独：python ai_engine/engine_serve.py
"""
import os
import subprocess
import sys
import time

CWD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
PY = os.path.join(CWD, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable
LOG = os.path.join(CWD, "engine.log")

# CREATE_NO_WINDOW：引擎日志写文件，桌面不会闪任何命令行窗口
CREATE_NO_WINDOW = 0x08000000

while True:
    log = open(LOG, "a")
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
        creationflags=CREATE_NO_WINDOW,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    rc = p.wait()
    log.write(f"=== engine supervisor: engine exited rc={rc}, restarting in 3s ===\n")
    log.flush()
    time.sleep(3)
