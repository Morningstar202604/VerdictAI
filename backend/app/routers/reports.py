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
    L.append(f"- **案件**：{_md(rec.get('case_title') or '未命名')}")
    L.append(f"- **开庭时间**：{_md(rec.get('started_at') or '-')}")
    L.append(f"- **模型**：{_md(rec.get('model') or '-')}")
    usg = rec.get("usage") or {}
    L.append(f"- **过程量**：{rec.get('rounds') or 0} 轮 · "
             f"调用 {usg.get('calls') or 0} 次 · 输出 {usg.get('out_chars') or 0} 字符")
    L.append("")

    L.append("## 一、合议庭专家主张")
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
            chain = ev.get("verdict")["evidence_chain"] or []
            break
    chain = chain or (verdict.get("evidence_chain") or [])
    if not chain:
        L.append("（证据链为空）")
    else:
        for i, c in enumerate(chain[:30], 1):
            L.append(f"{i}. {_md(c)}")
    L.append("")

    L.append("## 四、审判长裁决")
    L.append("")
    truth = verdict.get("truth_hypothesis")
    L.append(f"**真相推定**：{_md(truth or '（未得出）')}")
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
    # 法条引用核查附录（幻觉防火墙）：裁决+全部发言逐条比对卷宗/内置法条
    try:
        from app.legal.cite_check import check_texts
        v_all = "\n".join(
            [str(verdict.get("truth_hypothesis") or "")]
            + [str(x) for x in (verdict.get("evidence_chain") or [])]
            + [str(x) for x in (verdict.get("doubts") or [])]
            + [str(verdict.get("recommendation") or "")]
        )
        texts = [v_all] + [
            str(ev.get("text") or "")
            for ev in events if ev.get("kind") in ("agent_end", "speech") and ev.get("text")
        ]
        case = None
        try:
            from app.data.store import load_case
            case = load_case(str(rec.get("case_id") or ""))
        except Exception:  # noqa: BLE001
            case = None
        audit = check_texts(texts, (case or {}).get("statutes"))
        if audit["stats"]["unique_citations"]:
            st = audit["stats"]
            L.append("## 五、法条引用核查（幻觉防火墙）")
            L.append("")
            L.append(f"共 **{st['unique_citations']}** 条引用："
                     f"✓ {st['verified']} 已核实 · ⚠ {st['unverified']} 待人工核对")
            L.append("")
            ok = [c for c in audit["citations"] if c["status"] == "verified"]
            warn = [c for c in audit["citations"] if c["status"] == "unverified"]
            if ok:
                L.append("**已核实**（卷宗法条 / 内置法条库命中）")
                L.append("")
                for c in ok:
                    L.append(f"- ✓ {c['key'].replace('|', ' · ')}（{str(c.get('ref_name') or '')[:60]}）")
                L.append("")
            if warn:
                L.append("**待人工核对**（库外条文或模型杜撰，采信前务必查证原文）")
                L.append("")
                for c in warn:
                    L.append(f"- ⚠ {_md(c.get('raw') or c['key'])}")
                L.append("")
    except Exception:  # noqa: BLE001 — 核查附录失败不阻断报告导出
        pass
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
    doc.add_paragraph(f"真相推定：{verdict.get('truth_hypothesis') or '（未得出）'}")
    for d in (verdict.get("doubts") or [])[:20]:
        doc.add_paragraph("· " + str(d))
    doc.add_paragraph(f"处置建议：{verdict.get('recommendation') or ''}")
    # 法条引用核查附录（失败静默，不阻断 DOCX 导出）
    try:
        from app.legal.cite_check import check_texts
        events = rec.get("events") or []
        v_all = "\n".join([str(verdict.get("truth_hypothesis") or "")]
                          + [str(x) for x in (verdict.get("evidence_chain") or [])]
                          + [str(x) for x in (verdict.get("doubts") or [])]
                          + [str(verdict.get("recommendation") or "")])
        texts = [v_all] + [str(ev.get("text") or "") for ev in events
                           if ev.get("kind") in ("agent_end", "speech") and ev.get("text")]
        case = None
        try:
            from app.data.store import load_case
            case = load_case(str(rec.get("case_id") or ""))
        except Exception:  # noqa: BLE001
            case = None
        audit = check_texts(texts, (case or {}).get("statutes"))
        if audit["stats"]["unique_citations"]:
            st = audit["stats"]
            doc.add_heading(f"法条引用核查（共 {st['unique_citations']} 条："
                            f"✓ {st['verified']} 已核实 · ⚠ {st['unverified']} 待人工核对）", level=1)
            for c in audit["citations"]:
                mark = "✓" if c["status"] == "verified" else "⚠"
                suffix = f" — {str(c.get('ref_name') or '')[:60]}" if c.get("ref_name") else "（待人工核对）"
                doc.add_paragraph(f"{mark} {c['key'].replace('|', ' · ')}{suffix}")
    except Exception:  # noqa: BLE001
        pass
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