import subprocess, time


def find_pid(port=8787):
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if f":{port}" in line and "LISTEN" in line:
            return int(line.split()[-1])
    return None


pid = find_pid()
if pid:
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False)
    print("killed", pid)
time.sleep(1.5)

log = open(r"D:\Temp\User\opencode\be.log", "w")
p = subprocess.Popen(
    [
        r"D:\00000\openco\backend\.venv\Scripts\python.exe",
        "-u",
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8787",
    ],
    cwd=r"D:\00000\openco\backend",
    creationflags=0x00000008,
    stdout=log,
    stderr=subprocess.STDOUT,
)
print("restart issued pid", p.pid)
