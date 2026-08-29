import subprocess

log = open(r"D:\Temp\User\opencode\be.log", "w")
subprocess.Popen(
    [
        r"D:\00000\openco\backend\.venv\Scripts\python.exe",
        r"D:\00000\openco\backend\_serve.py",
    ],
    cwd=r"D:\00000\openco\backend",
    creationflags=0x00000008,
    stdout=log,
    stderr=subprocess.STDOUT,
)
print("supervisor launched")
