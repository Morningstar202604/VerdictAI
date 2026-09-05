from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time as _time
import uuid

from fastapi import FastAPI, Request, WebSocket, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings, MAX_PDF_PAGES, MAX_PDF_CHARS
from app.data import generate_case
from app.data.store import atomic_write_json, list_cases, load_case, validate_id
from app.agents.roles import role_list
from app.agents import agent_config
from app.graph.runner import run_debate
from app.runtime import current as current_settings, update as update_settings
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

app = FastAPI(title="VerdictAI", version="0.6.1")
_START_TIME = _time.time()

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常捕获：记录日志并返回友好错误，避免 500 空响应。"""
    log.exception("未处理异常: %s %s -> %s", request.method, request.url.path, exc)
    return JSONResponse(
        {"error": f"服务器内部错误: {type(exc).__name__}", "detail": str(exc)[:200]},
        status_code=500,
    )

# ---------------- 访问认证（ACCESS_PASSWORD 为空时完全开放） ----------------
_AUTH_COOKIE = "vai_auth"
# 会话令牌：{过期时间戳}.{HMAC 签名}。密钥每次进程启动随机生成——
# 重启后旧会话失效需重新登录；签名使令牌无法伪造，过期时间无法延长；
# 全部比较走 compare_digest，避免时序侧信道。
_SESSION_SECRET_BYTES = secrets.token_bytes(32)
SESSION_TTL_SECONDS = 7 * 24 * 3600
_LOGIN_MAX_FAILS = 5
_LOGIN_LOCK_SECONDS = 900
_login_fails: dict = {}


def _issue_session_token(expiry: float = None) -> str:
    # 整数时间戳：令牌里 "." 是分隔符，过期值不能带小数点
    if expiry is None:
        expiry = int(_time.time()) + SESSION_TTL_SECONDS
    sig = hmac.new(_SESSION_SECRET_BYTES, msg=str(int(expiry)).encode(), digestmod=hashlib.sha256)
    return f"{int(expiry)}.{sig.hexdigest()}"


def _verify_session(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expiry_str, _, sig = token.partition(".")
    try:
        expiry = float(expiry_str)
    except ValueError:
        return False
    expected = hmac.new(
        _SESSION_SECRET_BYTES, msg=expiry_str.encode(), digestmod=hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    return expiry > _time.time()


def _login_locked_until(ip: str) -> float:
    entry = _login_fails.get(ip)
    if entry and entry["locked_until"] > _time.time():
        return entry["locked_until"]
    return 0.0


def _record_login_fail(ip: str) -> None:
    entry = _login_fails.setdefault(ip, {"count": 0, "locked_until": 0.0})
    entry["count"] += 1
    if entry["count"] >= _LOGIN_MAX_FAILS:
        entry["locked_until"] = _time.time() + _LOGIN_LOCK_SECONDS
        entry["count"] = 0
    # 防止字典被海量伪造 IP 撑爆
    if len(_login_fails) > 10000:
        now = _time.time()
        for k in [k for k, v in _login_fails.items() if v["locked_until"] < now]:
            _login_fails.pop(k, None)


def _record_login_success(ip: str) -> None:
    _login_fails.pop(ip, None)


_EXEMPT_PREFIXES = ("/login", "/static/assets/", "/api/health", "/favicon")


@app.middleware("http")
async def access_gate(request, call_next):
    pwd = settings.access_password
    path = request.url.path
    if pwd and not any(path.startswith(pfx) or path == pfx for pfx in _EXEMPT_PREFIXES):
        if not _verify_session(request.cookies.get(_AUTH_COOKIE)):
            from fastapi.responses import RedirectResponse

            if path.startswith("/api/"):
                return JSONResponse({"error": "未登录或会话已过期"}, status_code=401)
            return RedirectResponse("/login", status_code=302)
    return await call_next(request)


_LOGIN_PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>登录 · VerdictAI</title>
<link rel="icon" type="image/svg+xml" href="/static/assets/logo.svg">
<style>
 body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0e131a;
   font-family:"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif;color:#e2e9f2;}
 .card{width:min(360px,92vw);background:#1a2330;border:1px solid #26313f;border-radius:16px;
   padding:34px 30px;box-shadow:0 20px 60px rgba(0,0,0,.45);text-align:center;}
 img{width:64px;height:64px;border-radius:14px;margin-bottom:14px;}
 h1{font-family:"Noto Serif SC","Songti SC",serif;font-size:19px;margin:0 0 6px;letter-spacing:1px;}
 p{font-size:12px;color:#94a1b1;margin:0 0 22px;}
 input{width:100%;box-sizing:border-box;padding:11px 13px;border-radius:9px;border:1px solid #36465c;
   background:#131a23;color:#e2e9f2;font-size:14px;outline:none;margin-bottom:12px;}
 input:focus{border-color:#4a78b0;}
 button{width:100%;padding:11px;border:0;border-radius:9px;background:#2f5d94;color:#fff;
   font-size:14px;font-weight:600;cursor:pointer;font-family:inherit;}
 button:hover{background:#3a6cab;}
 .err{color:#e08073;font-size:12px;min-height:16px;margin:8px 0 0;}
</style></head><body>
 <div class="card">
  <img src="/static/assets/logo.svg" alt="VerdictAI">
  <h1>VerdictAI · 智能探案合议庭</h1>
  <p>本系统受访问口令保护，请输入后继续</p>
  <form method="post" action="/login">
    <input type="password" name="password" placeholder="访问口令" autofocus>
    <button type="submit">进 入</button>
  </form>
  <div class="err">{error}</div>
 </div>
</body></html>"""


@app.get("/login")
def login_page():
    if not settings.access_password:
        from fastapi.responses import RedirectResponse

        return RedirectResponse("/", status_code=302)
    from fastapi.responses import HTMLResponse

    return HTMLResponse(_LOGIN_PAGE.replace("{error}", ""))


@app.post("/login")
def login_submit(request: Request, password: str = Form("")):
    from fastapi.responses import HTMLResponse, RedirectResponse

    if not settings.access_password:
        return RedirectResponse("/", status_code=302)
    ip = request.client.host if request.client else "unknown"
    locked_until = _login_locked_until(ip)
    if locked_until:
        remaining = int(locked_until - _time.time())
        return HTMLResponse(
            _LOGIN_PAGE.replace("{error}", f"失败次数过多，请 {remaining} 秒后重试"),
            status_code=429,
        )
    # 常数时间比较，避免时序侧信道逐位猜口令
    ok = bool(password) and hmac.compare_digest(
        password.encode(), settings.access_password.encode()
    )
    if ok:
        _record_login_success(ip)
        resp = RedirectResponse("/", status_code=302)
        # HTTPS 环境下设置 Secure 标志；HTTP 开发环境不设置以保证 cookie 可用
        is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        resp.set_cookie(
            _AUTH_COOKIE,
            _issue_session_token(),
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="lax",
            secure=is_https,
        )
        return resp
    _record_login_fail(ip)
    return HTMLResponse(_LOGIN_PAGE.replace("{error}", "口令错误，请重试"), status_code=401)


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
    """静态资源带 Cache-Control 头，减少重复下载。"""
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "public, max-age=86400"  # 24小时
        return resp

app.mount("/static/assets", _CachedStaticFiles(directory=assets_dir), name="assets")

# 沙箱产物（图表等）对外提供（不缓存）
sandbox_out_dir = os.path.abspath(settings.sandbox_out_dir)
os.makedirs(sandbox_out_dir, exist_ok=True)
app.mount("/sandbox", StaticFiles(directory=sandbox_out_dir), name="sandbox")

INDEX_HTML = os.path.join(os.path.dirname(__file__), "static", "index.html")
FLOW_HTML = os.path.join(os.path.dirname(__file__), "static", "flow.html")


@app.get("/")
def index():
    # no-cache：保证用户总是拿到最新界面（静态资源仍走缓存）
    return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-cache"})


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


@app.get("/api/roles")
def roles():
    return {"roles": role_list()}


@app.get("/api/cases")
def cases():
    return {"cases": list_cases()}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    if not validate_id(case_id):
        return JSONResponse({"error": "无效的案件 ID"}, status_code=400)
    c = load_case(case_id)
    if c is None:
        return JSONResponse({"error": "案件不存在"}, status_code=404)
    return c


_debates_index: dict = {}


def _debate_summary(path: str) -> dict | None:
    """解析单份辩论记录的列表摘要；损坏文件返回 None（重试到下次修改为止）。"""
    try:
        with open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
    except Exception:
        return None
    return {
        "session_id": rec.get("session_id"),
        "case_title": rec.get("case_title"),
        "started_at": rec.get("started_at"),
        "model": rec.get("model"),
        "rounds": rec.get("rounds"),
        "truth": (rec.get("final_verdict") or {}).get("truth_hypothesis", ""),
        "usage": rec.get("usage") or {},
    }


@app.get("/api/debates")
def list_debates(limit: int = 50):
    """列出已落盘的辩论记录，供复盘。默认最多返回最近 50 条（按开始时间排序）。
    摘要按文件 (mtime, size) 缓存：记录上千份时列表请求不再全量解析。"""
    d = os.path.join(settings.data_dir, "debates")
    if not os.path.isdir(d):
        return []
    limit = max(1, min(200, int(limit)))
    entries = []
    for fn in os.listdir(d):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(d, fn)
        try:
            st = os.stat(p)
        except OSError:
            continue
        key = (st.st_mtime_ns, st.st_size)
        cached = _debates_index.get(fn)
        if cached is not None and cached[0] == key:
            item = cached[1]
        else:
            item = _debate_summary(p)
            _debates_index[fn] = (key, item)
        if item is not None:
            entries.append(item)
    # 清理已删除记录的缓存
    live = {fn for fn in os.listdir(d) if fn.endswith(".json")}
    for fn in [k for k in _debates_index if k not in live]:
        _debates_index.pop(fn, None)
    entries.sort(key=lambda e: e.get("started_at") or "", reverse=True)
    return entries[:limit]


@app.get("/api/debates/{session_id}")
def get_debate(session_id: str):
    if not validate_id(session_id):
        return JSONResponse({"error": "无效的会话 ID"}, status_code=400)
    p = os.path.join(settings.data_dir, "debates", f"{session_id}.json")
    if not os.path.exists(p):
        return JSONResponse({"error": "未找到该辩论记录"}, status_code=404)
    with open(p, encoding="utf-8") as fh:
        return JSONResponse(json.load(fh))


@app.post("/api/cases/generate")
async def regenerate():
    """生成一个示例案件并加入案例库（用唯一 ID，不再硬编码 case_001）。"""
    from app.intake.processor import preprocess

    path = generate_case.generate()
    # 从 generate() 返回的路径读取案件，而非硬编码 case_001
    try:
        with open(path, encoding="utf-8") as f:
            case = json.load(f)
    except Exception as ex:
        return JSONResponse({"error": f"示例案件生成失败：{str(ex)[:200]}"}, status_code=500)
    if not case:
        return JSONResponse({"error": "示例案件为空"}, status_code=500)
    # 给示例案件一个新 ID，避免覆盖 case_001
    new_id = "case_" + uuid.uuid4().hex[:8]
    case["id"] = new_id
    # 标题去重：以原题去掉"(副本…)"后缀为基底，统计已有同源副本数，递增编号。
    # generate() 已把模板写进 cases 目录，统计时必须跳过模板自身，否则
    # 新生成的示例案件永远被误判为"已有副本"而带上 (副本) 后缀。
    base = re.sub(r"\s*\(副本\d*\)\s*$", "", case.get("title", "示例案件"))
    source_fn = os.path.basename(path)
    existing = 0
    try:
        for fn in os.listdir(os.path.join(data_dir, "cases")):
            if not fn.endswith(".json") or fn == source_fn:
                continue
            try:
                with open(os.path.join(data_dir, "cases", fn), encoding="utf-8") as f:
                    if (json.load(f).get("title") or "").startswith(base):
                        existing += 1
            except Exception:
                continue
    except Exception:
        pass
    if existing == 1:
        case["title"] = base + " (副本)"
    elif existing >= 2:
        case["title"] = base + f" (副本{existing})"
    try:
        case["brief"] = await preprocess(case)
    except Exception:
        pass
    new_path = os.path.join(os.path.dirname(path), f"{new_id}.json")
    atomic_write_json(new_path, case)
    return {"path": new_path, "case": case}


@app.get("/api/settings")
def get_settings():
    return current_settings()


@app.post("/api/settings")
def post_settings(payload: dict):
    return update_settings(payload)


@app.post("/api/settings/test")
def test_settings(payload: dict):
    """测试 LLM 连接是否可用，返回连通状态和耗时。"""
    import time as _time
    provider = (payload or {}).get("llm_provider", "openai_compatible").strip().lower()
    api_key = (payload or {}).get("llm_api_key", "").strip()
    base_url = (payload or {}).get("llm_base_url", "").strip() or None
    model = (payload or {}).get("llm_model", "").strip() or "gpt-4o-mini"
    result: dict = {"ok": False, "model": model, "provider": provider}
    if not api_key:
        result["error"] = "API Key 为空"
        return result
    if provider == "mock":
        result["ok"] = True
        result["message"] = "Mock 模式：离线模拟，无需联网"
        return result
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        t0 = _time.time()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "回复：ok"}],
            max_tokens=4,
            timeout=15.0,
        )
        elapsed = round(_time.time() - t0, 2)
        used_model = resp.model or model
        text = (resp.choices[0].message.content or "").strip()
        result.update({"ok": True, "model": used_model, "elapsed_s": elapsed, "message": text})
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result


@app.get("/api/agent-config")
def get_agent_config():
    return {"agents": agent_config.effective_list()}


@app.post("/api/agent-config")
def post_agent_config(payload: dict):
    data = payload.get("agents", payload) if isinstance(payload, dict) else payload
    # 兼容三种提交形状：{agents:{key:cfg}}（设置页保存）、
    # {agents:[{key:cfg},...]}（导出/导入文件）、{key:cfg}（直接对象）
    if isinstance(data, list):
        data = {it.get("key"): it for it in data if isinstance(it, dict) and it.get("key")}
    return {"agents": agent_config.save(data)}


@app.post("/api/sandbox/install")
def sandbox_install(payload: dict):
    from app.agents.tools import install_package

    pkg = (payload or {}).get("package", "")
    if not settings.code_sandbox_enabled:
        return JSONResponse(status_code=400, content={"error": "代码沙箱未启用。"})
    result = install_package.invoke({"package": pkg})
    return {"result": result}


@app.post("/api/sandbox/run")
def sandbox_run(payload: dict):
    from app.agents.tools import run_code

    code = (payload or {}).get("code", "")
    if not settings.code_sandbox_enabled:
        return JSONResponse(status_code=400, content={"error": "代码沙箱未启用。"})
    result = run_code.invoke({"code": code})
    return {"result": result}


def _extract_pdf_text(
    b64_content: str, max_pages: int = MAX_PDF_PAGES, max_chars: int = MAX_PDF_CHARS
) -> str:
    """从 base64 编码的 PDF 中提取文本。

    对超大文档做截断保护，避免无限撑爆模型上下文：最多取前 max_pages 页、
    拼接后最多保留 max_chars 字符，并在超限时附加提示。
    """
    import base64

    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ""
    try:
        raw = base64.b64decode(b64_content)
        doc = fitz.open(stream=raw, filetype="pdf")
        # 检测加密 PDF
        if doc.is_encrypted:
            # 尝试空密码解密（很多 PDF 用空密码加密只是限制编辑）
            if not doc.authenticate(""):
                doc.close()
                log.warning("PDF 已加密且无法用空密码解密")
                return "__ENCRYPTED__"
        pages = []
        truncated_pages = False
        for i, page in enumerate(doc):
            if i >= max_pages:
                truncated_pages = True
                break
            pages.append(page.get_text())
        doc.close()
        text = "\n\n".join(pages).strip()
        truncated_chars = False
        if len(text) > max_chars:
            text = text[:max_chars].rstrip()
            truncated_chars = True
        if truncated_pages or truncated_chars:
            text += (
                "\n\n[注意：原始文档较大，已自动截断（"
                + ("页数" if truncated_pages else "")
                + ("字符" if truncated_chars else "")
                + "上限）以保证分析可行，关键事实请以来源原件为准。]"
            )
        return text
    except Exception:
        return ""


def _text_to_case(text: str, filename: str = "") -> dict:
    """从纯文本构建案件 JSON 结构（PDF 上传时使用）。"""
    title = filename.replace(".pdf", "").replace(".PDF", "") or "上传案件"
    return {
        "title": title,
        "summary": text[:2000],
        "persons": [],
        "evidence": [],
        "timeline": [],
        "statutes": [],
        "images": [],
    }


@app.post("/api/cases/upload")
async def upload_case(payload: dict):
    from app.intake.processor import preprocess

    if not isinstance(payload, dict):
        return JSONResponse({"error": "案件须为 JSON 对象"}, status_code=400)
    data = dict(payload)

    # PDF 文件：从 base64 提取文本并构建案件结构
    if data.get("file_type") == "pdf" and data.get("file_content"):
        pdf_text = _extract_pdf_text(data["file_content"])
        if pdf_text == "__ENCRYPTED__":
            return JSONResponse(
                {"error": "PDF 已加密，请先解除密码保护后再上传"}, status_code=400
            )
        if not pdf_text:
            return JSONResponse(
                {"error": "PDF 文本提取失败，文件可能是扫描件（图片型 PDF），请粘贴文字内容"}, status_code=400
            )
        case_from_pdf = _text_to_case(pdf_text, data.get("file_name", ""))
        for k, v in case_from_pdf.items():
            if k not in data or not data[k]:
                data[k] = v
        data["pdf_text"] = pdf_text

    cid = str(data.get("id") or "").strip()
    if cid and not validate_id(cid):
        # cid 会参与案件文件名拼接，必须与 GET/DELETE 端点同等校验，
        # 否则 "../" 之类的值可以写出 cases 目录之外
        return JSONResponse({"error": "无效的案件 ID"}, status_code=400)
    if not cid:
        cid = "case_" + uuid.uuid4().hex[:8]
    data["id"] = cid
    cases_dir = os.path.join(data_dir, "cases")
    os.makedirs(cases_dir, exist_ok=True)
    # 标题去重：避免同名案件在列表中混淆
    _base = re.sub(r"\s*\(副本\d*\)\s*$", "", data.get("title", "上传案件"))
    _existing = 0
    try:
        for _fn in os.listdir(cases_dir):
            if not _fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(cases_dir, _fn), encoding="utf-8") as _f:
                    _c = json.load(_f)
                if (_c.get("title") or "").startswith(_base) and _c.get("id") != cid:
                    _existing += 1
            except Exception:
                continue
    except Exception:
        pass
    if _existing >= 1:
        data["title"] = _base + f" (副本{_existing})"
    try:
        data["brief"] = await preprocess(data)
    except Exception as ex:
        log.warning("preprocess failed for %s: %s", cid, ex)
        data["brief"] = {"intake_done": False, "error": str(ex)[:300]}
    try:
        from app.charts import generate_charts

        data["charts"] = generate_charts(data)
    except Exception as ex:
        log.warning("chart generation failed for %s: %s", cid, ex)
        data["charts"] = {}
    atomic_write_json(os.path.join(cases_dir, cid + ".json"), data)
    return {"case": data}


@app.delete("/api/cases/{case_id}")
async def delete_case(case_id: str):
    """删除案件（案例库管理）。"""
    import shutil

    if not validate_id(case_id):
        return JSONResponse({"error": "无效的案件 ID"}, status_code=400)
    cases_dir = os.path.join(data_dir, "cases")
    path = os.path.join(cases_dir, f"{case_id}.json")
    if not os.path.exists(path):
        return JSONResponse({"error": "案件不存在"}, status_code=404)
    os.remove(path)
    assets_dir = os.path.join(cases_dir, "assets", case_id)
    if os.path.exists(assets_dir):
        shutil.rmtree(assets_dir)
    return {"deleted": case_id}


@app.post("/api/verdict-qa")
async def verdict_qa(payload: dict):
    """裁决质询：辩论终结后，用户可就裁决继续向审判长追问。

    只依据卷宗与裁决内容作答，引用证据编号；供前端「裁决质询」面板使用。"""
    from langchain_core.messages import HumanMessage

    from app.agents.nodes import _retry_ainvoke
    from app.models.llm import get_llm

    data = payload if isinstance(payload, dict) else {}
    question = str(data.get("question") or "").strip()
    if not question:
        return JSONResponse({"error": "问题不能为空"}, status_code=400)
    verdict = data.get("verdict") or {}
    case_id = str(data.get("case_id") or "")
    case = load_case(case_id) if case_id and validate_id(case_id) else None

    case_facts = {
        "title": (case or {}).get("title", ""),
        "summary": ((case or {}).get("summary") or "")[:800],
        "evidence": [
            {"id": e.get("id"), "type": e.get("type"), "desc": (e.get("desc") or "")[:120]}
            for e in ((case or {}).get("evidence") or [])[:10]
        ],
        "verdict": verdict,
    }
    prompt = (
        "你是审判长。辩论已终结、裁决已作出。现在当事方就裁决提出质询，请以审判长身份答复：\n"
        "- 只依据卷宗与裁决内容，引用证据编号（如 [E-02]）；\n"
        "- 卷宗未覆盖的，明确说明属于待补充侦查/审查事项，不得编造；\n"
        "- 用中文、Markdown、条理清晰，250 字内。\n\n"
        "【裁决与卷宗要点】\n" + json.dumps(case_facts, ensure_ascii=False) +
        "\n\n【质询】\n" + question +
        "\n\n【裁决质询】请直接输出答复。"
    )
    llm = get_llm("审判长", temperature=0.2)
    try:
        resp = await _retry_ainvoke(llm, [HumanMessage(content=prompt)])
        content = resp.content if hasattr(resp, "content") else str(resp)
        answer = content if isinstance(content, str) else str(content)
    except Exception as ex:  # noqa: BLE001
        return JSONResponse({"error": f"质询答复失败：{str(ex)[:200]}"}, status_code=502)
    if not answer.strip():
        return JSONResponse({"error": "模型未返回有效答复"}, status_code=502)
    return {"answer": answer}


# ---------------- 策略模板（Presets）：本产品的"技能包" ----------------
_PRESETS_PATH = os.path.join(data_dir, "presets.json")

_BUILTIN_PRESETS: dict = {
    "刑事·严格证据攻防": {
        "guidance": "以证据裁判为主线：每一项指控事实必须对应证据编号；重点审查保管链、原始载体与取证程序；口供不作为定案唯一依据；对证明标准（排除合理怀疑）逐项检验。",
        "agents": {
            "law": "你是一位刑事诉讼证据法专家。除常规审查外，本轮请对每件关键证据逐项输出「三性」结论（真实性/合法性/关联性），并对证明标准达成度给出百分比估计与缺口清单。",
            "defense": "你是一位辩护 Agent。请优先攻击证据链中最薄弱的一环（保管链瑕疵、剪辑数据、身份不明生物检材），并明确给出替代事实模型；每个合理怀疑必须对应卷宗证据编号。",
        },
    },
    "民事·责任划分": {
        "guidance": "以合同与法律关系为骨架：先固定权利义务与违约事实，再按原因力比例划分责任；对不可抗力、减损义务、过错相抵逐项检验；赔偿数额须有计算依据。",
        "agents": {
            "psych": "你是一位集中于商业动机的分析专家：围绕交易背景、履约能力、违约获益与止损可能性构建动机与行为时间线，区分商业风险与主观过错。",
            "prosecutor": "你是一位主张方代理人：请按「合同成立 → 履行义务 → 违约事实 → 损失因果 → 数额依据」五步构建请求权基础，并引用《民法典》相应条文。",
        },
    },
}


def _load_presets() -> dict:
    presets = dict(_BUILTIN_PRESETS)
    try:
        with open(_PRESETS_PATH, encoding="utf-8") as f:
            custom = json.load(f)
        if isinstance(custom, dict):
            presets.update(custom)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return presets


@app.get("/api/presets")
def get_presets():
    return {"presets": _load_presets()}


@app.post("/api/presets")
def save_preset(payload: dict):
    from fastapi.responses import JSONResponse

    data = payload if isinstance(payload, dict) else {}
    name = str(data.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "模板名称不能为空"}, status_code=400)
    body = {"guidance": str(data.get("guidance") or ""),
            "agents": data.get("agents") or {}}
    custom = {}
    try:
        with open(_PRESETS_PATH, encoding="utf-8") as f:
            custom = json.load(f)
        if not isinstance(custom, dict):
            custom = {}
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    custom[name] = body
    atomic_write_json(_PRESETS_PATH, custom)
    return {"saved": name}


@app.delete("/api/presets/{name}")
def delete_preset(name: str):
    from fastapi.responses import JSONResponse

    if name in _BUILTIN_PRESETS:
        return JSONResponse({"error": "内置模板不可删除"}, status_code=400)
    custom = {}
    try:
        with open(_PRESETS_PATH, encoding="utf-8") as f:
            custom = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        custom = {}
    if name not in custom:
        return JSONResponse({"error": "模板不存在"}, status_code=404)
    del custom[name]
    atomic_write_json(_PRESETS_PATH, custom)
    return {"deleted": name}


@app.post("/api/presets/apply")
def apply_preset(payload: dict):
    """应用策略模板：写入各专家系统提示词（持久化到 agent_config），返回总体指导语。"""
    from fastapi.responses import JSONResponse

    from app.agents import agent_config as ac

    data = payload if isinstance(payload, dict) else {}
    name = str(data.get("name") or "").strip()
    presets = _load_presets()
    if name not in presets:
        return JSONResponse({"error": "模板不存在"}, status_code=404)
    preset = presets[name]
    cfg = ac.load()
    for role_key, prompt in (preset.get("agents") or {}).items():
        if role_key in cfg and prompt:
            cfg[role_key]["system_prompt"] = prompt
    ac.save(cfg)
    return {"applied": name, "guidance": preset.get("guidance", ""),
            "agents": ac.effective_list()}


@app.get("/api/knowledge")
def get_knowledge(q: str = ""):
    """知识库：内置法条 + 用户自定义条目，支持关键词检索。"""
    from app.legal.knowledge import list_knowledge, search_knowledge

    return {"entries": search_knowledge(q) if q.strip() else list_knowledge()}


@app.post("/api/knowledge")
def post_knowledge(payload: dict):
    """新增自定义知识条目（标题/正文/关键词）。"""
    from fastapi.responses import JSONResponse

    from app.legal.knowledge import add_knowledge

    data = payload if isinstance(payload, dict) else {}
    title = str(data.get("title") or "").strip()
    text = str(data.get("text") or "").strip()
    if not title or not text:
        return JSONResponse({"error": "标题与正文不能为空"}, status_code=400)
    kws = data.get("keywords") or []
    if isinstance(kws, str):
        kws = [k for k in kws.replace("，", ",").split(",") if k.strip()]
    entry = add_knowledge(title, text, kws)
    return {"entry": entry}


@app.delete("/api/knowledge/{entry_id}")
def remove_knowledge(entry_id: str):
    """删除自定义知识条目（内置法条不可删除）。"""
    from fastapi.responses import JSONResponse

    from app.legal.knowledge import delete_knowledge

    if not delete_knowledge(entry_id):
        return JSONResponse({"error": "条目不存在或为内置法条（不可删除）"}, status_code=400)
    return {"deleted": entry_id}


@app.websocket("/ws/{session_id}")
async def ws_endpoint(websocket: WebSocket, session_id: str):
    # 访问口令启用时，WebSocket 同样校验登录 cookie（ accept 前拒绝，避免产生半开连接）
    if settings.access_password and not _verify_session(
        websocket.cookies.get(_AUTH_COOKIE)
    ):
        await websocket.close(code=4401)
        return
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
    debate_task = None

    async def receiver():
        nonlocal debate_task
        while True:
            try:
                msg = await websocket.receive_json()
            except Exception:
                break
            msg_type = msg.get("type")
            if msg_type == "start":
                # 已有辩论在运行时，先取消再启动新的
                if debate_task is not None and not debate_task.done():
                    debate_task.cancel()
                    try:
                        await debate_task
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
                debate_task = asyncio.create_task(
                    run_debate(case, session_id, agents, overrides or None)
                )
            elif msg_type == "stop":
                if debate_task is not None and not debate_task.done():
                    debate_task.cancel()
                    try:
                        await debate_task
                    except Exception:
                        pass
                    await manager.send(session_id, {"kind": "stopped", "message": "辩论已被用户停止"})
                debate_task = None
            elif msg_type == "human":
                await manager.push_human(
                    session_id, msg.get("text", ""), msg.get("subtype", "intervene")
                )

    task = asyncio.create_task(receiver())
    try:
        await task
    finally:
        manager.disconnect(session_id)
        # 客户端断开后取消仍在后台跑的辩论，避免白白消耗 API 额度
        if debate_task is not None and not debate_task.done():
            debate_task.cancel()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
