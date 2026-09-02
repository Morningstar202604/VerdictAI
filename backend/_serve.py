# -*- coding: utf-8 -*-
"""VerdictAI 后端守护进程：崩溃自动重启。
跨平台（Windows / Linux / macOS）。
用法：python _serve.py
"""
import os
import subprocess
import sys
import time

CWD = os.path.dirname(os.path.abspath(__file__))  # backend/
# 优先使用项目虚拟环境，回退到当前解释器
VENV_PY = os.path.join(CWD, ".venv", "Scripts", "python.exe")
if not os.path.exists(VENV_PY):
    VENV_PY = os.path.join(CWD, ".venv", "bin", "python")
if not os.path.exists(VENV_PY):
    VENV_PY = sys.executable

LOG = os.path.join(CWD, "backend.log")
PORT = os.environ.get("PORT", "8787")
HOST = os.environ.get("HOST", "0.0.0.0")

# Windows 下 CREATE_NO_WINDOW 避免弹出控制台；其他平台忽略该参数
creationflags = 0
if sys.platform == "win32":
    creationflags = 0x08000000  # CREATE_NO_WINDOW

while True:
    log = open(LOG, "a", encoding="utf-8")
    log.write("\n=== supervisor: starting uvicorn ===\n")
    log.flush()
    p = subprocess.Popen(
        [
            VENV_PY,
            "-u",
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            HOST,
            "--port",
            PORT,
        ],
        cwd=CWD,
        creationflags=creationflags,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    rc = p.wait()
    log.write(f"=== supervisor: uvicorn exited rc={rc}, restarting in 3s ===\n")
    log.flush()
    log.close()
    time.sleep(3)
