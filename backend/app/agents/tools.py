from __future__ import annotations
import contextvars
import json
import os
import re
import subprocess
import time
from typing import Dict, List
from langchain_core.tools import tool
from app.config import settings

_IMG_EXT = (".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp")
_base_checked = False
_docker_ok: bool | None = None

# 沙箱静态命令黑名单正则缓存（按 deny 串粒度，避免每次编译）
_DENY_RE_CACHE: dict = {}


def _deny_pattern(deny: str):
    """把黑名单串（逗号分隔）编译为静态检查正则；空串返回 None（不拦截）。"""
    if deny not in _DENY_RE_CACHE:
        parts = []
        for item in (p.strip() for p in (deny or "").split(",")):
            if not item:
                continue
            parts.append(r"\b" + re.escape(item) + r"\b")
        _DENY_RE_CACHE[deny] = (
            re.compile("|".join(parts)) if parts else None
        )
    return _DENY_RE_CACHE[deny]


def check_denied(code: str) -> str | None:
    """静态命令白名单检查（M3.5）：命中黑名单命令返回命中项，否则返回 None。

    容器模式已有断网/资源隔离，此处作为第二道防线（subprocess 模式缺
    容器隔离尤其依赖它）：只拦明显的联网/进程/破坏性命令，正常数据统计
    与 matplotlib 绘图不受影响。
    """
    pat = _deny_pattern(settings.code_sandbox_deny_cmds)
    if pat is None:
        return None
    hit = pat.search(code or "")
    return hit.group(0) if hit else None

# 沙箱/pip 子进程不得继承敏感配置：专家生成的代码是任意代码，环境里的
# LLM 密钥、访问口令一旦可见即可被读取外传。新增敏感配置项时必须使用
# 以下前缀之一，或把变量名加进剥离逻辑（见 CONTRIBUTING「Secrets」）。
_SANDBOX_ENV_DROP_PREFIXES = ("LLM_", "ACCESS_")


def _sandbox_env(extra: Dict | None = None) -> Dict:
    """构造子进程环境：剥离敏感前缀，再叠加调用方需要的显式变量。"""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(_SANDBOX_ENV_DROP_PREFIXES)
    }
    if extra:
        env.update(extra)
    return env

# 使用 contextvars 而非全局变量存储当前案件，避免并发辩论时互相覆盖。
# 每个 asyncio Task 有独立上下文，activate_case 设置的值只在当前 Task 链中可见。
_active_case_var: contextvars.ContextVar[Dict] = contextvars.ContextVar(
    "active_case", default={}
)


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
                env=_sandbox_env(),
            )
        except Exception:
            pass


def activate_case(case: Dict) -> contextvars.Token:
    """设置当前辩论的案件上下文，返回 token 用于恢复。
    使用 contextvars 保证并发辩论互不干扰。"""
    return _active_case_var.set(dict(case or {}))


def _get_case() -> Dict:
    return _active_case_var.get()


@tool
def read_evidence(evidence_id: str) -> str:
    """读取指定物证/书证编号的详细内容。输入证据编号，如 'E-03'。"""
    items = _get_case().get("evidence", [])
    for e in items:
        if e.get("id") == evidence_id:
            return json.dumps(e, ensure_ascii=False)
    return f"未找到证据 {evidence_id}。现有证据编号：{', '.join(e.get('id', '') for e in items)}"


@tool
def timeline_check() -> str:
    """返回本案关键时间线，用于核对各专家推断是否矛盾。"""
    return json.dumps(_get_case().get("timeline", []), ensure_ascii=False, indent=2)


@tool
def list_contradictions() -> str:
    """列出当前已记录的矛盾点清单。"""
    return json.dumps(
        _get_case().get("contradictions", []), ensure_ascii=False, indent=2
    )


@tool
def search_case_law(keyword: str) -> str:
    """检索与关键词相关的法条或类案要旨。三级检索：本案卷宗法条 → 用户自定义知识库 → 内置法条库。输入法律关键词，如 '非法证据排除'。"""
    from app.legal.knowledge import search_knowledge
    parts: List[str] = []
    case = _get_case()
    laws = case.get("statutes", [])
    hits = [law for law in laws if keyword in (law.get("topic", "") + law.get("text", ""))]
    if hits:
        parts.append("【本案卷宗法条】\n" + json.dumps(hits, ensure_ascii=False, indent=2))
    kb = search_knowledge(keyword, limit=4)
    if kb:
        lines = "\n".join(
            f"- 《{e.get('category', '知识库')}》{e['title']}：{e['text'][:140]}"
            for e in kb
        )
        parts.append("【知识库检索结果】\n" + lines)
    if not parts:
        return f"卷宗与知识库中暂无与「{keyword}」直接相关的法条。可尝试其他关键词（如：证明标准、非法证据、保管链、三性）。"
    return "\n\n".join(parts)


@tool
def cite_source(fact: str) -> str:
    """要求为某事实标注依据。返回该事实应有的证据来源提示。"""
    return f"请为事实「{fact}」提供证据编号或法条依据，否则视为无依据推测。"


@tool
def web_search(query: str) -> str:
    """联网检索公开信息（法条更新、类案报道、公开事实核查）。输入检索词，返回前若干条结果的标题、摘要与链接。"""
    if not settings.web_search_enabled:
        return "联网搜索未启用（设置 → Agent 工程）。可依据卷宗与知识库作答。"
    from app.agents import search as _search

    items = _search.web_search(query)
    if not items:
        return f"联网检索「{query}」无结果。请依据卷宗与知识库继续分析。"
    nl = chr(10)
    out: List[str] = []
    for i, it in enumerate(items[:5], 1):
        out.append(
            f"{i}. {it['title']}" + nl + f"   {(it['snippet'] or '')[:140]}"
            + nl + f"   来源: {(it['url'] or '')[:110]}"
        )
    return f"联网检索「{query}」结果：" + nl + nl.join(out)


def _docker_available() -> bool:
    global _docker_ok
    if _docker_ok is None:
        import shutil

        _docker_ok = shutil.which("docker") is not None
        if _docker_ok:
            try:
                subprocess.run(
                    ["docker", "info", "--format", "ok"],
                    capture_output=True,
                    timeout=15,
                    check=True,
                )
            except Exception:
                _docker_ok = False
    return _docker_ok


def _docker_command(code: str, out_dir: str) -> list:
    """一次性容器执行：断网 + 内存/CPU/进程数上限；仅挂载产物目录，
    环境只注入 SANDBOX_OUT 与 matplotlib 后端，宿主变量一概不进入。"""
    return [
        "docker", "run", "--rm",
        "--network=none",
        "--memory=512m", "--cpus=1", "--pids-limit", "128",
        "-v", f"{out_dir}:/sandbox_out",
        "-e", "SANDBOX_OUT=/sandbox_out",
        "-e", "MPLBACKEND=Agg",
        settings.code_sandbox_docker_image,
        "python", "-I", "-c", code,
    ]


def _image_available() -> bool:
    """配置的镜像是否已在本地（缺镜像时 auto 应降级而非现场拉取拖慢辩论）。"""
    try:
        subprocess.run(
            ["docker", "image", "inspect", settings.code_sandbox_docker_image],
            capture_output=True,
            timeout=15,
            check=True,
        )
        return True
    except Exception:
        return False


def _effective_backend() -> str:
    """解析实际沙箱后端：docker | subprocess | unavailable | image-missing。"""
    backend = settings.code_sandbox_backend
    if backend == "subprocess":
        return "subprocess"
    if not _docker_available():
        return "unavailable" if backend == "docker" else "subprocess"
    if not _image_available():
        return "image-missing" if backend == "docker" else "subprocess"
    return "docker"


@tool
def run_code(code: str) -> str:
    """在受控沙箱中执行 Python 代码并返回标准输出与错误。用于对证据数据做统计、比对、时间线推算；也可生成图表（matplotlib，Agg 后端），保存到环境变量 SANDBOX_OUT 指向的目录，返回中会附带图片链接，将在笔录中渲染。

    安全说明：默认优先使用一次性 Docker 容器（断网、512MB 内存、1 核），
    无 Docker 或镜像未就绪时降级为本机 Python -I 隔离模式；两种模式均从
    环境剥离敏感配置（LLM_*/ACCESS_* 前缀）。容器模式无网络，请勿尝试联网。
    """
    if not settings.code_sandbox_enabled:
        return "代码沙箱未启用。请在「设置 → 运行环境」中开启「启用 Python 代码沙箱」。"
    denied = check_denied(code)
    if denied:
        return (
            f"沙箱命令黑名单命中（{denied}）：该操作被安全策略拒绝。"
            "沙箱不允许联网、拉起子进程或破坏性目录操作，仅限数据分析与图表生成；"
            "如需调整请编辑 CODE_SANDBOX_DENY_CMDS。"
        )
    eff = _effective_backend()
    if eff == "unavailable":
        return (
            "沙箱后端配置为 docker 但本机不可用：请安装并启动 Docker，"
            "或把 CODE_SANDBOX_BACKEND 改为 subprocess。"
        )
    if eff == "image-missing":
        return (
            f"镜像 {settings.code_sandbox_docker_image} 不存在：请先执行 "
            f"docker pull {settings.code_sandbox_docker_image}，或把 "
            "CODE_SANDBOX_BACKEND 改为 auto/subprocess。"
        )
    use_docker = eff == "docker"
    out_dir = settings.sandbox_out_dir
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    before = {f: os.path.getmtime(os.path.join(out_dir, f)) for f in os.listdir(out_dir)}
    if use_docker:
        cmd = _docker_command(code, out_dir)
        env = _sandbox_env()  # 容器内变量由 -e 显式注入，docker CLI 不需要宿主配置
    else:
        _ensure_base()
        cmd = [settings.code_sandbox_python, "-I", "-c", code]
        env = _sandbox_env({"SANDBOX_OUT": out_dir, "MPLBACKEND": "Agg"})
    try:
        proc = subprocess.run(
            cmd,
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
    # 本次新建或被覆盖写入（mtime 晚于调用开始）的图片都渲染；
    # 只认「新增」会导致固定文件名重复生成时丢失渲染。
    new_imgs = []
    for f in os.listdir(out_dir):
        if not f.lower().endswith(_IMG_EXT):
            continue
        if f not in before or os.path.getmtime(os.path.join(out_dir, f)) > t0:
            new_imgs.append(f)
    new_imgs = sorted(new_imgs)
    if new_imgs:
        body += "\n\n" + "\n".join(f"![{f}](/sandbox/{f})" for f in new_imgs)
    return body or "（无输出）"


@tool
def install_package(package: str) -> str:
    """安装额外的 Python 包到沙箱环境（需要联网），以便专家使用更多能力（如 scipy、openpyxl）。"""
    if not settings.code_sandbox_enabled:
        return "代码沙箱未启用。"
    if _effective_backend() != "subprocess":
        return (
            "沙箱运行于一次性容器：容器内安装不会保留。需要额外依赖时请自定义"
            " CODE_SANDBOX_DOCKER_IMAGE 镜像预置，或把沙箱后端切为 subprocess。"
        )
    pkg = (package or "").strip()
    if not pkg:
        return "请提供包名，例如 numpy、pandas、matplotlib。"
    # 基本的包名安全校验：只允许字母、数字、下划线、连字符、点
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", pkg):
        return f"包名格式不合法：{pkg}"
    try:
        proc = subprocess.run(
            [settings.code_sandbox_python, "-m", "pip", "install", "--quiet", pkg],
            capture_output=True,
            text=True,
            timeout=240,
            env=_sandbox_env(),
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
    web_search,
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
        "web_search",
        "list_contradictions",
        "cite_source",
        "run_code",
    ],
    "prosecutor": [
        "read_evidence",
        "search_case_law",
        "web_search",
        "list_contradictions",
        "cite_source",
        "run_code",
    ],
    "defense": [
        "read_evidence",
        "search_case_law",
        "web_search",
        "list_contradictions",
        "cite_source",
        "run_code",
    ],
    "psych": ["web_search", "list_contradictions", "timeline_check", "run_code"],
    "judge": ["list_contradictions", "timeline_check", "run_code"],
}


def builtin_tool_names(role_key: str) -> list:
    return list(_BUILTIN.get(role_key, ["list_contradictions", "timeline_check"]))


def tools_for_role(role_key: str):
    """不同角色挂载不同工具；若 agent_config 覆写了工具则采用覆写。
    最后合并该角色可见的 MCP 外部工具（P1-5），失败/未配置时自动为空。"""
    names = builtin_tool_names(role_key)
    try:
        from app.agents import agent_config
        out_cfg = agent_config.load().get(role_key, {})
        if out_cfg.get("tools") is not None:
            names = list(out_cfg["tools"])
    except Exception:
        pass
    tools = [TOOLS_BY_NAME[n] for n in names if n in TOOLS_BY_NAME]
    # MCP 外部工具：name 前缀 mcp_<server>_<tool>，避免与内置工具冲突
    try:
        from app.agents import mcp as mcp_mod
        mcp_tools = mcp_mod.mcp_tools_for_role(role_key)
        names = {t.name for t in tools}
        for t in mcp_tools:
            if getattr(t, "name", "") and t.name not in names:
                tools.append(t)
                names.add(t.name)
    except Exception:
        pass  # MCP 未配置/SDK 未装：不影响内置工具
    return tools


def all_tool_names() -> list:
    """全部可用工具名（内置 + MCP），供前端设置页展示。"""
    names = list(TOOLS_BY_NAME.keys())
    try:
        from app.agents import mcp as mcp_mod
        if mcp_mod.sdk_available() and mcp_mod.configured_servers():
            for t in mcp_mod.mcp_tools_for_role(""):
                if getattr(t, "name", "") and t.name not in names:
                    names.append(t.name)
    except Exception:
        pass
    return names


# ------------------------- 工具级指标（P2-3） -------------------------
# 每工具 调用数 / 成功 / 失败 / 累加耗时，供 /api/admin/usage 与前端工具
# 面板展示成功率、平均耗时与失败工具清单（对标 LangSmith 工具级观测）。
TOOL_STATS: dict = {}


def tool_stats_record(name: str, ok: bool, ms: float) -> None:
    """记录一次工具调用的结果与耗时（进程内聚合）。"""
    s = TOOL_STATS.setdefault(
        name, {"calls": 0, "ok": 0, "fail": 0, "ms": 0.0, "last_err": ""}
    )
    s["calls"] += 1
    s["ms"] += ms
    if ok:
        s["ok"] += 1
    else:
        s["fail"] += 1
        s["last_err"] = ""


def tool_stats_record_error(name: str, err: str) -> None:
    """记录一次失败的工具名与最近错误（重试期间累计的失败也归入统计）。"""
    s = TOOL_STATS.setdefault(
        name, {"calls": 0, "ok": 0, "fail": 0, "ms": 0.0, "last_err": ""}
    )
    s["fail"] += 1
    s["last_err"] = str(err)[:200]


def tool_stats_snapshot() -> dict:
    """快照：每工具 调用/成功/失败/成功率/平均耗时；整体成功率与最慢工具 TOP。"""
    out = {}
    for name, s in TOOL_STATS.items():
        calls = max(1, int(s.get("calls") or 0))
        ok = int(s.get("ok") or 0)
        out[name] = {
            "calls": calls,
            "ok": ok,
            "fail": int(s.get("fail") or 0),
            "success_rate": round(ok / calls, 3),
            "avg_ms": round(float(s.get("ms") or 0) / calls, 1),
            "last_err": str(s.get("last_err") or "")[:120],
        }
    total_ok = sum(s.get("ok", 0) for s in TOOL_STATS.values())
    total = sum(s.get("calls", 0) for s in TOOL_STATS.values())
    slowest = max(out.items(), key=lambda kv: kv[1]["avg_ms"], default=None)
    return {
        "tools": out,
        "total_calls": total,
        "overall_success_rate": round(total_ok / total, 3) if total else 0.0,
        "slowest": {"tool": slowest[0], "avg_ms": slowest[1]["avg_ms"]} if slowest else None,
    }
