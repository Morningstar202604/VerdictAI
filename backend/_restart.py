# -*- coding: utf-8 -*-
"""重启后端服务（跨平台）。杀掉占用 8787 端口的进程后重新启动。"""
import os
import socket
import subprocess
import sys
import time

CWD = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(CWD, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = os.path.join(CWD, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable

PORT = 8787
IS_WIN = sys.platform == "win32"
creationflags = 0x08000000 if IS_WIN else 0


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def kill_port(port: int):
    if IS_WIN:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                pid = int(line.split()[-1])
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
                print("killed", pid)
    else:
        # Linux/macOS: 用 lsof 找进程
        try:
            out = subprocess.run(
                ["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=5
            ).stdout
            for pid in out.split():
                if pid.isdigit():
                    subprocess.run(["kill", "-9", pid], capture_output=True)
                    print("killed", pid)
        except Exception:
            pass


if port_in_use(PORT):
    kill_port(PORT)
time.sleep(1.5)

log = open(os.path.join(CWD, "backend.log"), "a", encoding="utf-8")
p = subprocess.Popen(
    [PY, "-u", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(PORT)],
    cwd=CWD,
    creationflags=creationflags,
    stdout=log,
    stderr=subprocess.STDOUT,
)
print("restart issued pid", p.pid)
