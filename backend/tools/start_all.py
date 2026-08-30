# -*- coding: utf-8 -*-
"""VerdictAI 一键启动/停止（Windows，全程无命令行窗口）。

启动：python tools/start_all.py          # 已在运行的服务自动跳过
停止：python tools/start_all.py stop     # 停止后端与引擎

组件：
  后端  http://localhost:8787  （_serve.py 监管，崩溃自动重启）
  引擎  http://127.0.0.1:9100  （ai_engine/engine_serve.py 监管，崩溃自动重启）
"""
import os
import subprocess
import sys
import time

import urllib.request

CWD = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
PY = os.path.join(CWD, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable

CREATE_NO_WINDOW = 0x08000000
COMPONENTS = [
    {"name": "backend", "port": 8787, "url": "http://localhost:8787/api/health",
     "script": os.path.join(CWD, "_serve.py")},
    {"name": "engine", "port": 9100, "url": "http://127.0.0.1:9100/healthz",
     "script": os.path.join(CWD, "ai_engine", "engine_serve.py")},
]


def port_listener(port: int):
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if f":{port} " in line and "LISTENING" in line:
            return int(line.split()[-1])
    return None


def kill_pid(pid: int):
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def alive(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=3)
        return True
    except Exception:
        return False


def start():
    for comp in COMPONENTS:
        if alive(comp["url"]):
            print(f"[{comp['name']}] 已在运行（端口 {comp['port']}），跳过")
            continue
        pid = port_listener(comp["port"])
        if pid:
            kill_pid(pid)  # 端口被残留进程占用：清掉再启动
            time.sleep(1.5)
        log_path = os.path.join(CWD, f"{comp['name']}.log")
        log = open(log_path, "a")
        subprocess.Popen(
            [PY, "-u", comp["script"]],
            cwd=CWD,
            creationflags=CREATE_NO_WINDOW,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        print(f"[{comp['name']}] 守护进程已启动（日志：{log_path}）")
    print("等待服务就绪…")
    for _ in range(20):
        time.sleep(1.5)
        if all(alive(c["url"]) for c in COMPONENTS):
            break
    for comp in COMPONENTS:
        print(f"[{comp['name']}] {'✓ ' + comp['url'] if alive(comp['url']) else '✗ 未就绪，请查看 ' + comp['name'] + '.log'}")
    print("\n打开 http://localhost:8787 即可使用。")


def stop():
    for comp in COMPONENTS:
        # 先杀监听进程；守护进程检测到子进程退出会重启，因此连守护进程一起结束
        pid = port_listener(comp["port"])
        if pid:
            kill_pid(pid)
        out = subprocess.run(
            ["wmic", "process", "where", f"name='python.exe'", "get", "processid,commandline"],
            capture_output=True, text=True,
        ).stdout
        for line in out.splitlines():
            low = line.lower()
            marker = "_serve.py" if comp["name"] == "backend" else "engine_serve.py"
            if marker in low and line.strip().split()[-1].isdigit():
                kill_pid(int(line.strip().split()[-1]))
        print(f"[{comp['name']}] 已停止")
    print("完成。")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        stop()
    else:
        start()
