import subprocess, time

LOG = r"D:\Temp\User\opencode\be.log"
VENV_PY = r"D:\00000\openco\backend\.venv\Scripts\python.exe"
CWD = r"D:\00000\openco\backend"

while True:
    log = open(LOG, "a")
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
            "0.0.0.0",
            "--port",
            "8787",
        ],
        cwd=CWD,
        creationflags=0x00000008,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    rc = p.wait()
    log.write(f"=== supervisor: uvicorn exited rc={rc}, restarting in 3s ===\n")
    log.flush()
    log.close()
    time.sleep(3)
