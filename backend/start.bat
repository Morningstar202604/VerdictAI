@echo off
REM 启动后端（FastAPI + LangGraph 多智能体探案服务）
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
)
call .venv\Scripts\activate.bat
set LLM_PROVIDER=mock
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
