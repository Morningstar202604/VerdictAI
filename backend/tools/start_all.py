# -*- coding: utf-8 -*-
"""VerdictAI 一键启动/停止（跨平台：Windows / Linux / macOS）。
启动：python tools/start_all.py          # 已在运行的服务自动跳过
停止：python tools/start_all.py stop     # 停止后端与引擎
组件：
  后端  http://localhost:8787  （_serve.py 监管，崩溃自动重启）
  引擎  http://127.0.0.1:9100  （ai_engine/engine_serve.py 监管，崩溃自动重启）
"""
import os
import socket
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

IS_WIN = sys.platform == "win32"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0

COMPONENTS = [
    {"name": "backend", "port": 8787, "path": "/api/health",
     "url": "http://localhost:8787",
     "script": os.path.join(CWD, "_serve.py"),
     "marker": "_serve.py"},
    {"name": "engine", "port": 9100, "path": "/healthz",
     "url": "http://127.0.0.1:9100",
     "script": os.path.join(CWD, "ai_engine", "engine_serve.py"),
     "marker": "engine_serve.py"},
]


def port_in_use(port: int) -> bool:
    """检查端口是否被占用（跨平台，不依赖 netstat）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def find_processes_by_marker(marker: str):
    """查找命令行中包含指定 marker 的进程 PID 列表（跨平台）。"""
    pids = []
    try:
        if IS_WIN:
            out = subprocess.run(
                ["wmic", "process", "where", "name='python.exe'",
                 "get", "processid,commandline"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            for line in out.splitlines():
                if marker.lower() in line.lower():
                    parts = line.strip().split()
                    if parts and parts[-1].isdigit():
                        pids.append(int(parts[-1]))
        else:
            # Linux/macOS: 使用 ps
            out = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True, timeout=10,
            ).stdout
            for line in out.splitlines():
                if marker in line and "grep" not in line:
                    parts = line.split()
                    if len(parts) > 1 and parts[1].isdigit():
                        pids.append(int(parts[1]))
    except Exception:
        pass
    return pids


def kill_pid(pid: int):
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=5)
        else:
            subprocess.run(["kill", "-9", str(pid)],
                           capture_output=True, timeout=5)
    except Exception:
        pass


def alive(port: int, path: str) -> bool:
    """健康探测：目标恒为本机回环地址，仅端口与路径随组件配置。"""
    import http.client

    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            conn.request("GET", path)
            return conn.getresponse().status == 200
        finally:
            conn.close()
    except Exception:
        return False


def start():
    for comp in COMPONENTS:
        if alive(comp["port"], comp["path"]):
            print(f"[{comp['name']}] 已在运行（端口 {comp['port']}），跳过")
            continue
        # 端口被残留进程占用：清掉再启动
        if port_in_use(comp["port"]):
            for pid in find_processes_by_marker(comp["marker"]):
                kill_pid(pid)
            time.sleep(1.5)
        log_path = os.path.join(CWD, f"{comp['name']}.log")
        log = open(log_path, "a", encoding="utf-8")
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
        if all(alive(c["port"], c["path"]) for c in COMPONENTS):
            break
    for comp in COMPONENTS:
        status = "✓ " + comp["url"] if alive(comp["port"], comp["path"]) else "✗ 未就绪，请查看 " + comp["name"] + ".log"
        print(f"[{comp['name']}] {status}")
    print("\n打开 http://localhost:8787 即可使用。")


def stop():
    for comp in COMPONENTS:
        # 杀掉所有匹配的进程（守护进程 + 子进程）
        for pid in find_processes_by_marker(comp["marker"]):
            kill_pid(pid)
        # uvicorn 子进程可能不包含 marker，再按端口清理
        if port_in_use(comp["port"]):
            # Windows 下用 netstat 找 PID
            if IS_WIN:
                try:
                    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=5).stdout
                    for line in out.splitlines():
                        if f":{comp['port']} " in line and "LISTENING" in line:
                            pid = int(line.split()[-1])
                            kill_pid(pid)
                except Exception:
                    pass
        print(f"[{comp['name']}] 已停止")
    print("完成。")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        stop()
    else:
        start()
