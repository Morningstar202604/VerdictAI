# -*- coding: utf-8 -*-
"""启动后端守护进程（跨平台）。等价于直接运行 _serve.py，但保留此入口兼容旧脚本。"""
import os
import subprocess
import sys

CWD = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(CWD, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = os.path.join(CWD, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable

creationflags = 0x08000000 if sys.platform == "win32" else 0
log = open(os.path.join(CWD, "backend.log"), "a", encoding="utf-8")
subprocess.Popen(
    [PY, os.path.join(CWD, "_serve.py")],
    cwd=CWD,
    creationflags=creationflags,
    stdout=log,
    stderr=subprocess.STDOUT,
)
print("supervisor launched")
