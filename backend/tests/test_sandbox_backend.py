"""沙箱后端选择测试：docker 命令构造（断网/资源上限）、auto 降级、
容器模式下 install_package 的明确提示。不在测试里真正调用 docker。"""

import sys

import pytest

from app.agents import tools as T
from app.config import settings


@pytest.fixture(autouse=True)
def _sandbox_setup():
    settings.code_sandbox_python = sys.executable
    settings.code_sandbox_enabled = True
    # 默认强制子进程：本文件用 monkeypatch 显式选择被测后端，
    # 避免依赖本机 Docker 的真实状态（存在与否/镜像是否拉取）
    settings.code_sandbox_backend = "subprocess"
    T._docker_ok = None
    yield
    T._docker_ok = None


def test_docker_command_is_network_isolated_with_limits():
    cmd = T._docker_command("print(1)", "C:/tmp/out")
    assert cmd[:2] == ["docker", "run"]
    assert "--network=none" in cmd
    assert "--memory=512m" in cmd
    assert "--cpus=1" in cmd
    assert cmd[cmd.index("--pids-limit") + 1] == "128"
    assert "-I" in cmd  # 隔离模式保留
    assert cmd[-1] == "print(1)"


def test_docker_backend_forces_container(monkeypatch):
    monkeypatch.setattr(settings, "code_sandbox_backend", "docker")
    monkeypatch.setattr(T, "_docker_ok", True)
    monkeypatch.setattr(T, "_image_available", lambda: True)
    captured = {}
    monkeypatch.setattr(
        T.subprocess, "run",
        lambda cmd, **kw: (captured.update(cmd=cmd), _fake_completed("ok"))[1],
    )
    out = T.run_code.invoke({"code": "print(1)"})
    assert captured["cmd"][0] == "docker"
    assert "ok" in out


def test_auto_falls_back_to_subprocess_without_docker(monkeypatch):
    monkeypatch.setattr(T, "_docker_ok", False)
    captured = {}
    monkeypatch.setattr(
        T.subprocess, "run",
        lambda cmd, **kw: (captured.update(cmd=cmd), _fake_completed("ok"))[1],
    )
    out = T.run_code.invoke({"code": "print(1)"})
    assert captured["cmd"][0] == settings.code_sandbox_python
    assert "ok" in out


def test_auto_falls_back_when_image_missing(monkeypatch):
    """Docker 在但镜像未拉取：auto 降级子进程，而不是现场拉镜像拖垮辩论。"""
    monkeypatch.setattr(T, "_docker_ok", True)
    monkeypatch.setattr(T, "_image_available", lambda: False)
    captured = {}
    monkeypatch.setattr(
        T.subprocess, "run",
        lambda cmd, **kw: (captured.update(cmd=cmd), _fake_completed("ok"))[1],
    )
    out = T.run_code.invoke({"code": "print(1)"})
    assert captured["cmd"][0] == settings.code_sandbox_python
    assert "ok" in out


def test_docker_backend_image_missing_gives_pull_hint(monkeypatch):
    monkeypatch.setattr(settings, "code_sandbox_backend", "docker")
    monkeypatch.setattr(T, "_docker_ok", True)
    monkeypatch.setattr(T, "_image_available", lambda: False)
    out = T.run_code.invoke({"code": "print(1)"})
    assert "docker pull" in out
    assert settings.code_sandbox_docker_image in out


def test_docker_backend_without_docker_gives_actionable_error(monkeypatch):
    monkeypatch.setattr(settings, "code_sandbox_backend", "docker")
    monkeypatch.setattr(T, "_docker_ok", False)
    out = T.run_code.invoke({"code": "print(1)"})
    assert "CODE_SANDBOX_BACKEND" in out and "docker" in out


def test_install_package_in_docker_mode_explains(monkeypatch):
    monkeypatch.setattr(settings, "code_sandbox_backend", "docker")
    monkeypatch.setattr(T, "_docker_ok", True)
    monkeypatch.setattr(T, "_image_available", lambda: True)
    out = T.install_package.invoke({"package": "scipy"})
    assert "一次性容器" in out
    assert "CODE_SANDBOX_DOCKER_IMAGE" in out


def _fake_completed(stdout=""):
    import subprocess

    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")
