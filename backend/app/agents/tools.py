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
    import http.client
    import urllib.parse

    # 上游固定为 Bing 国内源，仅查询串动态；显式固定主机避免请求目标被间接改写
    path = "/search?q=" + urllib.parse.quote(query) + "&count=8"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    try:
        conn = http.client.HTTPSConnection("cn.bing.com", timeout=12)
        try:
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()
            if resp.status != 200:
                return f"联网检索失败（HTTP {resp.status}）。请依据卷宗与知识库继续分析。"
            html = resp.read().decode("utf-8", "ignore")
        finally:
            conn.close()
    except Exception as ex:  # noqa: BLE001
        return f"联网检索失败（网络不可达）：{str(ex)[:120]}。请依据卷宗与知识库继续分析。"
    chunks = html.split('<li class="b_algo"')[1:]
    items = []
    for ch in chunks:
        mh = re.search(r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', ch, re.S)
        if not mh:
            continue
        mp = re.search(r'<p[^>]*>(.*?)</p>', ch, re.S)
        items.append((mh.group(1), mh.group(2), mp.group(1) if mp else ""))
    out: List[str] = []
    nl = chr(10)
    for i, (href, title, snip) in enumerate(items[:5], 1):
        title_txt = re.sub(r"<[^>]+>", "", title).strip()
        snip = re.sub(r"<[^>]+>", "", snip).strip()
        out.append(f"{i}. {title_txt}" + nl + f"   {snip[:140]}" + nl + f"   来源: {href[:110]}")
    if not out:
        return f"联网检索「{query}」无结果。请依据卷宗与知识库继续分析。"
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
