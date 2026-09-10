# -*- coding: utf-8 -*-
"""访问认证：访问口令门（ACCESS_PASSWORD 为空时完全开放）。

会话令牌为 {过期时间戳}.{HMAC 签名}：密钥每次进程启动随机生成，
重启后旧会话失效需重新登录；签名使令牌无法伪造，过期时间无法延长；
全部比较走 compare_digest，避免时序侧信道。
登录按 IP 计入失败次数并锁定，避免口令被爆。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time as _time

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings

_AUTH_COOKIE = "vai_auth"
SESSION_TTL_SECONDS = 7 * 24 * 3600
_LOGIN_MAX_FAILS = 5
_LOGIN_LOCK_SECONDS = 900
_login_fails: dict = {}

_EXEMPT_PREFIXES = ("/login", "/static/assets/", "/api/health", "/favicon")

_SESSION_SECRET_BYTES = secrets.token_bytes(32)


def _issue_session_token(expiry: float = None) -> str:
    # 整数时间戳：令牌里 "." 是分隔符，过期值不能带小数点
    if expiry is None:
        expiry = int(_time.time()) + SESSION_TTL_SECONDS
    sig = hmac.new(
        _SESSION_SECRET_BYTES, msg=str(int(expiry)).encode(), digestmod=hashlib.sha256
    )
    return f"{int(expiry)}.{sig.hexdigest()}"


def verify_session(token: str | None) -> bool:
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


# 保持与历史测试约定的名称（下划线前缀版本）
_verify_session = verify_session


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


async def access_gate(request: Request, call_next):
    """所有页面/API/WS 的访问口令门。登录页与静态品牌资源放行。"""
    pwd = settings.access_password
    path = request.url.path
    if pwd and not any(path.startswith(pfx) or path == pfx for pfx in _EXEMPT_PREFIXES):
        from fastapi.responses import JSONResponse

        if not verify_session(request.cookies.get(_AUTH_COOKIE)):
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


async def login_page(request: Request):
    if not settings.access_password:
        return RedirectResponse("/", status_code=302)
    return HTMLResponse(_LOGIN_PAGE.replace("{error}", ""))


async def login_submit(request: Request, password: str = Form("")):
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
        is_https = (
            request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto") == "https"
        )
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