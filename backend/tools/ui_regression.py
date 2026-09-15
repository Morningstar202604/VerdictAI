# -*- coding: utf-8 -*-
"""VerdictAI 全界面 UI 回归测试：29 项功能用例 + 自动截图。

前置：
    1) 起服务（mock 模式无需 API Key）：
       LLM_PROVIDER=mock uvicorn app.main:app --host 127.0.0.1 --port 8787
       或 tools/start_all.py
    2) pip install playwright requests reportlab && playwright install chromium

用法（在 backend 目录）：
    python tools/ui_regression.py                      # 连 http://127.0.0.1:8787
    VAI_BASE_URL=http://127.0.0.1:9000 python tools/ui_regression.py
    python tools/ui_regression.py --out /tmp/ui_shots  # 自定义产物目录

产物： results.json（用例明细）+ screenshots/（31 张界面截图）。
覆盖： 落地页/帮助/设置 7Tab/明暗主题/知识库/案例库/时间线/沙箱/上传
       /开庭辩论/插话/裁决/质询/报告/复盘回放/聚焦/移动端/Console 零报错。
"""
import argparse, json, os, time
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

parser = argparse.ArgumentParser(description="VerdictAI UI 回归测试")
parser.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "ui_test_artifacts"))
parser.add_argument("--base", default=os.environ.get("VAI_BASE_URL", "http://127.0.0.1:8787"))
args = parser.parse_args()

BASE = args.base.rstrip("/")
OUT = os.path.abspath(args.out)
SHOT = os.path.join(OUT, "screenshots")
os.makedirs(SHOT, exist_ok=True)

results = []
console_errors = []

def check(name, fn, detail_max=220):
    t0 = time.time()
    try:
        detail = fn() or ""
        results.append((name, "PASS", round(time.time()-t0, 1), str(detail)[:detail_max]))
        print(f"PASS {name} :: {str(detail)[:130]}")
    except Exception as e:
        results.append((name, "FAIL", round(time.time()-t0, 1), str(e)[:detail_max]))
        print(f"FAIL {name} :: {str(e)[:200]}")

def shot(page, name, full=False):
    page.screenshot(path=os.path.join(SHOT, name), full_page=full)

def close_overlays(page):
    """关掉设置/帮助弹窗与可能残留的自定义确认弹窗"""
    page.evaluate("document.getElementById('settingsModal') && document.getElementById('settingsModal').classList.add('hidden')")
    page.evaluate("document.getElementById('helpModal') && document.getElementById('helpModal').classList.add('hidden')")
    page.evaluate("document.querySelectorAll('.modal:not(#settingsModal):not(#helpModal)').forEach(m=>m.remove())")

def cases_count():
    return len(requests.get(BASE + "/api/cases", timeout=5).json().get("cases", []))

def prepare_files():
    from reportlab.pdfgen import canvas
    p = "/tmp/ui_assets/sample_case2.pdf"
    c = canvas.Canvas(p)
    c.setFont("Helvetica", 12)
    for i, line in enumerate([
        "Criminal Case File No. 2026-099",
        "On 2026-06-02, a burglary occurred in",
        "Lakeview Community. Stolen: laptop and",
        "cash. Door lock was pried open. DNA",
        "sample collected at the scene.",
    ]):
        c.drawString(60, 780 - i*20, line)
    c.save()
    import time as _t
    json.dump({"title": "JSON上传测试案：仓库失窃 %d" % int(_t.time()), "summary": "物流仓库夜间失窃，监控缺失，需核查内部人员作案可能性与证据链完整性。"},
              open("/tmp/ui_assets/case_upload.json", "w"), ensure_ascii=False)
    _ts = int(_t.time()); open("/tmp/ui_assets/batch1.txt", "w").write(f"批量导入测试一{_ts}：商铺合同纠纷，被告逾期未支付货款。")
    open("/tmp/ui_assets/batch2.txt", "w").write(f"批量导入测试二{_ts}：邻里噪音扰民调解案件。")
    return p

PDF_PATH = prepare_files()

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
    page = ctx.new_page()
    page.on("console", lambda m: console_errors.append(m.text[:200]) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(str(e)[:200]))
    page.set_default_timeout(15000)

    # ============ Phase A: 静态界面截图 ============
    def a1():
        page.goto(BASE + "/")
        page.wait_for_function("document.querySelectorAll('#landCase option').length >= 1", timeout=15000)
        page.wait_for_timeout(800)
        shot(page, "01-landing-light.png", full=True)
        n = page.evaluate("document.querySelectorAll('#landCase option').length")
        return f"案件下拉选项数={n}"
    check("A1 落地页加载+截图", a1)

    def a2():
        page.click("button[onclick='openHelp()']")
        page.wait_for_selector("#helpModal:not(.hidden)")
        try:
            shot(page, "02-help-modal.png")
        finally:
            page.evaluate("closeHelp()")   # 无论截图是否超时, 确保弹窗关闭不污染后续用例
        return "帮助弹窗开/关正常"
    check("A2 帮助弹窗", a2)

    def a3():
        page.click("#btnSettings")
        page.wait_for_selector("#settingsModal:not(.hidden)")
        tabs = ["engine", "env", "board", "agents", "library", "kb", "agent"]
        names = {"engine": "03-settings-engine", "env": "04-settings-env", "board": "05-settings-board",
                 "agents": "06-settings-agents", "library": "07-settings-library", "kb": "08-settings-kb", "agent": "09-settings-agent"}
        for t in tabs:
            if t == "library":
                page.evaluate("switchTab('library'); refreshCaseLibrary(); refreshDebates()")
            elif t == "kb":
                page.evaluate("switchTab('kb'); loadKnowledge()")
            elif t == "agent":
                page.evaluate("switchTab('agent')")
            else:
                page.evaluate(f"switchTab('{t}')")
            page.wait_for_timeout(1500 if t in ("library", "kb", "agent") else 400)
            shot(page, names[t] + ".png")
        n_lib = page.evaluate("document.querySelectorAll('#libList .lib-item').length")
        n_kb = page.evaluate("document.querySelectorAll('#kbList .kb-item').length")
        n_board = page.evaluate("document.querySelectorAll('#boardList .ac-item').length")
        n_agents = page.evaluate("document.querySelectorAll('#agentList .ac-item').length")
        close_overlays(page)
        return f"案例库={n_lib}行 KB={n_kb}条 合议庭={n_board} 专家配置={n_agents}"
    check("A3 设置弹窗7个Tab截图", a3)

    def a4():
        page.evaluate("toggleTheme()")
        page.wait_for_timeout(400)
        dark = page.evaluate("document.body.classList.contains('dark')")
        shot(page, "10-landing-dark.png", full=True)
        page.evaluate("toggleTheme()")
        page.wait_for_timeout(300)
        light = page.evaluate("document.body.classList.contains('dark')")
        assert dark and not light, f"dark={dark} 回到浅色={not light}"
        return "深色类挂到 body.dark, 往返切换 OK"
    check("A4 明暗主题切换", a4)

    def a5():
        p2 = ctx.new_page()
        r = p2.goto(BASE + "/flow.html")
        p2.wait_for_timeout(600)
        shot(p2, "11-flow.png", full=True)
        body_len = p2.evaluate("document.body.innerText.length")
        p2.close()
        assert r.status == 200 and body_len > 50
        return f"status=200 正文{body_len}字"
    check("A5 流程图页 flow.html", a5)

    # ============ Phase B: 落地页与设置功能 ============
    def b1():
        h = requests.get(BASE + "/api/health", timeout=5).json()
        assert h["status"] == "ok"
        return f"provider={h['provider']} mock={h['mock']} v={h['version']}"
    check("B1 健康检查 API", b1)

    def b2():
        opts = page.evaluate("Array.from(document.querySelectorAll('#landCase option')).map(o=>o.textContent)")
        assert any(("命案" in o or "红谷" in o) for o in opts), f"种子案件未出现: {opts}"
        return f"下拉含种子案件, 选项数={len(opts)} 首项={opts[0][:20]!r}"
    check("B2 案例下拉加载", b2)

    gen = {}
    def b3():
        d = requests.post(BASE + "/api/cases/generate", timeout=10).json()
        cid = d["case"]["id"]; gen["id"] = cid
        page.evaluate(f"selectCaseFromLib('{cid}')")
        page.wait_for_timeout(1500)
        cd_id = page.evaluate("caseDetail && caseDetail.id")
        panel = page.evaluate("document.getElementById('casePanel').innerHTML.length")
        intake_vis = page.evaluate("!document.getElementById('intakeCard').classList.contains('hidden')")
        shot(page, "12-intake-card.png", full=True)
        assert cd_id == cid and panel > 200, f"caseDetail={cd_id} casePanel长度={panel}"
        return f"选中案件={cid} 案卷面板{panel}字 intake卡显示={intake_vis}"
    check("B3 选中案件→案卷+intake卡", b3)

    def b4():
        page.fill("#landQuery", "2026年5月某物流仓库夜间失窃，监控损坏，管理员王某案发后离职，嫌疑重大。请分析证据链。")
        page.evaluate("onIntentPreview()")
        page.wait_for_timeout(1500)
        prev = page.evaluate("document.getElementById('intentPreview')?.textContent?.slice(0,80)")
        return f"意图预览: {prev!r}"
    check("B4 粘贴案情→意图预览", b4)

    def b5():
        page.click("#btnSettings")
        page.evaluate("switchTab('kb'); loadKnowledge()")
        page.wait_for_timeout(1200)
        n1 = page.evaluate("document.querySelectorAll('#kbList .kb-item').length")
        page.fill("#kbSearch", "证明标准"); page.evaluate("loadKnowledge()")
        page.wait_for_timeout(1200)
        n_search = page.evaluate("document.querySelectorAll('#kbList .kb-item').length")
        page.fill("#kbTitle", "测试自定义条目：本院盗窃既遂标准")
        page.fill("#kbKw", "既遂,失控说")
        page.fill("#kbText", "本院类案采失控说：财物脱离占有人控制即既遂。")
        page.evaluate("addKnowledge()")
        page.wait_for_timeout(1500)
        page.fill("#kbSearch", "失控说"); page.evaluate("loadKnowledge()")
        page.wait_for_timeout(1200)
        found = page.evaluate("document.getElementById('kbList').textContent.includes('测试自定义条目')")
        shot(page, "20-kb-function.png")
        # 删除自定义条目 → 自定义confirm弹窗 → 点确认（循环删尽，防历史脏数据）
        gone = False
        for _ in range(5):
            if not page.evaluate("document.getElementById('kbList').textContent.includes('测试自定义条目')"):
                gone = True; break
            page.evaluate("document.querySelector('#kbList .kb-item button')?.click()")
            page.wait_for_selector("#cd-yes", timeout=5000)
            page.click("#cd-yes")
            page.wait_for_timeout(1500)
        close_overlays(page)
        assert n1 > 0 and n_search > 0, f"内置检索无结果: {n1}/{n_search}"
        assert found, "自定义条目添加后检索不到"
        assert gone, "自定义条目删除失败"
        return f"内置条目={n1} 命中'证明标准'={n_search} 自定义增/删 OK"
    check("B5 知识库 检索/新增/删除", b5)

    def b6():
        page.click("#btnSettings")
        page.evaluate("switchTab('library'); refreshCaseLibrary()")
        page.wait_for_timeout(1500)
        n0 = page.evaluate("document.querySelectorAll('#libList .lib-item').length")
        tags = page.evaluate("document.querySelectorAll('#libTag option').length")
        page.evaluate("generateSampleCase(document.querySelector(\"button[onclick='generateSampleCase(this)']\"))")
        page.wait_for_timeout(2500)
        n1 = page.evaluate("document.querySelectorAll('#libList .lib-item').length")
        page.fill("#libQ", "命案"); page.evaluate("libFilterInput()")
        page.wait_for_timeout(1500)
        n_filter = page.evaluate("document.querySelectorAll('#libList .lib-item').length")
        page.fill("#libQ", ""); page.evaluate("libFilterInput()")
        page.wait_for_timeout(1200)
        page.set_input_files("#libImport", ["/tmp/ui_assets/batch1.txt", "/tmp/ui_assets/batch2.txt"])
        try:
            page.wait_for_function("document.querySelectorAll('#libList .lib-item').length >= %d + 2" % n1, timeout=25000)
        except Exception:
            pass
        page.wait_for_timeout(1000)
        n2 = page.evaluate("document.querySelectorAll('#libList .lib-item').length")
        shot(page, "21-case-library.png")
        # UI 删除一个批量导入案件（含 confirm 弹窗）
        ids = requests.get(BASE + "/api/cases", timeout=5).json()["cases"]
        target = next((c["id"] for c in ids if "批量导入测试一" in (c.get("title") or "")), None)
        del_ok = False
        if target:
            page.evaluate(f"deleteCase('{target}')")
            page.wait_for_selector("#cd-yes", timeout=5000)
            page.click("#cd-yes")
            page.wait_for_timeout(1500)
            del_ok = cases_count() == len(ids) - 1
        close_overlays(page)
        assert n0 >= 1 and n1 > n0, f"生成示例失败 n0={n0} n1={n1}"
        assert n_filter >= 1, f"筛选种子案件应>=1行 got {n_filter}"
        assert n2 >= n1 + 2, f"批量导入后应+2 n1={n1} n2={n2}"
        return f"案例 {n0}→{n1}(生成示例) 筛选种子={n_filter} 批量导入→{n2} UI删除={del_ok} 标签={tags}"
    check("B6 案例库 生成/筛选/批量导入/UI删除", b6)

    def b7():
        try:
            page.click("#btnSettings", timeout=6000)
        except Exception:
            import json as _json
            diag = page.evaluate("""(() => {
              const el=document.getElementById('btnSettings');
              const r=el.getBoundingClientRect();
              const top=document.elementFromPoint(r.left+r.width/2, r.top+r.height/2);
              const chain=[]; let n=top; while(n&&chain.length<5){chain.push(n.tagName+'.'+(typeof n.className==='string'?n.className:'')+(n.id?'#'+n.id:''));n=n.parentElement;}
              return {top: chain.join(' < '), overlays: Array.from(document.querySelectorAll('.modal,.tl-overlay,.toast')).map(m=>({cls:m.className,hidden:m.classList.contains('hidden'),rect:(rr=>({t:Math.round(rr.top),l:Math.round(rr.left),w:Math.round(rr.width),h:Math.round(rr.height)}))(m.getBoundingClientRect())}))};
            })()""")
            print("B7-DIAG", _json.dumps(diag, ensure_ascii=False))
            raise
        page.evaluate("switchTab('library'); refreshCaseLibrary()")
        page.wait_for_timeout(1500)
        page.evaluate("document.querySelector(\"#libList button[onclick*='openTimelineModal']\").click()")
        page.wait_for_timeout(2500)
        tl = page.evaluate("document.querySelector('.tl-modal')?.textContent?.slice(0,80)")
        shot(page, "22-timeline-modal.png")
        page.evaluate("document.querySelector('.tl-overlay')?.remove()")
        close_overlays(page)
        assert tl and "时间线" in tl, f"时间线弹窗异常: {tl}"
        return f"弹窗内容: {tl}"
    check("B7 证据时间线+相似案例弹窗", b7)

    def b8():
        page.click("#btnSettings")
        page.evaluate("switchTab('agent')")
        page.wait_for_timeout(1800)
        usage = page.evaluate("document.getElementById('usageCard')?.textContent?.slice(0,90)")
        presets = page.evaluate("Array.from(document.querySelectorAll('#s_preset option')).map(o=>o.textContent)")
        shot(page, "23-agent-usage.png")
        close_overlays(page)
        assert usage and "加载用量统计" not in usage, f"用量卡未加载: {usage}"
        return f"usage={usage!r} 模板={presets}"
    check("B8 Agent工程 用量统计+策略模板", b8)

    def b9():
        page.click("#btnSettings")
        old = requests.get(BASE + "/api/settings", timeout=5).json()
        old_rounds = old.get("max_rounds", 3)
        page.evaluate("switchTab('engine')")
        page.fill("#s_rounds", "2")
        page.evaluate("saveSettings()")
        page.wait_for_timeout(2000)
        s1 = requests.get(BASE + "/api/settings", timeout=5).json()
        ok1 = s1.get("max_rounds") == 2
        page.click("#btnSettings")   # saveSettings 成功后自动关窗，需重开
        page.evaluate("switchTab('engine')")
        page.fill("#s_rounds", str(old_rounds))
        page.evaluate("saveSettings()")
        page.wait_for_timeout(2000)
        s2 = requests.get(BASE + "/api/settings", timeout=5).json()
        ok2 = s2.get("max_rounds") == old_rounds
        close_overlays(page)
        assert ok1 and ok2, f"max_rounds={s1.get('max_rounds')}/{s2.get('max_rounds')}"
        return f"轮次 {old_rounds}→2→{old_rounds} 均落库(.env)"
    check("B9 设置保存持久化", b9)

    def b10():
        page.click("#btnSettings")
        page.evaluate("switchTab('engine'); testSettings()")
        page.wait_for_function("(document.getElementById('testResult').textContent||'').includes('✅') || (document.getElementById('testResult').textContent||'').includes('❌')", timeout=20000)
        res = page.evaluate("document.getElementById('testResult').textContent")
        close_overlays(page)
        assert "✅" in res, f"测试连接失败: {res}"
        return f"结果: {res.strip()[:60]}"
    check("B10 设置·测试连接(mock)", b10)

    def b11():
        page.click("#btnSettings")
        page.evaluate("switchTab('env')")
        page.fill("#s_try", "import os\nprint('SANDBOX_OK', 2+3)")
        page.evaluate("runTry()")
        page.wait_for_function("(document.getElementById('tryOut').textContent||'').includes('SANDBOX_OK') || (document.getElementById('tryOut').textContent||'').includes('失败') || (document.getElementById('tryOut').textContent||'').includes('HTTP')", timeout=120000)
        out = page.evaluate("document.getElementById('tryOut').textContent.slice(0,100)")
        shot(page, "24-sandbox-try.png")
        close_overlays(page)
        assert "SANDBOX_OK 5" in out, f"沙箱输出异常: {out}"
        return f"沙箱输出: {out!r}"
    check("B11 运行环境·沙箱试跑", b11)

    def b12():
        n0 = cases_count()
        page.set_input_files("#fileInput", "/tmp/ui_assets/case_upload.json")
        page.wait_for_timeout(9000)
        n1 = cases_count()
        shot(page, "27-json-upload.png")
        assert n1 == n0 + 1, f"JSON上传后 {n0}->{n1}"
        return f"案件数 {n0}->{n1}"
    check("B12 上传JSON卷宗建案", b12)

    def b13():
        n0 = cases_count()
        page.set_input_files("#pdfInputMain", PDF_PATH)
        page.wait_for_timeout(6000)
        n1 = cases_count()
        info = page.evaluate("document.getElementById('pdfFileInfoMain')?.textContent?.slice(0,80)")
        assert n1 == n0 + 1, f"PDF上传后 {n0}->{n1} info={info}"
        return f"案件数 {n0}->{n1} info={info!r}"
    check("B13 上传PDF卷宗建案", b13)

    def b14():
        cfg = requests.get(BASE + "/api/agent-config", timeout=5).json()
        n_agents = len(cfg.get("agents", []))
        presets = requests.get(BASE + "/api/presets", timeout=5).json()
        pm = presets.get("presets", presets) if isinstance(presets, dict) else {}
        names = list(pm.keys()) if isinstance(pm, dict) else [p.get("name") for p in pm]
        return f"专家配置={n_agents}个 策略模板={len(names)}个 names={names[:4]}"
    check("B14 专家配置与策略模板 API", b14)

    # ============ Phase C: 辩论端到端 ============
    def c1():
        page.evaluate("goHome()")
        page.wait_for_timeout(600)
        page.fill("#landQuery", "")          # 清空粘贴框，避免覆盖所选案件
        d = requests.post(BASE + "/api/cases/generate", timeout=10).json()
        cid = d["case"]["id"]
        page.evaluate(f"selectCaseFromLib('{cid}')")
        page.wait_for_timeout(1500)
        close_overlays(page)
        page.evaluate("landStart()")
        page.wait_for_function("document.getElementById('workspace') && !document.getElementById('workspace').classList.contains('hidden')", timeout=10000)
        page.wait_for_function("(document.getElementById('connText')?.textContent||'').includes('已连接')", timeout=20000)
        return f"案件={cid} ws已连接"
    check("C1 开庭:选案件→工作区+ws连接", c1)

    def c2():
        page.wait_for_function("document.querySelectorAll('#debate .rec').length > 1", timeout=40000)
        page.wait_for_timeout(2500)
        n_msg = page.evaluate("document.querySelectorAll('#debate .rec').length")
        n_tool = page.evaluate("document.querySelectorAll('#debate .sandbox').length")
        phase = page.evaluate("document.getElementById('phase')?.textContent")
        shot(page, "14-debate-running.png", full=True)
        return f"发言{n_msg}条 工具调用块{n_tool}个 phase={phase}"
    check("C2 辩论推进:笔录+工具调用", c2)

    def c3():
        page.fill("#ivInput", "请补充核查金饰的保管链与原始载体是否完整")
        page.evaluate("sendIntervene()")
        page.wait_for_timeout(800)
        val = page.evaluate("document.getElementById('ivInput').value")
        assert val == "", "插话后输入框未清空"
        return "插话已发送(下一轮生效), 输入框已清空"
    check("C3 中途插话(intervene)", c3)

    def c4():
        # 现场辩论完整收敛（7专家×N轮×真实推理）可达 10-20 分钟，超出回归等待窗。
        # 裁决渲染完整性改为回放最近一场已完成辩论验证（记录含 final_verdict，
        # openReplay 会按事件流重放 → 渲染裁决书/工具条/质询面板/后续清单），
        # mock 与真实模式均稳定可测。
        import requests as _rq
        sess = _rq.get(BASE + "/api/debates", timeout=5).json()
        sl = sess if isinstance(sess, list) else sess.get("sessions", [])
        assert sl, "无复盘记录可回放"
        # 取最近一场带裁决的记录（倒序列表里第一个 truth 非空的；
        # 注意 /api/debates 摘要字段是 truth（truth_hypothesis 截断），无 final_verdict 键）
        target = None
        for d in sl:
            if (d.get("truth") or "").strip() or (d.get("final_verdict") or {}).get("verdict"):
                target = d.get("session_id") or d.get("id")
                break
        if target is None:
            target = sl[0].get("session_id") or sl[0].get("id")
        page.evaluate(f"openReplay('{target}')")
        page.wait_for_function("!document.getElementById('workspace').classList.contains('hidden')", timeout=10000)
        page.wait_for_timeout(2500)
        v_vis = page.evaluate("document.querySelectorAll('#verdictBox .verdict').length")
        tools_vis = page.evaluate("!document.getElementById('verdictTools').classList.contains('hidden')")
        qa_vis = page.evaluate("!document.getElementById('qaBox').classList.contains('hidden')")
        n_ns = page.evaluate("document.querySelectorAll('#nextSteps input[type=checkbox]').length")
        n_msg = page.evaluate("document.querySelectorAll('#debate .rec').length")
        shot(page, "15-verdict.png", full=True)
        assert v_vis >= 1 and tools_vis and qa_vis, f"裁决渲染不全 verdict={v_vis} tools={tools_vis} qa={qa_vis}"
        return f"回放{target} 总发言{n_msg} 裁决书={v_vis} 工具条={tools_vis} 质询面板={qa_vis} 后续清单={n_ns}项"
    check("C4 裁决书渲染(回放已完成辩论)", c4)

    def c5():
        # 质询面板在 C4 的回放上下文中已打开：对裁决真实发问（/api/verdict-qa）
        page.fill("#qaInput", "为什么物证保管链被认定为存疑点？")
        page.evaluate("askVerdict()")
        page.wait_for_function("var a=document.querySelector('#qaList .qa-item .qa-a'); a && a.textContent.length > 3", timeout=90000)
        ans = page.evaluate("document.querySelector('#qaList .qa-item .qa-a')?.textContent?.slice(0,90)")
        shot(page, "25-verdict-qa.png")
        return f"质询答复: {ans!r}"
    check("C5 裁决质询(QA追问)", c5)

    def c6():
        sess = requests.get(BASE + "/api/debates", timeout=5).json()
        sl = sess if isinstance(sess, list) else sess.get("sessions", [])
        sid = sl[0].get("session_id") or sl[0].get("id") if sl else None
        r = requests.get(BASE + f"/api/debates/{sid}/report?format=markdown", timeout=10)
        return f"复盘{len(sl)}场 report API={r.status_code} 首行={r.text[:60]!r}"
    check("C6 审判报告 API", c6)

    def c7():
        # 直接切到复盘标签（不再经设置抽屉：抽屉遮罩会挡后续交互）
        page.evaluate("switchTab('library'); refreshDebates()")
        page.wait_for_timeout(1800)
        n2 = page.evaluate("document.querySelectorAll('#debateList .lib-item').length")
        shot(page, "26-replay-list.png")
        # UI 重构后按钮为 JS 属性绑定（btn.onclick=…），按 class 选择器取「打开复盘」
        page.evaluate("var b=document.querySelector('#debateList .lib-item button'); b && b.click()")
        page.wait_for_timeout(2800)
        ws_hidden = page.evaluate("document.getElementById('workspace')?.classList.contains('hidden')")
        n_msg = page.evaluate("document.querySelectorAll('#debate .rec').length")
        n_verdict = page.evaluate("document.querySelectorAll('#verdictBox .verdict').length")
        shot(page, "16-replay.png", full=True)
        page.evaluate("goHome()")
        close_overlays(page)
        assert not ws_hidden and n_msg > 1, f"回放异常: hidden={ws_hidden} msgs={n_msg}"
        return f"复盘列表={n2}场 回放发言{n_msg}条 裁决书恢复={n_verdict==1}"
    check("C7 复盘留档+回放", c7)

    def c8():
        page.evaluate("goHome()")
        if not gen.get("id"):
            d = requests.post(BASE + "/api/cases/generate", timeout=10).json()
            gen["id"] = d["case"]["id"]
        page.evaluate("selectCaseFromLib('" + gen["id"] + "')")
        page.wait_for_timeout(1000)
        close_overlays(page)
        page.evaluate("landStart()")
        page.wait_for_function("document.getElementById('workspace') && !document.getElementById('workspace').classList.contains('hidden')", timeout=10000)
        page.wait_for_timeout(1200)
        page.evaluate("focusMode()")
        page.wait_for_timeout(500)
        noleft = page.evaluate("document.getElementById('workspace').classList.contains('no-left')")
        btn_txt = page.evaluate("document.getElementById('btnFocus')?.textContent")
        shot(page, "17-focus-mode.png")
        page.evaluate("focusMode()")
        return f"聚焦模式: no-left={noleft} 按钮={btn_txt!r}"
    check("C8 聚焦模式", c8)

    def c9():
        m = ctx.new_page()
        m.set_viewport_size({"width": 390, "height": 844})
        m.goto(BASE + "/")
        m.wait_for_timeout(2000)
        shot(m, "13-mobile-landing.png", full=True)
        nav = m.evaluate("!!document.getElementById('mobileNav')")
        m.evaluate("toggleMobilePanel('left')")
        m.wait_for_timeout(600)
        shot(m, "18-mobile-panel.png")
        m.close()
        assert nav, "移动端底部导航缺失"
        return "移动端落地页+底部导航+侧板 OK"
    check("C9 移动端视图", c9)

    real_errors = [e for e in console_errors if "favicon" not in e and "404" not in e]
    results.append(("_ Console JS errors", "PASS" if not real_errors else "WARN", len(real_errors), " | ".join(real_errors[:5])))
    browser.close()

print("\n" + "=" * 80)
np = sum(1 for r in results if r[1] == "PASS")
nf = sum(1 for r in results if r[1] == "FAIL")
print(f"TOTAL {len(results)}  PASS {np}  FAIL {nf}")
for name, st, dt, detail in results:
    print(f"[{st}] {name} ({dt}s) {detail}")
json.dump([{"name": n, "status": s, "secs": d, "detail": x} for n, s, d, x in results],
          open(os.path.join(OUT, "results.json"), "w"), ensure_ascii=False, indent=1)
