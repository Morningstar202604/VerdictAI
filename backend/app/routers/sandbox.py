# -*- coding: utf-8 -*-
"""代码沙箱路由：专家/用户手动在隔离环境中执行 Python 与安装依赖。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.auth import require_admin
from app.config import settings

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


def _guard() -> JSONResponse | None:
    """开放模式（未设访问口令）下拒绝沙箱执行：任意访客可触发任意代码，
    这是默认部署里最危险的组合。设置 ACCESS_PASSWORD 后自动恢复。"""
    if not settings.access_password:
        return JSONResponse(
            status_code=403,
            content={"error": "沙箱已锁定：当前为开放访问模式（未设置访问口令），"
                              "请在 backend/.env 设置 ACCESS_PASSWORD 后重启再启用沙箱。"},
        )
    return None


@router.post("/install")
def sandbox_install(payload: dict, _: dict = Depends(require_admin)):
    if (resp := _guard()) is not None:
        return resp
    if not settings.code_sandbox_enabled:
        return JSONResponse(status_code=400, content={"error": "代码沙箱未启用。"})
    from app.agents.tools import install_package

    pkg = (payload or {}).get("package", "")
    result = install_package.invoke({"package": pkg})
    return {"result": result}


@router.post("/run")
def sandbox_run(payload: dict, _: dict = Depends(require_admin)):
    if (resp := _guard()) is not None:
        return resp
    if not settings.code_sandbox_enabled:
        return JSONResponse(status_code=400, content={"error": "代码沙箱未启用。"})
    from app.agents.tools import run_code

    code = (payload or {}).get("code", "")
    result = run_code.invoke({"code": code})
    return {"result": result}