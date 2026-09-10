# -*- coding: utf-8 -*-
"""案件管理路由：列表 / 查看 / 上传（含 PDF 文本提取）/ 生成示例 / 删除 / 证据一键核验。"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import MAX_PDF_CHARS, MAX_PDF_PAGES, settings
from app.data import generate_case
from app.data.store import atomic_write_json, list_cases, load_case, validate_id

router = APIRouter(prefix="/api/cases", tags=["cases"])
log = logging.getLogger("verdictai")

DATA_DIR = os.path.abspath(settings.data_dir)


# ----------------------------- PDF 文本提取 -----------------------------


def extract_pdf_text(
    b64_content: str, max_pages: int = MAX_PDF_PAGES, max_chars: int = MAX_PDF_CHARS
) -> str:
    """从 base64 编码的 PDF 中提取文本。

    对超大文档做截断保护，避免无限撑爆模型上下文：最多取前 max_pages 页、
    拼接后最多保留 max_chars 字符，并在超限时附加提示。
    """
    import base64

    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ""
    try:
        raw = base64.b64decode(b64_content)
        doc = fitz.open(stream=raw, filetype="pdf")
        # 检测加密 PDF
        if doc.is_encrypted:
            # 尝试空密码解密（很多 PDF 用空密码加密只是限制编辑）
            if not doc.authenticate(""):
                doc.close()
                log.warning("PDF 已加密且无法用空密码解密")
                return "__ENCRYPTED__"
        pages = []
        truncated_pages = False
        for i, page in enumerate(doc):
            if i >= max_pages:
                truncated_pages = True
                break
            pages.append(page.get_text())
        doc.close()
        text = "\n\n".join(pages).strip()
        truncated_chars = False
        if len(text) > max_chars:
            text = text[:max_chars].rstrip()
            truncated_chars = True
        if truncated_pages or truncated_chars:
            text += (
                "\n\n[注意：原始文档较大，已自动截断（"
                + ("页数" if truncated_pages else "")
                + ("字符" if truncated_chars else "")
                + "上限）以保证分析可行，关键事实请以来源原件为准。]"
            )
        return text
    except Exception:
        return ""


def _text_to_case(text: str, filename: str = "") -> dict:
    """从纯文本构建案件 JSON 结构（PDF 上传时使用）。"""
    title = filename.replace(".pdf", "").replace(".PDF", "") or "上传案件"
    return {
        "title": title,
        "summary": text[:2000],
        "persons": [],
        "evidence": [],
        "timeline": [],
        "statutes": [],
        "images": [],
    }


# ----------------------------- 案件 CRUD -----------------------------


@router.get("")
def cases():
    return {"cases": list_cases()}


@router.get("/{case_id}")
def get_case(case_id: str):
    if not validate_id(case_id):
        return JSONResponse({"error": "无效的案件 ID"}, status_code=400)
    c = load_case(case_id)
    if c is None:
        return JSONResponse({"error": "案件不存在"}, status_code=404)
    return c


@router.get("/{case_id}/evidence-audit")
def evidence_audit(case_id: str):
    """证据一键核验：确定性体检（编号唯一/格式/描述完整/保管链/时间可解析），
    庭前快速发现卷宗硬伤。纯规则检查，不做任何主观判断。"""
    if not validate_id(case_id):
        return JSONResponse({"error": "无效的案件 ID"}, status_code=400)
    c = load_case(case_id)
    if c is None:
        return JSONResponse({"error": "案件不存在"}, status_code=404)
    evs = c.get("evidence") or []
    ids = [str(e.get("id") or "") for e in evs]
    issues: list = []
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        issues.append({"level": "high", "msg": f"证据编号重复：{'、'.join(dup)}"})
    bad_fmt = [i for i in ids if i and not re.match(r"^[A-Z]-\d{2}$", i)]
    if bad_fmt:
        issues.append({"level": "low", "msg": f"编号格式建议统一为 E-NN：{'、'.join(bad_fmt)}"})
    missing_desc = [i for i, e in zip(ids, evs) if not str(e.get("desc") or "").strip()]
    if missing_desc:
        issues.append({"level": "medium", "msg": f"缺少证据描述：{'、'.join(missing_desc)}"})
    chain_flawed = [i for i, e in zip(ids, evs) if e.get("chain_intact") is False]
    unparseable_time = sum(
        1
        for t in c.get("timeline") or []
        if str(t.get("time") or "")
        and not re.search(r"\d{1,2}[:：]\d{2}|\d{4}年|\d{1,2}月\d{1,2}日", str(t.get("time")))
    )
    if unparseable_time:
        issues.append({"level": "low", "msg": f"{unparseable_time} 条时间线的时间无法解析为标准格式"})
    stats = {
        "count": len(evs),
        "chain_flawed": len(chain_flawed),
        "avg_reliability": (
            round(sum(float(e.get("reliability") or 0) for e in evs) / len(evs), 2) if evs else 0
        ),
        "timeline_events": len(c.get("timeline") or []),
        "unparseable_time": unparseable_time,
    }
    return {
        "case_id": case_id,
        "ok": not issues,
        "issues": issues,
        "stats": stats,
        "chain_flawed": chain_flawed,
    }


@router.post("/generate")
async def regenerate():
    """生成一个示例案件并加入案例库（用唯一 ID，不再硬编码 case_001）。"""
    from app.intake.processor import preprocess

    path = generate_case.generate()
    # 从 generate() 返回的路径读取案件，而非硬编码 case_001
    try:
        with open(path, encoding="utf-8") as f:
            case = json.load(f)
    except Exception as ex:
        return JSONResponse({"error": f"示例案件生成失败：{str(ex)[:200]}"}, status_code=500)
    if not case:
        return JSONResponse({"error": "示例案件为空"}, status_code=500)
    # 给示例案件一个新 ID，避免覆盖 case_001
    new_id = "case_" + uuid.uuid4().hex[:8]
    case["id"] = new_id
    # 标题去重：以原题去掉"(副本…)"后缀为基底，统计已有同源副本数，递增编号。
    # generate() 已把模板写进 cases 目录，统计时必须跳过模板自身，否则
    # 新生成的示例案件永远被误判为"已有副本"而带上 (副本) 后缀。
    base = re.sub(r"\s*\(副本\d*\)\s*$", "", case.get("title", "示例案件"))
    source_fn = os.path.basename(path)
    existing = 0
    try:
        for fn in os.listdir(os.path.join(DATA_DIR, "cases")):
            if not fn.endswith(".json") or fn == source_fn:
                continue
            try:
                with open(os.path.join(DATA_DIR, "cases", fn), encoding="utf-8") as f:
                    if (json.load(f).get("title") or "").startswith(base):
                        existing += 1
            except Exception:
                continue
    except Exception:
        pass
    if existing == 1:
        case["title"] = base + " (副本)"
    elif existing >= 2:
        case["title"] = base + f" (副本{existing})"
    try:
        case["brief"] = await preprocess(case)
    except Exception:
        pass
    new_path = os.path.join(os.path.dirname(path), f"{new_id}.json")
    atomic_write_json(new_path, case)
    return {"path": new_path, "case": case}


@router.post("/upload")
async def upload_case(payload: dict):
    from app.intake.processor import preprocess

    if not isinstance(payload, dict):
        return JSONResponse({"error": "案件须为 JSON 对象"}, status_code=400)
    data = dict(payload)

    # PDF 文件：从 base64 提取文本并构建案件结构
    if data.get("file_type") == "pdf" and data.get("file_content"):
        pdf_text = extract_pdf_text(data["file_content"])
        if pdf_text == "__ENCRYPTED__":
            return JSONResponse(
                {"error": "PDF 已加密，请先解除密码保护后再上传"}, status_code=400
            )
        if not pdf_text:
            return JSONResponse(
                {"error": "PDF 文本提取失败，文件可能是扫描件（图片型 PDF），请粘贴文字内容"}, status_code=400
            )
        case_from_pdf = _text_to_case(pdf_text, data.get("file_name", ""))
        for k, v in case_from_pdf.items():
            if k not in data or not data[k]:
                data[k] = v
        data["pdf_text"] = pdf_text

    cid = str(data.get("id") or "").strip()
    if cid and not validate_id(cid):
        # cid 会参与案件文件名拼接，必须与 GET/DELETE 端点同等校验，
        # 否则 "../" 之类的值可以写出 cases 目录之外
        return JSONResponse({"error": "无效的案件 ID"}, status_code=400)
    if not cid:
        cid = "case_" + uuid.uuid4().hex[:8]
    data["id"] = cid
    cases_dir = os.path.join(DATA_DIR, "cases")
    os.makedirs(cases_dir, exist_ok=True)
    # 标题去重：避免同名案件在列表中混淆
    _base = re.sub(r"\s*\(副本\d*\)\s*$", "", data.get("title", "上传案件"))
    _existing = 0
    try:
        for _fn in os.listdir(cases_dir):
            if not _fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(cases_dir, _fn), encoding="utf-8") as _f:
                    _c = json.load(_f)
                if (_c.get("title") or "").startswith(_base) and _c.get("id") != cid:
                    _existing += 1
            except Exception:
                continue
    except Exception:
        pass
    if _existing >= 1:
        data["title"] = _base + f" (副本{_existing})"
    try:
        data["brief"] = await preprocess(data)
    except Exception as ex:
        log.warning("preprocess failed for %s: %s", cid, ex)
        data["brief"] = {"intake_done": False, "error": str(ex)[:300]}
    try:
        from app.charts import generate_charts

        data["charts"] = generate_charts(data)
    except Exception as ex:
        log.warning("chart generation failed for %s: %s", cid, ex)
        data["charts"] = {}
    atomic_write_json(os.path.join(cases_dir, cid + ".json"), data)
    return {"case": data}


@router.delete("/{case_id}")
async def delete_case(case_id: str):
    """删除案件（案例库管理）。"""
    import shutil

    if not validate_id(case_id):
        return JSONResponse({"error": "无效的案件 ID"}, status_code=400)
    cases_dir = os.path.join(DATA_DIR, "cases")
    path = os.path.join(cases_dir, f"{case_id}.json")
    if not os.path.exists(path):
        return JSONResponse({"error": "案件不存在"}, status_code=404)
    os.remove(path)
    assets_dir = os.path.join(cases_dir, "assets", case_id)
    if os.path.exists(assets_dir):
        shutil.rmtree(assets_dir)
    return {"deleted": case_id}