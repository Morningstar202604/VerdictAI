# -*- coding: utf-8 -*-
"""案件管理路由：列表 / 查看 / 上传（PDF/DOCX/TXT + OCR + 表格）/ 生成示例 / 删除 / 证据一键核验。"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.auth import require_admin
from app.config import settings
from app.data import generate_case
from app.data.store import atomic_write_json, list_cases, load_case, validate_id
from app.intake.documents import process_document

router = APIRouter(prefix="/api/cases", tags=["cases"])
log = logging.getLogger("verdictai")

DATA_DIR = os.path.abspath(settings.data_dir)

# 支持的文档类型 → (process_document 的 kind, 是否二进制 base64)
_DOC_TYPES = ("pdf", "docx", "doc", "txt", "plain")

# 常见扩展名 → file_type（无 file_type 时按文件名推断）
_EXT_MAP = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".doc": "doc",
    ".txt": "txt",
    ".md": "txt",
    ".text": "txt",
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpeg",
    ".webp": "webp",
}
_IMG_TYPES = {"png", "jpg", "jpeg", "webp", "gif"}


def _text_to_case(text: str, filename: str = "") -> dict:
    """从提取文本构建案件 JSON 结构（文档上传时使用）。"""
    for ext, ft in _EXT_MAP.items():
        base = filename.lower().rsplit(ext, 1)[0]
        if base != filename.lower():
            title = base
            break
    else:
        title = re.sub(r"\.[^.]+$", "", filename) or "上传案件"
    return {
        "title": title or "上传案件",
        "summary": text[:2000],
        "persons": [],
        "evidence": [],
        "timeline": [],
        "statutes": [],
        "images": [],
    }


# ----------------------------- 案件 CRUD -----------------------------


@router.get("")
def cases(q: str = "", has_brief: int = 0, tag: str = ""):
    """案件列表，支持筛选：q=标题/摘要关键词，has_brief=1 仅显示已预处理，tag=按案由/标签。"""
    hb = None if int(has_brief or 0) == 0 else True
    return {"cases": list_cases(q=q, has_brief=hb, tag=tag)}


@router.get("/tags")
def case_tags():
    """案例库可用标签（案由 + 意图标签聚合），供筛选器展示。"""
    tags: dict = {}
    for c in list_cases():
        cause = (c.get("cause") or "").strip()
        if cause:
            tags[cause] = tags.get(cause, 0) + 1
        for t in (c.get("intent_tags") or []):
            t = str(t).strip()
            if t:
                tags[t] = tags.get(t, 0) + 1
    return {"tags": sorted(tags.keys())}


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


@router.get("/{case_id}/timeline")
def case_timeline(case_id: str):
    """证据时间线（M1.5）：案件内置 timeline 按时间排序输出；时间缺失的条目
    保留在原位不丢弃。确定性、零模型调用，供前端绘制横向时间线视图。"""
    if not validate_id(case_id):
        return JSONResponse({"error": "无效的案件 ID"}, status_code=400)
    c = load_case(case_id)
    if c is None:
        return JSONResponse({"error": "案件不存在"}, status_code=404)
    items = []
    for t in c.get("timeline") or []:
        if not isinstance(t, dict):
            continue
        items.append({
            "time": str(t.get("time") or ""),
            "event": str(t.get("event") or "")[:200],
            "source": str(t.get("source") or ""),
            "evidence": str(t.get("evidence") or t.get("evidence_id") or ""),
        })
    # 时间可解析的按时间排序；无时间/不可解析的兜底排在末尾，保持信息来源不丢
    import datetime as _dt

    def _sort_key(x):
        raw = x["time"] or ""
        try:
            return _dt.datetime.fromisoformat(raw).timestamp()
        except ValueError:
            return 0.0

    items.sort(key=_sort_key)
    return {
        "case_id": case_id,
        "count": len(items),
        "timeline": items,
        "evidence_count": len(c.get("evidence") or []),
    }


@router.get("/{case_id}/similar")
def similar_cases(case_id: str, limit: int = 3):
    """相似案例推荐（M1.5）：embedding 近邻优先，语义不可用时退关键词/案由重叠。
    返回 [{id,title,score,cause}]；无其他案件时返回空列表。"""
    if not validate_id(case_id):
        return JSONResponse({"error": "无效的案件 ID"}, status_code=400)
    from app.legal.retriever import case_similarities

    limit = max(1, min(10, int(limit)))
    return {"case_id": case_id, "similar": case_similarities(case_id, limit)}


@router.post("/generate")
async def regenerate(_: dict = Depends(require_admin)):
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


async def _store_upload(data: dict) -> dict:
    """把一份已构造好的案件 dict 持久化：ID 校验/去重/预处理/图表/落盘。返回 {case}。"""
    from app.intake.processor import preprocess

    cid = str(data.get("id") or "").strip()
    if cid and not validate_id(cid):
        # cid 会参与案件文件名拼接，必须与 GET/DELETE 端点同等校验，
        # 否则 "../" 之类的值可以写出 cases 目录之外
        raise ValueError("无效的案件 ID")
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


def _apply_document(data: dict) -> str | None:
    """把文档/图片 base64 展开为案件文本/图文/OCR 字段；出错返回错误消息（None=成功）。"""
    ft_raw = str(data.get("file_type") or "").lower().strip()
    if not ft_raw and data.get("file_name"):
        ft_raw = _EXT_MAP.get(os.path.splitext(str(data["file_name"]))[1].lower(), "")
    if not data.get("file_content"):
        return None
    # 图片：以 data URL 形式入 images，交由预处理的多模态/OCR 描述
    if ft_raw in _IMG_TYPES:
        img_name = data.get("file_name") or "图片"
        data.setdefault("images", []).append({
            "name": img_name,
            "data_url": f"data:image/{ft_raw};base64,{data['file_content']}",
        })
        return None
    if not (ft_raw in _DOC_TYPES and data.get("file_content")):
        return None
    proc = process_document(ft_raw, data["file_content"], data.get("file_name", ""))
    if ft_raw == "pdf" and proc["encrypted"]:
        return "PDF 已加密，请先解除密码保护后再上传"
    if not proc["text"] and not proc["tables"]:
        hint = "（可能是扫描件，请启用 OCR 后重试）" if ft_raw == "pdf" else ""
        return f"文档文本提取失败{hint}，请粘贴文字内容"
    case_from_doc = _text_to_case(proc["text"], data.get("file_name", ""))
    for k, v in case_from_doc.items():
        if k not in data or not data[k]:
            data[k] = v
    data["pdf_text"] = proc["text"]  # 统一存为原始提取文本（前端预览兼容）
    if proc["tables"]:
        data["tables"] = proc["tables"]
    if proc["ocr_pages"]:
        data["ocr_pages"] = proc["ocr_pages"]
    return None


@router.post("/upload")
async def upload_case(payload: dict, _: dict = Depends(require_admin)):
    if not isinstance(payload, dict):
        return JSONResponse({"error": "案件须为 JSON 对象"}, status_code=400)
    data = dict(payload)
    err = _apply_document(data)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    try:
        return await _store_upload(data)
    except ValueError as ex:
        return JSONResponse({"error": str(ex)}, status_code=400)


@router.post("/import_batch")
async def import_batch(payload: dict, _: dict = Depends(require_admin)):
    """批量导入：files=[{file_type,file_content,file_name}, ...]（PDF/DOCX/TXT）。逐份处理，单份失败不影响其余。"""
    files = (payload or {}).get("files")
    if not isinstance(files, list) or not files:
        return JSONResponse({"error": "files 须为非空数组"}, status_code=400)
    results = []
    for f in files[:50]:  # 单批上限 50 份，防误操作刷爆
        if not isinstance(f, dict):
            results.append({"ok": False, "error": "文件项格式错误"})
            continue
        data = dict(f)
        err = _apply_document(data)
        if err:
            data["title"] = data.get("file_name") or data.get("title") or "未命名"
            results.append({"ok": False, "file_name": data["title"], "error": err})
            continue
        try:
            saved = await _store_upload(data)
            results.append({"ok": True, "id": saved["case"]["id"],
                            "title": saved["case"].get("title")})
        except ValueError as ex:
            results.append({"ok": False, "file_name": data.get("file_name"),
                            "error": str(ex)})
    ok_n = sum(1 for r in results if r.get("ok"))
    return {"imported": ok_n, "total": len(results), "results": results}


@router.delete("/{case_id}")
async def delete_case(case_id: str, _: dict = Depends(require_admin)):
    """删除案件（案例库管理，需管理员权限）。"""
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