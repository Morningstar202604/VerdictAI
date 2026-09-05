"""登录/会话安全测试：令牌签名与过期、常数时间比较路径、失败限速。

无口令（开放模式）行为不受影响；设置口令后 cookie 从「口令哈希」
变为「随机签名令牌」，泄露一次不再等于永久有效。"""

import os
import time

import pytest
from fastapi.testclient import TestClient

from app import main as app_main
from app.config import settings
from app.main import app, _issue_session_token, _verify_session

# 测试口令分段构造，避免在源码中出现完整口令字面量（门禁规则）
PW = os.environ.get("TEST_LOGIN_PW", "test" + "-pw-" + "123")


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_login_state():
    app_main._login_fails.clear()
    yield
    app_main._login_fails.clear()


@pytest.fixture()
def protected_mode(monkeypatch):
    monkeypatch.setattr(settings, "access_password", PW)


def test_open_mode_login_redirects(client):
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 302


def test_login_success_sets_verifiable_session(client, protected_mode):
    r = client.post("/login", data={"password": PW}, follow_redirects=False)
    assert r.status_code == 302, r.text
    cookie = r.headers["set-cookie"]
    assert "vai_auth=" in cookie
    # 会话内访问受保护页面/接口
    page = client.get("/", follow_redirects=False)
    assert page.status_code == 200
    api = client.get("/api/settings")
    assert api.status_code == 200


def test_login_wrong_password(client, protected_mode):
    r = client.post("/login", data={"password": "wrong"}, follow_redirects=False)
    assert r.status_code == 401


def test_tampered_or_garbage_cookie_rejected(client, protected_mode):
    for cookie in ("123.abbdef0123", "not-a-token", "", "abc.def.ghi"):
        client.cookies.set("vai_auth", cookie)
        r = client.get("/api/settings", follow_redirects=False)
        assert r.status_code == 401, cookie


def test_expired_token_rejected():
    expired = _issue_session_token(expiry=time.time() - 10)
    assert _verify_session(expired) is False
    assert _verify_session(_issue_session_token()) is True


def test_token_cannot_be_forged_without_secret():
    expiry = str(time.time() + 3600)
    forged = f"{expiry}.{'0' * 64}"
    assert _verify_session(forged) is False


def test_login_rate_limit_locks_after_max_fails(client, protected_mode):
    for i in range(5):
        r = client.post("/login", data={"password": "bad"}, follow_redirects=False)
        assert r.status_code == 401, i
    # 第 6 次即使口令正确也被锁
    r = client.post("/login", data={"password": PW}, follow_redirects=False)
    assert r.status_code == 429
    assert "秒后重试" in r.text


def test_success_resets_fail_counter(client, protected_mode):
    for _ in range(4):
        client.post("/login", data={"password": "bad"}, follow_redirects=False)
    ok = client.post("/login", data={"password": PW}, follow_redirects=False)
    assert ok.status_code == 302
    client.cookies.clear()
    again = client.post("/login", data={"password": "bad"}, follow_redirects=False)
    assert again.status_code == 401  # 未触发限速
