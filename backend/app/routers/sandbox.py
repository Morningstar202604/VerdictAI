# -*- coding: utf-8 -*-
"""代码沙箱路由：专家/用户手动在隔离环境中执行 Python 与安装依赖。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


@router.post("/install")
def sandbox_install(payload: dict):
    from app.agents.tools import install_package

    pkg = (payload or {}).get("package", "")
    if not settings.code_sandbox_enabled:
        return JSONResponse(status_code=400, content={"error": "代码沙箱未启用。"})
    result = install_package.invoke({"package": pkg})
    return {"result": result}


@router.post("/run")
def sandbox_run(payload: dict):
    from app.agents.tools import run_code

    code = (payload or {}).get("code", "")
    if not settings.code_sandbox_enabled:
        return JSONResponse(status_code=400, content={"error": "代码沙箱未启用。"})
    result = run_code.invoke({"code": code})
    return {"result": result}