# -*- coding: utf-8 -*-
"""应用外壳（app-shell.js）与静态资源一致性测试。

背景：外壳重构（左侧多级目录 + 三步卡片 + 侧栏抽屉）的交互此前只能靠人工点。
本模块把关键契约固化成可回归的断言，覆盖三类容易被静默破坏的问题：

  1. 契约破坏：switchTab() 依赖全局 .tab / .tabpane 选择器联动，
     目录叶子必须同时具备 class="tab" 与 data-tab，否则点了不切换。
  2. 引用断裂：index.html 的内联处理器、JS 里 $("id") 的引用必须存在。
  3. 冷色调基线：主题色不得回退到暖色区（产品要求默认冷色亮色）。

不依赖浏览器：纯静态解析，可在任何 CI 上跑（无 playwright 也能通过）。
"""
from __future__ import annotations

import colorsys
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
ASSETS = STATIC / "assets"


# --------------------------------------------------------------------------
# 读取工具
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def html() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def shell_js() -> str:
    return (ASSETS / "app-shell.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return (ASSETS / "app.css").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def all_js() -> str:
    return "".join(
        (ASSETS / n).read_text(encoding="utf-8")
        for n in ("app-core.js", "app-ui.js", "app-shell.js")
    )


def _hex_to_hsl(hx: str):
    h = hx.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    return hh * 360, ss, ll


# --------------------------------------------------------------------------
# 1. 外壳脚本存在且被正确加载
# --------------------------------------------------------------------------
def test_shell_script_exists():
    assert (ASSETS / "app-shell.js").exists(), "app-shell.js 缺失"


def test_shell_script_loaded_after_core(html: str):
    """app-shell.js 依赖 core/ui 定义的全局函数，必须在其后加载。"""
    core = html.index("/static/assets/app-core.js")
    ui = html.index("/static/assets/app-ui.js")
    shell = html.index("/static/assets/app-shell.js")
    assert core < ui < shell, "app-shell.js 加载顺序应在 app-core/app-ui 之后"


def test_shell_script_in_service_worker_precache():
    """新增脚本必须进 SW 预缓存清单，否则离线时外壳交互失效。"""
    sw = (ASSETS / "sw.js").read_text(encoding="utf-8")
    assert "app-shell.js" in sw, "sw.js 预缓存清单缺少 app-shell.js"


# --------------------------------------------------------------------------
# 2. switchTab 契约：目录叶子 -> 面板联动
# --------------------------------------------------------------------------
def test_nav_leaves_carry_tab_class(html: str):
    """映射到设置面板的目录叶子必须带 class="tab" + data-tab。

    switchTab() 用 querySelectorAll(".tab") 做高亮联动，缺 class 会导致
    点击后目录不亮、用户以为没反应。
    """
    bad = re.findall(r'class="navleaf" data-tab="([a-z]+)"', html)
    assert not bad, f"这些叶子缺 class=\"tab\"，switchTab 不会高亮：{bad}"


def test_every_tabpane_reachable_from_navtree(html: str, shell_js: str):
    """每个 .tabpane 都应能由某个 openPane 叶子到达，避免"死面板"。"""
    panes = set(re.findall(r'class="tabpane[^"]*" id="tab-([a-z]+)"', html))
    openable = set(re.findall(r"openPane\('([a-z]+)'", html))
    orphan = panes - openable
    assert not orphan, f"以下面板无导航入口：{sorted(orphan)}"


def test_openpane_defined(html: str, shell_js: str):
    """目录叶子的 onclick 处理器必须在 app-shell.js 中定义。"""
    handlers = set(re.findall(r'onclick="(openPane|toggleNavGroup|openWorkspace)\b', html))
    for fn in handlers:
        assert re.search(rf"window\.{fn}\s*=", shell_js), f"{fn} 未在 app-shell.js 导出"


def test_openpane_calls_switchtab(shell_js: str):
    """openPane 必须桥接 switchTab，否则只开设置抽屉不切面板。"""
    body = re.search(r"window\.openPane\s*=\s*function.*?\n  \};", shell_js, re.S)
    assert body, "未找到 openPane 定义"
    assert "switchTab(" in body.group(0), "openPane 未调用 switchTab"
    assert "openSettings(" in body.group(0), "openPane 未调用 openSettings"


def test_switchtab_uses_global_tab_selectors():
    """switchTab 的联动选择器是 .tab / .tabpane —— 改动这里会静默破坏目录高亮。"""
    ui = (ASSETS / "app-ui.js").read_text(encoding="utf-8")
    m = re.search(r"function switchTab\(name\)\{(.*?)\}\s*$", ui, re.M | re.S)
    assert m, "未找到 switchTab"
    assert 'querySelectorAll(".tab")' in m.group(1)
    assert 'querySelectorAll(".tabpane")' in m.group(1)


# --------------------------------------------------------------------------
# 3. 引用完整性：内联处理器 / DOM id
# --------------------------------------------------------------------------
def test_inline_handlers_are_defined(html: str, all_js: str):
    """index.html 的内联事件处理器都必须有定义（否则点击静默失败）。"""
    handlers = set(re.findall(r'on\w+="([a-zA-Z_$][\w$]*)\s*\(', html))
    # 内联表达式里允许出现的语言内建/关键字
    builtin = {"if", "return", "$"}
    missing = [
        f for f in sorted(handlers)
        if f not in builtin
        and not re.search(rf"function\s+{re.escape(f)}\s*\(", all_js)
        and not re.search(rf"window\.{re.escape(f)}\s*=", all_js)
    ]
    assert not missing, f"以下内联处理器无定义：{missing}"


def test_dollar_id_references_resolvable(html: str, all_js: str):
    """JS 里 $("x") 引用的 id 必须存在于 HTML 或由 JS 动态生成。

    动态生成的（如弹窗内注入的 nsProg）在 JS 字符串里有 id="x"，一并计入。
    """
    referenced = set(re.findall(r'\$\("([\w\-]+)"\)', all_js))
    in_html = set(re.findall(r'\bid="([^"]+)"', html))
    # 动态注入：JS 模板串里的 id="x"
    in_js = set(re.findall(r'id=\\?"([\w\-]+)\\?"', all_js))
    unresolved = referenced - in_html - in_js
    assert not unresolved, f"以下 id 引用无法解析：{sorted(unresolved)}"


def test_css_classes_used_by_html_are_defined(html: str, css: str):
    """HTML 用到的类名应在 CSS 有定义（漏写会导致折叠等样式静默失效）。

    历史问题：CSS 写 .navlabel 而 HTML 用 .nlabel，折叠时文字不隐藏。
    """
    used = set()
    for m in re.findall(r'class="([^"]+)"', html):
        used.update(m.split())
    defined = set(re.findall(r"\.([a-zA-Z][\w\-]*)", css))
    # 少量语义占位/第三方钩子类不在 CSS 中定义属正常
    allowed = {"hidden", "tab", "md", "n", "st-", "main", "qa", "on"}
    missing = {c for c in used if c not in defined and c not in allowed
               and not c.startswith("st-")}
    assert not missing, f"HTML 使用但 CSS 未定义的类名：{sorted(missing)}"


# --------------------------------------------------------------------------
# 4. 冷色调基线
# --------------------------------------------------------------------------
COLD_MIN, COLD_MAX = 100, 290   # 冷区色相区间（青→蓝→靛→紫）
NEUTRAL_SAT = 0.12              # 低于此饱和度视为中性，不计冷暖


def _warm_colors(text: str):
    """返回文本中偏离冷区的有色色值。"""
    out = []
    for hx in set(re.findall(r"#[0-9a-fA-F]{6}", text)):
        hue, sat, _ = _hex_to_hsl(hx)
        if sat >= NEUTRAL_SAT and not (COLD_MIN <= hue < COLD_MAX):
            out.append((hx, round(hue)))
    return sorted(out, key=lambda x: x[1])


def test_app_css_is_cold_toned(css: str):
    """主样式表必须保持冷色调（产品要求：默认冷色）。"""
    warm = _warm_colors(css)
    assert not warm, f"app.css 出现暖色：{warm}"


def test_frontend_scripts_are_cold_toned(all_js: str):
    """前端脚本内联色值（报告模板 / SVG 时间线等）同样需为冷色。"""
    warm = _warm_colors(all_js)
    assert not warm, f"前端脚本出现暖色：{warm}"


def test_flow_page_is_cold_toned():
    warm = _warm_colors((STATIC / "flow.html").read_text(encoding="utf-8"))
    assert not warm, f"flow.html 出现暖色：{warm}"


def test_logo_is_cold_toned():
    warm = _warm_colors((ASSETS / "logo.svg").read_text(encoding="utf-8"))
    assert not warm, f"logo.svg 出现暖色：{warm}"


def test_role_palette_is_cold_toned():
    """角色色板（后端定义，前端渲染头像）必须落在冷区。"""
    roles = (Path(__file__).resolve().parent.parent / "app" / "agents" / "roles.py")
    warm = _warm_colors(roles.read_text(encoding="utf-8"))
    assert not warm, f"角色色板出现暖色：{warm}"


def test_theme_defaults_to_light():
    """产品基线：默认亮色。仅在用户显式选择过深色时才覆盖。"""
    ui = (ASSETS / "app-ui.js").read_text(encoding="utf-8")
    assert 'localStorage.getItem("vai_theme") || "light"' in ui, \
        "主题读取的默认值应为 light"
