# -*- coding: utf-8 -*-
"""认证信息与多用户 RBAC 管理路由。

- GET  /api/auth/me        当前会话身份（user/role/mode）
- GET  /api/admin/users    用户列表（admin）
- POST /api/admin/users    创建/更新用户（admin）
- DELETE /api/admin/users/{username}  删除用户（admin）
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request

from app import auth
from app.auth import require_admin

router = APIRouter(tags=["auth"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin-users"])

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\-\u4e00-\u9fa5]{2,32}$")


@router.get("/api/auth/me")
def auth_me(request: Request):
    """当前会话身份。单口令模式恒为 admin；多用户模式返回实际角色。"""
    ident = auth.current_identity(request)
    return {
        "user": ident["user"],
        "role": ident["role"],
        "mode": "multi" if auth.users_enabled() else "single",
        "auth_enabled": bool(auth.settings.access_password),
    }


@admin_router.get("/users")
def list_users(request: Request, _: dict = Depends(require_admin)):
    users = [
        {
            "username": u["username"],
            "role": u["role"],
            "enabled": bool(u.get("enabled", True)),
        }
        for u in auth.load_users()
    ]
    return {"users": users}


@admin_router.post("/users")
def set_user(
    payload: dict,
    request: Request,
    _: dict = Depends(require_admin),
):
    """创建或更新用户：{username, password?, role?, enabled?}。
    不传 password 视为仅改角色/启用状态；传则重置密码。"""
    username = str(payload.get("username") or "").strip()
    if not _USERNAME_RE.match(username):
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="用户名需为 2-32 位字母/数字/下划线/中文")
    role = str(payload.get("role") or auth.ROLE_VIEWER)
    if role not in (auth.ROLE_ADMIN, auth.ROLE_VIEWER):
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="角色只能是 admin 或 viewer")

    users = auth.load_users()
    existing = auth._find_user(users, username)
    password = str(payload.get("password") or "")
    if existing is None and not password:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="新用户必须设置密码")
    if password and len(password) < 8:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="密码至少 8 位")

    if existing is None:
        salt = auth._new_salt()
        users.append(
            {
                "username": username,
                "salt": salt,
                "hash": auth._pw_hash(password, salt),
                "role": role,
                "enabled": bool(payload.get("enabled", True)),
            }
        )
    else:
        if payload.get("role") is not None:
            existing["role"] = role
        if payload.get("enabled") is not None:
            existing["enabled"] = bool(payload["enabled"])
        if password:
            existing["salt"] = auth._new_salt()
            existing["hash"] = auth._pw_hash(password, existing["salt"])
    auth._save_users(users)
    return {"ok": True, "username": username, "role": role}


@admin_router.delete("/users/{username}")
def delete_user(
    username: str,
    request: Request,
    _: dict = Depends(require_admin),
):
    from fastapi import HTTPException

    users = auth.load_users()
    if not users:
        raise HTTPException(status_code=404, detail="用户表为空")
    target = auth._find_user(users, username)
    if target is None:
        raise HTTPException(status_code=404, detail=f"用户 {username} 不存在")
    # 防止管理员误删自己导致锁死（最后一名 admin 不可删/不可降级）
    admins = [u for u in users if u.get("role") == auth.ROLE_ADMIN and u.get("enabled", True)]
    if target.get("role") == auth.ROLE_ADMIN and len(admins) <= 1:
        raise HTTPException(status_code=409, detail="至少保留一名启用的管理员")
    users.remove(target)
    auth._save_users(users)
    return {"ok": True, "username": username}