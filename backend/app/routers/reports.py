# -*- coding: utf-8 -*-
"""庭审核查报告导出（M1.5）：把一份辩论记录组装为结构化报告。

- Markdown（默认，零依赖）；
- DOCX（python-docx 可选依赖，缺失自动降级为 Markdown，绝不报错）。

报告章节：案件信息 → 各专家核心主张 → 矛盾清单 → 证据链/存疑点 →
审判长裁决 → 处置建议 → 免责声明。全部取自落盘的辩论记录 events，
无任何模型调用，可离线/反复导出。
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

from app.config import settings
from app.data.store import validate_id

router = APIRouter(prefix="/api/debates", tags=["reports"])

_MD_ESCAPE = str.maketrans({"_": r"\_", "*": r"\*", "[": r"\[", "`": r"\`"})


def _md(text: str) -> str:
    return str(text or "").translate(_MD_ESCAPE)


def _last_verification(events: List[dict]) -> dict | None:
    """取最近一条 selfcheck 事件携带的引用核验结果（B 阶段）；旧记录无则 None。"""
    last = None
    for ev in events or []:
        if ev.get("kind") == "selfcheck":
            v = (ev.get("selfcheck") or {}).get("verification")
            if isinstance(v, dict):
                last = v
    return last


def _load_record(session_id: str) -> dict | None:
    p = os.path.join(settings.data_dir, "debates", f"{session_id}.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def render_markdown(rec: dict) -> str:
    """确定性组装 Markdown 报告。任何字段缺失都用占位兜底，不抛异常。"""
    verdict = rec.get("final_verdict") or {}
    events = rec.get("events") or []

    # 各专家最后一条核心主张（agent_note）
    notes: Dict[str, dict] = {}
    for ev in events:
        if ev.get("kind") == "agent_note" and ev.get("role"):
            notes[ev["role"]] = ev
    # 矛盾清单：合并各轮 critic_end
    contradicts: List[str] = []
    for ev in events:
        if ev.get("kind") == "critic_end":
            for c in ev.get("contradictions") or []:
                issue = (c.get("issue") if isinstance(c, dict) else c) or ""
                if issue and issue not in contradicts:
                    contradicts.append(issue)

    L: List[str] = []
    L.append("# 庭审核查报告")
    L.append("")
    L.append("> **文书性质说明**：本报告由 AI 审查角色辅助生成，供合议庭庭前审查与阅卷参考，"
             "不具有法律效力；所载意见不构成裁判结论，最终认定以合议庭评议为准。")
    L.append("")
    L.append(f"- **案件**：{_md(rec.get('case_title') or '未命名')}")
    L.append(f"- **开庭时间**：{_md(rec.get('started_at') or '-')}")
    L.append(f"- **模型**：{_md(rec.get('model') or '-')}")
    usg = rec.get("usage") or {}
    L.append(f"- **过程量**：{rec.get('rounds') or 0} 轮 · "
             f"调用 {usg.get('calls') or 0} 次 · 输出 {usg.get('out_chars') or 0} 字符")
    L.append("")

    L.append("## 一、AI 审查视角意见（模拟控辩合议，供参考）")
    L.append("")
    if not notes:
        L.append("（无专家发言记录）")
    else:
        for role, ev in notes.items():
            L.append(f"### {_md(ev.get('name') or role)}")
            L.append(f">{ _md((ev.get('note') or {}).get('claim') if isinstance(ev.get('note'), dict) else ev.get('note') or '') }")
            L.append("")
    L.append("")

    L.append("## 二、矛盾清单")
    L.append("")
    if not contradicts:
        L.append("（未发现矛盾，或本场未产生竞争性陈述）")
    else:
        for i, c in enumerate(contradicts, 1):
            L.append(f"{i}. {_md(c)}")
    L.append("")

    L.append("## 三、证据链")
    L.append("")
    chain = verdict.get("evidence_chain") or []
    for ev in events:
        if ev.get("kind") == "verdict":
            chain = (ev.get("verdict") or {}).get("evidence_chain") or chain
            if chain:
                break
    findings = verdict.get("evidence_findings") or []
    if findings:
        L.append("| 编号 | 证据 | 三性意见 | 采信 | 理由 |")
        L.append("| --- | --- | --- | --- | --- |")
        for f in findings[:40]:
            adm = "采信" if f.get("admitted") else "排除"
            L.append(
                f"| {_md(f.get('id') or '')} | {_md(f.get('name') or '')} | {_md(f.get('opinion') or '')} "
                f"| {adm} | {_md(f.get('reason') or '')} |"
            )
        L.append("")
    if chain:
        for i, c in enumerate(chain[:30], 1):
            L.append(f"{i}. {_md(c)}")
        L.append("")
    if not chain and not findings:
        L.append("（证据链为空）")
        L.append("")

    L.append("## 四、审判长裁决")
    L.append("")
    truth = verdict.get("findings_of_fact") or verdict.get("truth_hypothesis")
    L.append(f"**经审理查明**：{_md(truth or '（未得出）')}")
    L.append("")
    if verdict.get("reasoning"):
        L.append(f"**裁判说理**：{_md(verdict['reasoning'])}")
        L.append("")
    cites = verdict.get("law_citations") or []
    if cites:
        L.append("**引用法条**：")
        for c in cites[:20]:
            L.append(f"- 《{_md(str(c.get('title') or '').strip('《》'))}》{_md(c.get('article') or '')}（{_md(c.get('purpose') or '依据')}）")
        L.append("")
    # B 阶段：法条引用核验（取 selfcheck 事件携带的 verification；旧记录无此字段则跳过）
    verification = _last_verification(events)
    if verification:
        v_cites = verification.get("citations") or []
        flagged = [r for r in v_cites if r.get("status") != "verified"]
        sent = verification.get("sentencing_check") or {}
        L.append("**引用核验**（内置法条库确定性比对，供人工复核）：")
        if v_cites:
            for r in v_cites[:20]:
                mark = {"verified": "✓", "not_in_library": "✗", "unknown_law": "?"}.get(r.get("status"), "·")
                L.append(f"- {mark} {_md(str(r.get('title') or ''))} {_md(str(r.get('article') or ''))}：{_md(r.get('note') or '')}")
        if flagged:
            L.append(f"- ⚠ 共 {verification.get('flagged', len(flagged))} 条引用未通过核验，需法官人工核对原文")
        if sent.get("note"):
            L.append(f"- 量刑区间校验：{'通过' if sent.get('ok') else '不通过'}——{sent.get('note', '')}")
        L.append("")
    if verdict.get("ruling"):
        L.append(f"**裁决主文**：{_md(verdict['ruling'])}")
        L.append("")
    if verdict.get("sentencing"):
        L.append(f"**量刑/责任承担**：{_md(verdict['sentencing'])}")
        L.append("")
    L.append("**存疑点**：")
    doubts = verdict.get("doubts") or []
    if not doubts:
        L.append("- （无）")
    else:
        for d in doubts[:20]:
            L.append(f"- {_md(d)}")
    L.append("")
    L.append("**处置建议**：")
    recmd = verdict.get("recommendation")
    L.append(f"{_md(recmd or '（未给出）')}")
    L.append("")
    stps = verdict.get("next_steps") or []
    if stps:
        L.append("**后续步骤**：")
        for s in stps[:10]:
            L.append(f"- {_md(s)}")
        L.append("")
    disc = verdict.get("disclaimer")
    if disc:
        L.append(f"> {_md(disc)}")
    return "\n".join(L)


def render_docx(rec: dict) -> bytes | None:
    """DOCX 导出（python-docx，可选）。缺失返回 None 由调用方降级。"""
    try:
        from docx import Document  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    doc = Document()
    doc.add_heading("庭审核查报告", 0)
    verdict = rec.get("final_verdict") or {}
    doc.add_paragraph(f"案件：{rec.get('case_title') or '未命名'}")
    doc.add_paragraph(f"开庭时间：{rec.get('started_at') or '-'}")
    doc.add_heading("合议庭专家主张", level=1)
    events = rec.get("events") or []
    notes = {}
    for ev in events:
        if ev.get("kind") == "agent_note" and ev.get("role"):
            notes[ev["role"]] = ev
    for _role, ev in notes.items():
        note = ev.get("note") or {}
        doc.add_heading(str(ev.get("name") or _role), level=2)
        doc.add_paragraph(str(note.get("claim") if isinstance(note, dict) else note or ""))
    doc.add_heading("审判长裁决", level=1)
    doc.add_paragraph(f"经审理查明：{verdict.get('findings_of_fact') or verdict.get('truth_hypothesis') or '（未得出）'}")
    for f in (verdict.get("evidence_findings") or [])[:40]:
        adm = "采信" if f.get("admitted") else "排除"
        doc.add_paragraph(f"· {f.get('id', '')} {f.get('name', '')}：{f.get('opinion', '')}（{adm}）")
    if verdict.get("reasoning"):
        doc.add_paragraph(f"裁判说理：{verdict['reasoning']}")
    for c in (verdict.get("law_citations") or [])[:20]:
        doc.add_paragraph(f"· 法条：{c.get('title', '')} {c.get('article', '')}（{c.get('purpose', '')}）")
    verification = _last_verification(events)
    if verification:
        doc.add_heading("法条引用核验（供人工复核）", level=2)
        for r in (verification.get("citations") or [])[:20]:
            mark = {"verified": "✓", "not_in_library": "✗", "unknown_law": "?"}.get(r.get("status"), "·")
            doc.add_paragraph(f"{mark} {r.get('title','')} {r.get('article','')}：{r.get('note','')}")
        if verification.get("sentencing_check") and verification["sentencing_check"].get("note"):
            s = verification["sentencing_check"]
            doc.add_paragraph(f"量刑区间校验：{'通过' if s.get('ok') else '不通过'}——{s.get('note','')}")
    if verdict.get("ruling"):
        doc.add_paragraph(f"裁决主文：{verdict['ruling']}")
    if verdict.get("sentencing"):
        doc.add_paragraph(f"量刑/责任承担：{verdict['sentencing']}")
    for d in (verdict.get("doubts") or [])[:20]:
        doc.add_paragraph("· 存疑：" + str(d))
    doc.add_paragraph(f"处置建议：{verdict.get('recommendation') or ''}")
    if verdict.get("disclaimer"):
        doc.add_paragraph(str(verdict.get("disclaimer")))
    import io

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@router.get("/{session_id}/report")
def get_report(session_id: str, format: str = "markdown"):
    """导出庭审核查报告：format=markdown（默认）/ docx / txt。"""
    if not validate_id(session_id):
        return JSONResponse({"error": "无效的会话 ID"}, status_code=400)
    rec = _load_record(session_id)
    if rec is None:
        return JSONResponse({"error": "未找到该辩论记录"}, status_code=404)

    fmt = (format or "markdown").strip().lower()
    if fmt == "docx":
        data = render_docx(rec)
        if data is not None:
            return PlainTextResponse(
                data,
                media_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="verdictai-report-{session_id}.docx"'
                    )
                },
            )
        # python-docx 缺失 → 降级 Markdown（保证导出功能不中断）
    body = render_markdown(rec)
    if fmt == "txt":
        return PlainTextResponse(body, media_type="text/plain; charset=utf-8")
    return PlainTextResponse(
        body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="verdictai-report-{session_id}.md"'
            )
        },
    )