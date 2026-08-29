@echo off
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
)
call .venv\Scripts\activate.bat
uvicorn app.main:app --host 0.0.0.0 --port 8787 > D:\Temp\User\opencode\be.log 2>&1
