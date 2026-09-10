"""多用户 RBAC（P1-6）：users 表登录、角色令牌、admin/viewer 写门禁。

保证单口令模式完全向后兼容（test_login_security 已覆盖），此处只覆盖
多用户模式的新行为。"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.auth import ROLE_ADMIN, ROLE_VIEWER
from app.config import settings
from app.main import app


def _write_users(users):
    os.makedirs(settings.data_dir, exist_ok=True)
    with open(auth.users_path(), "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False)


def _mk_user(username, password, role=ROLE_VIEWER, enabled=True):
    salt = auth._new_salt()
    return {
        "username": username,
        "salt": salt,
        "hash": auth._pw_hash(password, salt),
        "role": role,
        "enabled": enabled,
    }


@pytest.fixture()
def multi_users(monkeypatch):
    """启用多用户模式：把全局 data_dir 指向临时目录并写入 users 表。"""
    import tempfile

    tmp = tempfile.mkdtemp(prefix="vai-rbac-")
    monkeypatch.setattr(settings, "data_dir", tmp)
    monkeypatch.setattr(settings, "access_password", "door-123")
    auth._save_users(
        [
            _mk_user("admin1", "admin-pass-1", ROLE_ADMIN),
            _mk_user("viewer1", "viewer-pass-1", ROLE_VIEWER),
            _mk_user("locked1", "locked-pass-1", ROLE_VIEWER, enabled=False),
        ]
    )
    yield
    if os.path.exists(auth.users_path()):
        os.remove(auth.users_path())


@pytest.fixture(autouse=True)
def _reset():
    auth._login_fails.clear()
    yield
    auth._login_fails.clear()


def login(client, username, password):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def test_multi_login_viewer_sets_viewer_session(multi_users):
    c = TestClient(app)
    r = login(c, "viewer1", "viewer-pass-1")
    assert r.status_code == 302
    me = c.get("/api/auth/me").json()
    assert me["user"] == "viewer1"
    assert me["role"] == ROLE_VIEWER
    assert me["mode"] == "multi"


def test_multi_login_admin_sets_admin_session(multi_users):
    c = TestClient(app)
    r = login(c, "admin1", "admin-pass-1")
    assert r.status_code == 302
    me = c.get("/api/auth/me").json()
    assert me["role"] == ROLE_ADMIN


def test_multi_login_wrong_password(multi_users):
    c = TestClient(app)
    r = login(c, "viewer1", "wrong-pass")
    assert r.status_code == 401


def test_multi_login_disabled_user_rejected(multi_users):
    c = TestClient(app)
    r = login(c, "locked1", "locked-pass-1")
    assert r.status_code == 401


def test_viewer_cannot_write_settings(multi_users):
    c = TestClient(app)
    login(c, "viewer1", "viewer-pass-1")
    r = c.post("/api/settings", json={"max_rounds": 4})
    assert r.status_code == 403


def test_viewer_can_read_settings(multi_users):
    c = TestClient(app)
    login(c, "viewer1", "viewer-pass-1")
    r = c.get("/api/settings")
    assert r.status_code == 200


def test_admin_can_write_settings(multi_users):
    c = TestClient(app)
    login(c, "admin1", "admin-pass-1")
    r = c.post("/api/settings", json={})
    assert r.status_code == 200


def test_viewer_cannot_manage_users(multi_users):
    c = TestClient(app)
    login(c, "viewer1", "viewer-pass-1")
    assert c.get("/api/admin/users").status_code == 403
    r = c.post("/api/admin/users", json={"username": "hack", "password": "x" * 10})
    assert r.status_code == 403


def test_admin_can_create_and_delete_user(multi_users):
    c = TestClient(app)
    login(c, "admin1", "admin-pass-1")
    r = c.post("/api/admin/users", json={"username": "bob", "password": "bob-pass-123", "role": "viewer"})
    assert r.status_code == 200, r.text
    users = c.get("/api/admin/users").json()["users"]
    assert any(u["username"] == "bob" for u in users)
    # 新用户即可登录
    c2 = TestClient(app)
    assert login(c2, "bob", "bob-pass-123").status_code == 302
    r = c.delete("/api/admin/users/bob")
    assert r.status_code == 200
    names = [u["username"] for u in c.get("/api/admin/users").json()["users"]]
    assert "bob" not in names


def test_last_admin_guard(multi_users):
    """最后一个启用的 admin 不可删除，防止锁死系统。"""
    c = TestClient(app)
    login(c, "admin1", "admin-pass-1")
    r = c.delete("/api/admin/users/admin1")
    assert r.status_code == 409


def test_forged_viewer_token_cannot_be_admin(multi_users):
    """伪造角色提升：即使构造 viewer 会话也无法通过 admin 门禁。"""
    c = TestClient(app)
    r = login(c, "viewer1", "viewer-pass-1")
    assert r.status_code == 302
    r = c.post("/api/agent-config", json={})
    assert r.status_code == 403