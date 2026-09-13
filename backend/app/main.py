from __future__ import annotations

import asyncio
import logging
import os
import time as _time

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import auth
from app.config import settings
from app.data.store import load_case, validate_id
from app.graph.runner import run_debate
from app.routers import admin, agents, cases, debates, intent, knowledge, presets, qa, reports, sandbox
from app.routers import settings as settings_router
from app.routers import users as users_router
from app.ws.manager import manager

log = logging.getLogger("verdictai")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# 文件日志按 1MB×5 份轮转，防止单文件无限增长；只读盘等场景退回仅控制台
try:
    from logging.handlers import RotatingFileHandler

    _log_dir = os.path.join(os.path.abspath(settings.data_dir), "logs")
    os.makedirs(_log_dir, exist_ok=True)
    _file_handler = RotatingFileHandler(
        os.path.join(_log_dir, "verdictai.log"),
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    _file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    log.addHandler(_file_handler)
except Exception:
    pass

app = FastAPI(title="VerdictAI", version="0.9.0")
_START_TIME = _time.time()

if not settings.access_password:
    log.warning(
        "ACCESS_PASSWORD 未设置：当前为完全开放访问，代码沙箱已锁定。"
        "局域网/公网部署请在 backend/.env 设置访问口令后重启。"
    )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常捕获：记录日志并返回友好错误，避免 500 空响应。"""
    log.exception("未处理异常: %s %s -> %s", request.method, request.url.path, exc)
    return JSONResponse(
        {"error": f"服务器内部错误: {type(exc).__name__}", "detail": str(exc)[:200]},
        status_code=500,
    )


# ---------------- 中间件（注册顺序决定执行顺序：限流 → CORS → 访问口令） ----------------
app.middleware("http")(auth.rate_limit_middleware)
app.middleware("http")(auth.access_gate)

_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_size_limit(request, call_next):
    """限制请求体大小，防止超大 base64 PDF 撑爆内存。"""
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > settings.max_request_size:
        return JSONResponse(
            {"error": f"请求体过大（上限 {settings.max_request_size // 1024 // 1024}MB），请压缩或拆分文件"},
            status_code=413,
        )
    return await call_next(request)


# ---------------- 登录（访问口令门） ----------------
app.get("/login")(auth.login_page)
app.post("/login")(auth.login_submit)


# ---------------- REST 路由 ----------------
for r in (cases, debates, reports, settings_router, agents, sandbox, presets, knowledge, qa, intent, admin):
    app.include_router(r.router)
app.include_router(users_router.router)
app.include_router(users_router.admin_router)


# ---------------- 静态资源 ----------------
# 静态资源：只暴露案件图表资产目录（浏览器渲染卷宗图表必需）。
# data/ 下的辩论记录、agent_config、knowledge_base、presets 等私有
# 存储不再有任何 URL 可直达；图表 URL 前缀 /static/data/cases/assets/
# 与历史辩论记录保持兼容。
data_dir = os.path.abspath(settings.data_dir)
os.makedirs(data_dir, exist_ok=True)
case_assets_dir = os.path.join(data_dir, "cases", "assets")
os.makedirs(case_assets_dir, exist_ok=True)
app.mount("/static/data/cases/assets", StaticFiles(directory=case_assets_dir), name="data")

# 品牌与界面静态资源（logo 等，长缓存）
assets_dir = os.path.join(os.path.dirname(__file__), "static", "assets")
os.makedirs(assets_dir, exist_ok=True)


class _CachedStaticFiles(StaticFiles):
    """静态资源带 Cache-Control 头（短缓存 15 分钟）：外链 JS/CSS 升级后
    浏览器不至于长时间停留在旧版本；HTML 本身仍走 no-cache。"""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "public, max-age=900"  # 15分钟
        return resp


app.mount("/static/assets", _CachedStaticFiles(directory=assets_dir), name="assets")

# 沙箱产物（图表等）对外提供（不缓存）
sandbox_out_dir = os.path.abspath(settings.sandbox_out_dir)
os.makedirs(sandbox_out_dir, exist_ok=True)
app.mount("/sandbox", StaticFiles(directory=sandbox_out_dir), name="sandbox")

INDEX_HTML = os.path.join(os.path.dirname(__file__), "static", "index.html")
FLOW_HTML = os.path.join(os.path.dirname(__file__), "static", "flow.html")
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "static", "assets")
_asset_ver_cache: tuple[float, str] = (0.0, "")


def _asset_ver() -> str:
    """静态资源版本号：取 assets 目录最新修改时间。升级后 URL 自动变化，
    浏览器短缓存（15 分钟）立即失效，用户不会停留在旧版界面。"""
    global _asset_ver_cache
    latest = 0.0
    try:
        for fn in ("app-core.js", "app-ui.js", "app.css"):
            latest = max(latest, os.path.getmtime(os.path.join(ASSETS_DIR, fn)))
    except OSError:
        pass
    if latest <= _asset_ver_cache[0]:
        return _asset_ver_cache[1]
    ver = "v" + str(int(latest))
    _asset_ver_cache = (latest, ver)
    return ver


@app.get("/")
def index():
    # no-cache：保证用户总是拿到最新页面；资源 URL 带版本参数，升级即击穿缓存
    try:
        with open(INDEX_HTML, encoding="utf-8") as fh:
            html = fh.read().replace("__VER__", _asset_ver())
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
    except OSError:
        return FileResponse(
            INDEX_HTML,
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-cache"},
        )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    # 避免浏览器默认请求 /favicon.ico 产生 404 噪音
    path = os.path.join(os.path.dirname(__file__), "static", "assets", "logo.svg")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/svg+xml")
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/flow.html")
@app.get("/static/flow.html")
def flow():
    if not os.path.exists(FLOW_HTML):
        return JSONResponse({"error": "流程图不存在"}, status_code=404)
    return FileResponse(FLOW_HTML, media_type="text/html; charset=utf-8")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "version": app.version,
        "provider": settings.llm_provider,
        "mock": settings.llm_provider == "mock",
        "max_rounds": settings.max_rounds,
        "max_concurrency": settings.max_concurrency,
        "active_sessions": len(manager.active),
        "auth_enabled": bool(settings.access_password),
        "uptime": int(_time.time() - _START_TIME),
    }


# ---------------- WebSocket 庭审会话 ----------------
@app.websocket("/ws/{session_id}")
async def ws_endpoint(websocket: WebSocket, session_id: str):
    # 访问口令启用时，WebSocket 同样校验登录 cookie（accept 前拒绝，避免产生半开连接）
    ident = None
    if settings.access_password:
        ident = auth.session_identity(websocket.cookies.get(auth._AUTH_COOKIE))
        if ident is None:
            await websocket.close(code=4401)
            return
    # viewer 只读：可观看/续看，但不能开庭、停止、落槌、介入
    can_control = not settings.access_password or ident.get("role") == auth.ROLE_ADMIN
    # session_id 会作为辩论记录文件名落盘，与 REST 端点同等校验，杜绝路径穿越
    if not validate_id(session_id):
        await websocket.close(code=4400)
        return
    # 同一会话重复连接：先关闭旧连接，避免孤儿连接占用资源
    if session_id in manager.active:
        try:
            await manager.active[session_id].close(code=4400)
        except Exception:
            pass
        manager.disconnect(session_id)
    await manager.connect(session_id, websocket)

    async def receiver():
        while True:
            try:
                msg = await websocket.receive_json()
            except Exception:
                break
            msg_type = msg.get("type")
            if msg_type in ("start", "stop", "human") and not can_control:
                await manager.send(
                    session_id,
                    {"kind": "error", "message": "只读账号无权控制庭审，请联系管理员。"},
                    buffer=False,
                )
                continue
            if msg_type == "start":
                # 新庭审：清空事件缓冲与遗留介入/落槌队列，取消同会话仍在运行的任务
                manager.clear_buffer(session_id)
                manager.reset_session_queues(session_id)
                old = manager.tasks.get(session_id)
                if old is not None and not old.done():
                    old.cancel()
                    try:
                        await old
                    except Exception:
                        pass
                case_id = msg.get("case_id", "case_001")
                case = load_case(case_id)
                if case is None:
                    await manager.send(session_id, {"kind": "error", "message": f"案件 {case_id} 不存在"})
                    continue
                agents = msg.get("agents") or None
                overrides = {
                    k: msg[k]
                    for k in (
                        "intent",
                        "reasoning_intensity",
                        "global_guidance",
                        "judge_mode",
                    )
                    if msg.get(k)
                }
                manager.tasks[session_id] = asyncio.create_task(
                    run_debate(case, session_id, agents, overrides or None)
                )
            elif msg_type == "resume":
                # 断线重连续看：补发历史事件快照，绝不取消进行中的辩论。
                # manager.active 已被新连接接管，直播事件自动续上。
                events = manager.buffer(session_id)
                if events:
                    await manager.send(
                        session_id, {"kind": "batch", "events": events}, buffer=False
                    )
            elif msg_type == "stop":
                old = manager.tasks.get(session_id)
                if old is not None and not old.done():
                    old.cancel()
                    try:
                        await old
                    except Exception:
                        pass
                    await manager.send(session_id, {"kind": "stopped", "message": "辩论已被用户停止"})
                manager.tasks.pop(session_id, None)
            elif msg_type == "human":
                await manager.push_human(
                    session_id, msg.get("text", ""), msg.get("subtype", "intervene")
                )

    task = asyncio.create_task(receiver())
    try:
        await task
    finally:
        # 守护式清理：重连后本连接已被新连接接管（taken_over）时保留任务；
        # 正常断开（无人接管）进入脱离宽限期——宽限期内重连可 resume 续看
        # 且辩论继续（排队中的介入/落槌也不丢），超时无人认领才取消并清理，
        # 兼顾断线容错与不白烧 API 额度（WS_DETACH_GRACE=0 恢复旧行为）
        taken_over = manager.active.get(session_id) is not websocket
        manager.disconnect(session_id, websocket)
        if not taken_over:
            old = manager.tasks.get(session_id)
            if old is not None and not old.done():
                grace = int(settings.ws_detach_grace or 0)
                if grace > 0:

                    async def _reap_detached(sid: str = session_id, task=old, g: int = grace):
                        await asyncio.sleep(g)
                        if (
                            manager.tasks.get(sid) is task
                            and not task.done()
                            and manager.active.get(sid) is None
                        ):
                            task.cancel()
                            try:
                                await task
                            except Exception:
                                pass
                            manager.cleanup_session(sid, task)

                    asyncio.create_task(_reap_detached())
                else:
                    old.cancel()
                    manager.cleanup_session(session_id, old)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)