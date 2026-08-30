@echo off
REM 启动 VerdictAI 后端（读取 backend/.env 配置；引擎由 start_all 一并拉起）
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
)
call .venv\Scripts\activate.bat
python tools\start_all.py
python -m uvicorn app.main:app --host 0.0.0.0 --port 8787
