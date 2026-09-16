# -*- coding: utf-8 -*-
"""访问认证：访问口令门（ACCESS_PASSWORD 为空时完全开放）+ 可选多用户 RBAC。

两种模式（自动切换，向前兼容）：
- 单口令模式：未配置 users 表（data/users.json 不存在或为空）时，仅用
  ACCESS_PASSWORD 校验，登录用户固定为 admin。
- 多用户模式：users 表存在且非空时按 用户名+密码 登录，支持角色
  admin（全部写操作）/ viewer（只读，仅庭审与浏览）。

会话令牌为 {过期时间戳}.{base64(user:role)}.{HMAC 签名}：密钥每次进程启动
随机生成，重启后旧会话失效需重新登录；签名使令牌无法伪造，过期时间无法
延长；全部比较走 compare_digest，避免时序侧信道。
登录按 IP 计入失败次数并锁定，避免口令被爆。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time as _time

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import settings

_AUTH_COOKIE = "vai_auth"
SESSION_TTL_SECONDS = 7 * 24 * 3600
_LOGIN_MAX_FAILS = 5
_LOGIN_LOCK_SECONDS = 900
_login_fails: dict = {}

# /sw.js 为 Service Worker 脚本根路径（见 main.py 的同名路由），必须免登录：
# 否则开启访问口令后浏览器拿不到脚本，PWA 离线安装整体失效。
_EXEMPT_PREFIXES = ("/login", "/static/assets/", "/api/health", "/favicon", "/sw.js")

_SESSION_SECRET_BYTES = secrets.token_bytes(32)

ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
_VALID_ROLES = (ROLE_ADMIN, ROLE_VIEWER)


# ---------------------------------------------------------------------------
# 多用户 users 表（data/users.json）
# ---------------------------------------------------------------------------
def users_path() -> str:
    return os.path.join(settings.data_dir, "users.json")


def load_users() -> list:
    """读取 users 表；文件缺失/损坏返回空列表（此时走单口令兼容模式）。"""
    p = users_path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            return []
        return [
            u
            for u in data
            if isinstance(u, dict)
            and str(u.get("username") or "").strip()
            and str(u.get("role") or "") in _VALID_ROLES
        ]
    except Exception:
        return []


def users_enabled() -> bool:
    """多用户模式激活条件：用户表非空（且访问口令仍可作备用门禁）。"""
    return len(load_users()) > 0


def _pw_hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 120_000
    ).hex()


def _new_salt() -> str:
    return secrets.token_hex(16)


def _save_users(users: list) -> bool:
    """原子写入 users 表（复用 store.atomic_write_json 的落盘策略）。"""
    from app.data.store import atomic_write_json

    atomic_write_json(users_path(), users, indent=2)
    return True


def _find_user(users: list, username: str) -> dict | None:
    target = str(username or "").strip()
    for u in users:
        if str(u.get("username") or "").strip() == target:
            return u
    return None


def verify_user_login(username: str, password: str) -> dict | None:
    """校验用户名+密码：成功返回用户记录（含 role），失败返回 None。"""
    users = load_users()
    if not users:
        return None
    u = _find_user(users, username)
    if u is None or not u.get("enabled", True):
        return None
    salt = str(u.get("salt") or "")
    if not salt:
        return None
    if not hmac.compare_digest(
        _pw_hash(str(password or ""), salt), str(u.get("hash") or "")
    ):
        return None
    return {"username": u["username"], "role": u["role"], "enabled": True}


# ---------------------------------------------------------------------------
# 会话令牌（携带身份）
# ---------------------------------------------------------------------------
def _issue_session_token(
    expiry: float = None, user: str = "admin", role: str = ROLE_ADMIN
) -> str:
    if expiry is None:
        expiry = int(_time.time()) + SESSION_TTL_SECONDS
    payload = base64.urlsafe_b64encode(
        json.dumps({"u": str(user)[:64], "r": role}, ensure_ascii=False).encode()
    ).decode()
    sig = hmac.new(
        _SESSION_SECRET_BYTES,
        msg=f"{int(expiry)}.{payload}".encode(),
        digestmod=hashlib.sha256,
    )
    return f"{int(expiry)}.{payload}.{sig.hexdigest()}"


# 保持与历史测试约定的名称（下划线前缀版本）
_issue_session_token_legacy = _issue_session_token


def _parse_token(token: str | None) -> dict | None:
    """解析令牌：返回 {exp, user, role}；非法/过期返回 None。"""
    if not token or not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    exp_str, payload_b64, sig = parts
    try:
        expiry = float(exp_str)
    except ValueError:
        return None
    expected = hmac.new(
        _SESSION_SECRET_BYTES,
        msg=f"{exp_str}.{payload_b64}".encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    if expiry <= _time.time():
        return None
    try:
        info = json.loads(
            base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4))
        )
    except Exception:
        return None
    role = str(info.get("r") or ROLE_ADMIN)
    return {
        "exp": expiry,
        "user": str(info.get("u") or "admin")[:64],
        "role": role if role in _VALID_ROLES else ROLE_ADMIN,
    }


def verify_session(token: str | None) -> bool:
    """令牌有效性校验（公开接口，仅返回是否有效）。"""
    return _parse_token(token) is not None


# 保持与历史测试约定的名称（下划线前缀版本）
_verify_session = verify_session


def session_identity(token: str | None) -> dict | None:
    """当前会话身份：{user, role}；未登录/过期返回 None。"""
    parsed = _parse_token(token)
    if parsed is None:
        return None
    return {"user": parsed["user"], "role": parsed["role"]}


def role_of(token: str | None) -> str:
    """当前会话角色（未登录视为空；单口令兼容模式下始终 admin）。"""
    ident = session_identity(token)
    if ident is not None:
        return ident["role"]
    # 无用户表（单口令模式）且口令本就启用时，令牌必然已签发 admin；
    # 直接返回视角角色。
    return ROLE_ADMIN if not users_enabled() else ROLE_VIEWER


def is_admin(token: str | None) -> bool:
    return role_of(token) == ROLE_ADMIN


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
        token = request.cookies.get(_AUTH_COOKIE)
        if not verify_session(token):
            if path.startswith("/api/"):
                return JSONResponse({"error": "未登录或会话已过期"}, status_code=401)
            return RedirectResponse("/login", status_code=302)
    return await call_next(request)


# ---------------------------------------------------------------------------
# 登录页（支持 多用户/单口令 两种形态）
# ---------------------------------------------------------------------------
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
 .muted{font-size:11px;color:#6b7a8c;margin-top:10px;}
</style></head><body>
 <div class="card">
  <img src="/static/assets/logo.svg" alt="VerdictAI">
  <h1>VerdictAI · 智能探案合议庭</h1>
  <p>{subtitle}</p>
  <form method="post" action="/login">
    {user_field}
    <input type="password" name="password" placeholder="{pw_ph}" autofocus>
    <button type="submit">进 入</button>
  </form>
  <div class="err">{error}</div>
 </div>
</body></html>"""


async def login_page(request: Request):
    if not settings.access_password:
        return RedirectResponse("/", status_code=302)
    multi = users_enabled()
    user_field = (
        '<input type="text" name="username" placeholder="用户名" autocomplete="username">'
        if multi
        else ""
    )
    subtitle = "使用账号登录（多用户模式）" if multi else "本系统受访问口令保护，请输入后继续"
    pw_ph = "密码" if multi else "访问口令"
    return HTMLResponse(
        _LOGIN_PAGE
        .replace("{error}", "")
        .replace("{subtitle}", subtitle)
        .replace("{user_field}", user_field)
        .replace("{pw_ph}", pw_ph)
    )


async def login_submit(
    request: Request,
    password: str = Form(""),
    username: str = Form(""),
):
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

    multi = users_enabled()
    if multi:
        user = verify_user_login(username, password)
        if user is None:
            _record_login_fail(ip)
            return HTMLResponse(
                _login_page_simple("用户名或密码错误，请重试"),
                status_code=401,
            )
        display_name = user["username"]
        role = user["role"]
    else:
        # 单口令兼容模式：常数时间比较；登录固定为 admin
        ok = bool(password) and hmac.compare_digest(
            password.encode(), settings.access_password.encode()
        )
        if not ok:
            _record_login_fail(ip)
            return HTMLResponse(
                _login_page_simple("口令错误，请重试"),
                status_code=401,
            )
        display_name = "admin"
        role = ROLE_ADMIN

    _record_login_success(ip)
    resp = RedirectResponse("/", status_code=302)
    is_https = (
        request.url.scheme == "https"
        or request.headers.get("x-forwarded-proto") == "https"
    )
    resp.set_cookie(
        _AUTH_COOKIE,
        _issue_session_token(user=display_name, role=role),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=is_https,
    )
    return resp


def _login_page_simple(error: str) -> str:
    return (
        _LOGIN_PAGE
        .replace("{error}", error)
        .replace("{user_field}", "")
        .replace("{pw_ph}", "访问口令")
        .replace("{subtitle}", "本系统受访问口令保护，请输入后继续")
    )


def current_identity(request: Request) -> dict:
    """当前请求的身份信息（供路由依赖使用）。

    无访问口令（完全开放）时视为单一 admin；有口令但未登录回退 viewer。"""
    if not settings.access_password:
        return {"user": "admin", "role": ROLE_ADMIN}
    ident = session_identity(request.cookies.get(_AUTH_COOKIE))
    if ident is None:
        ident = {"user": "anon", "role": ROLE_VIEWER}
    return ident


async def require_admin(request: Request) -> dict:
    """FastAPI 依赖：强制管理员会话。仅访问口令启用时做角色校验；
    口令关闭（完全开放）时放行（此时任何场景都视为单一 admin 用户）。"""
    from fastapi import HTTPException

    pwd = settings.access_password
    if not pwd:
        return {"user": "admin", "role": ROLE_ADMIN}
    ident = session_identity(request.cookies.get(_AUTH_COOKIE))
    if ident is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    if ident.get("role") != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return ident


async def require_viewer(request: Request) -> dict:
    """FastAPI 依赖：要求已登录（admin 或 viewer）；口令关闭时放行。"""
    from fastapi import HTTPException

    pwd = settings.access_password
    if not pwd:
        return {"user": "admin", "role": ROLE_ADMIN}
    ident = session_identity(request.cookies.get(_AUTH_COOKIE))
    if ident is None:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    return ident


# ---------------------------------------------------------------------------
# API 限流（P2-4）
# ---------------------------------------------------------------------------
# 固定窗口令牌桶：按客户端 IP 统计窗口内请求数，超限返回 429 + Retry-After。
# 对标大厂 Agent 平台的限流策略（OpenAI/Anthropic 均按 key/IP 限流）。
# 登录页与健康检查豁免，避免合法用户被误伤。rate_limit_max=0 关闭。
_RATE_BUCKETS: dict = {}  # ip -> [window_start, count]


def rate_limit_exempt(path: str) -> bool:
    return any(
        path == pfx or path.startswith(pfx)
        for pfx in ("/login", "/api/health", "/favicon", "/static/", "/sandbox")
    )


async def rate_limit_middleware(request: Request, call_next):
    """限流中间件：配置文件里 RATE_LIMIT_MAX=0（默认）即放行，绝不影响现有部署。"""
    m = settings.rate_limit_max
    if m <= 0 or rate_limit_exempt(request.url.path):
        return await call_next(request)
    ip = request.client.host if request.client else "unknown"
    now = _time.time()
    win = settings.rate_limit_window
    bucket = _RATE_BUCKETS.get(ip)
    if bucket is None or now - bucket[0] >= win:
        # 新窗口：重置计数；顺带清理过期桶，防止字典被海量 IP 撑爆
        _RATE_BUCKETS[ip] = [now, 1]
        if len(_RATE_BUCKETS) > 20000:
            stale = [k for k, (ts, _c) in _RATE_BUCKETS.items() if now - ts >= win]
            for k in stale:
                _RATE_BUCKETS.pop(k, None)
    elif bucket[1] >= m:
        retry = int(win - (now - bucket[0]))
        return JSONResponse(
            {"error": f"请求过于频繁，请 {retry} 秒后重试"},
            status_code=429,
            headers={"Retry-After": str(max(1, retry))},
        )
    else:
        bucket[1] += 1
    return await call_next(request)


def reset_rate_limits() -> None:
    """清理限流桶（测试用）。"""
    _RATE_BUCKETS.clear()