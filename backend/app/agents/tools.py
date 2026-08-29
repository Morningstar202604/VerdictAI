from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Dict, List

from langchain_core.tools import tool

from app.config import settings

_IMG_EXT = (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp")
_base_checked = False


def _ensure_base() -> None:
    """首次使用时尽力安装基础科学计算/图表库（numpy/pandas/matplotlib），仅尝试一次。"""
    global _base_checked
    if _base_checked:
        return
    _base_checked = True
    try:
        import matplotlib  # noqa: F401
        import numpy  # noqa: F401
        import pandas  # noqa: F401

        return
    except Exception:
        try:
            subprocess.run(
                [
                    settings.code_sandbox_python,
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "numpy",
                    "pandas",
                    "matplotlib",
                ],
                capture_output=True,
                text=True,
                timeout=240,
            )
        except Exception:
            pass


# 工具层：各智能体可调用的能力。运行前通过 activate_case 注入当前卷宗。
_ACTIVE_CASE: Dict = {}


def activate_case(case: Dict) -> None:
    _ACTIVE_CASE.clear()
    _ACTIVE_CASE.update(case or {})


@tool
def read_evidence(evidence_id: str) -> str:
    """读取指定物证/书证编号的详细内容。输入证据编号，如 'E-03'。"""
    items = _ACTIVE_CASE.get("evidence", [])
    for e in items:
        if e.get("id") == evidence_id:
            return json.dumps(e, ensure_ascii=False)
    return f"未找到证据 {evidence_id}。现有证据编号：{', '.join(e.get('id', '') for e in items)}"


@tool
def timeline_check() -> str:
    """返回本案关键时间线，用于核对各专家推断是否矛盾。"""
    return json.dumps(_ACTIVE_CASE.get("timeline", []), ensure_ascii=False, indent=2)


@tool
def list_contradictions() -> str:
    """列出当前已记录的矛盾点清单。"""
    return json.dumps(
        _ACTIVE_CASE.get("contradictions", []), ensure_ascii=False, indent=2
    )


@tool
def search_case_law(keyword: str) -> str:
    """检索与关键词相关的法条或类案要旨。输入法律关键词，如 '非法证据排除'。"""
    laws = _ACTIVE_CASE.get("statutes", [])
    hits = [l for l in laws if keyword in (l.get("topic", "") + l.get("text", ""))]
    if not hits:
        return f"卷宗中暂无与「{keyword}」直接相关的法条。"
    return json.dumps(hits, ensure_ascii=False, indent=2)


@tool
def cite_source(fact: str) -> str:
    """要求为某事实标注依据。返回该事实应有的证据来源提示。"""
    return f"请为事实「{fact}」提供证据编号或法条依据，否则视为无依据推测。"


@tool
def run_code(code: str) -> str:
    """在受控沙箱中执行 Python 代码并返回标准输出与错误。用于对证据数据做统计、比对、时间线推算；也可生成图表（matplotlib，Agg 后端），保存到环境变量 SANDBOX_OUT 指向的目录，返回中会附带图片链接，将在笔录中渲染。"""
    if not settings.code_sandbox_enabled:
        return "代码沙箱未启用。请在「设置 → 运行环境」中开启「启用 Python 代码沙箱」。"
    _ensure_base()
    out_dir = settings.sandbox_out_dir
    os.makedirs(out_dir, exist_ok=True)
    before = set(os.listdir(out_dir))
    env = dict(os.environ)
    env["SANDBOX_OUT"] = out_dir
    env["MPLBACKEND"] = "Agg"
    try:
        proc = subprocess.run(
            [settings.code_sandbox_python, "-I", "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
    except FileNotFoundError:
        return f"未找到 Python 解释器：{settings.code_sandbox_python}"
    except subprocess.TimeoutExpired:
        return "执行超时（>60s），已中止。"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    body = out
    if err:
        body += ("\n\n[stderr]\n" + err) if body else ("[stderr]\n" + err)
    if proc.returncode != 0:
        body += f"\n\n[exit code {proc.returncode}]"
    new_imgs = sorted(
        f for f in (set(os.listdir(out_dir)) - before) if f.lower().endswith(_IMG_EXT)
    )
    if new_imgs:
        body += "\n\n" + "\n".join(f"![{f}](/sandbox/{f})" for f in new_imgs)
    return body or "（无输出）"


@tool
def install_package(package: str) -> str:
    """安装额外的 Python 包到沙箱环境（需要联网），以便专家使用更多能力（如 scipy、openpyxl）。"""
    if not settings.code_sandbox_enabled:
        return "代码沙箱未启用。"
    pkg = (package or "").strip()
    if not pkg:
        return "请提供包名，例如 numpy、pandas、matplotlib。"
    try:
        proc = subprocess.run(
            [settings.code_sandbox_python, "-m", "pip", "install", "--quiet", pkg],
            capture_output=True,
            text=True,
            timeout=240,
        )
    except FileNotFoundError:
        return f"未找到解释器：{settings.code_sandbox_python}"
    except subprocess.TimeoutExpired:
        return "安装超时（>240s）。"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    res = (out + ("\n" + err if err else "")).strip() or "（无输出）"
    return f"安装 {pkg} 结束（exit {proc.returncode}）：\n{res}"


TOOLS = [
    read_evidence,
    timeline_check,
    list_contradictions,
    search_case_law,
    cite_source,
    run_code,
    install_package,
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}

_BUILTIN = {
    "evidence": ["read_evidence", "timeline_check", "list_contradictions", "run_code"],
    "forensic": ["read_evidence", "timeline_check", "list_contradictions", "run_code"],
    "scene": ["read_evidence", "timeline_check", "list_contradictions", "run_code"],
    "law": [
        "read_evidence",
        "search_case_law",
        "list_contradictions",
        "cite_source",
        "run_code",
    ],
    "prosecutor": [
        "read_evidence",
        "search_case_law",
        "list_contradictions",
        "cite_source",
        "run_code",
    ],
    "defense": [
        "read_evidence",
        "search_case_law",
        "list_contradictions",
        "cite_source",
        "run_code",
    ],
    "psych": ["list_contradictions", "timeline_check", "run_code"],
    "judge": ["list_contradictions", "timeline_check", "run_code"],
}


def builtin_tool_names(role_key: str) -> list:
    return list(_BUILTIN.get(role_key, ["list_contradictions", "timeline_check"]))


def tools_for_role(role_key: str):
    """不同角色挂载不同工具；若 agent_config 覆写了工具则采用覆写。"""
    names = builtin_tool_names(role_key)
    try:
        from app.agents import agent_config

        cfg = agent_config.load().get(role_key, {})
        if cfg.get("tools") is not None:
            names = list(cfg["tools"])
    except Exception:
        pass
    return [TOOLS_BY_NAME[n] for n in names if n in TOOLS_BY_NAME]
