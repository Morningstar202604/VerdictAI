# -*- coding: utf-8 -*-
"""文档解析层：PDF / DOCX / TXT / 扫描件 OCR / PDF 表格。

统一入口 process_document()：
- 文本层直取（PDF via PyMuPDF，DOCX via python-docx）；
- 无文本层（扫描件）时按需走 RapidOCR（onnx 本地，可选开关）；
- PDF 表格用 pdfplumber 提取（可选依赖，缺失自动降级）；
- 全部经过 base64 解码与字符上限截断，超长时返回首尾信息摘要提示。

可选能力通过 settings 开关控制，缺失依赖时静默降级，绝不阻断主流程。
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any, Dict, List

from app.config import MAX_PDF_CHARS, MAX_PDF_PAGES, settings

log = logging.getLogger("verdictai.documents")

_RAPIDOCR: Any = None  # 惰性单例：None=未加载, False=不可用, 对象=可用


def _ocr_engine():
    """惰性加载 RapidOCR（onnxruntime）。失败或未启用时返回 None。"""
    global _RAPIDOCR
    if _RAPIDOCR is not None:
        return _RAPIDOCR or None
    if not settings.ocr_enabled:
        _RAPIDOCR = False
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR

        engine = RapidOCR()
        # 预热（首次调用会加载模型，避免在辩论主路径上卡顿）
        engine("")
        _RAPIDOCR = engine
    except Exception as ex:  # noqa: BLE001
        log.warning("RapidOCR 不可用，扫描件将退回文本说明: %s", ex)
        _RAPIDOCR = False
    return _RAPIDOCR or None


def _decode_b64(b64_content: str) -> bytes:
    try:
        return base64.b64decode(b64_content or "")
    except Exception:
        return b""


def ocr_image_bytes(png_bytes: bytes) -> str:
    """对一张图片字节做 OCR，返回识别文本（失败返回空串）。"""
    engine = _ocr_engine()
    if engine is None:
        return ""
    try:
        # RapidOCR 接受 numpy 数组或 bytes（新版支持 path/bytes）
        result, _ = engine(png_bytes)
        if not result:
            return ""
        lines = [str(r[1]).strip() for r in result if len(r) > 1 and str(r[1]).strip()]
        return "\n".join(lines)
    except Exception as ex:  # noqa: BLE001
        log.warning("OCR 单页失败: %s", ex)
        return ""


def extract_text_tail(text: str, max_chars: int = MAX_PDF_CHARS) -> tuple[str, bool]:
    """截断长文本：保留开头与结尾各四分之一（关键事实通常集中在首尾），
    并附截断说明。返回 (text, truncated)。"""
    if len(text) <= max_chars:
        return text, False
    head = max_chars * 3 // 4
    tail = max_chars - head - 64
    body = text[:head] + "\n\n[中间内容已省略……]\n\n" + text[-tail:]
    return body, True


def chunk_text(text: str, size: int = 40000, overlap: int = 2000) -> List[str]:
    """按近似段落边界把长文本切成有重叠的块（供 future map-merge 使用）。"""
    if len(text) <= size:
        return [text]
    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # 回退到最近的段落边界，保留 overlap
            cut = text.rfind("\n", int(start + size * 0.8), end)
            if cut > start:
                end = cut
        chunks.append(text[start:end])
        start = max(end - overlap, start + size // 2)
        if not chunks[-1]:
            break
    return chunks


def _extract_pdf(pdf_bytes: bytes, max_pages: int, max_chars: int) -> Dict[str, Any]:
    """PDF 文本层 + 表格 + 扫描页 OCR。返回 {"text","tables","ocr_pages","encrypted"}。"""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return {"text": "", "tables": [], "ocr_pages": [], "encrypted": False}
    out: Dict[str, Any] = {"text": "", "tables": [], "ocr_pages": [], "encrypted": False}
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if doc.is_encrypted and not doc.authenticate(""):
            doc.close()
            out["encrypted"] = True
            return out
        pages: List[str] = []
        ocr_engine = _ocr_engine()
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            t = page.get_text().strip()
            if not t and ocr_engine is not None:
                pix = page.get_pixmap(dpi=200)
                ocr_text = ocr_image_bytes(pix.tobytes("png"))
                if ocr_text.strip():
                    pages.append(f"[第{i + 1}页·扫描件OCR]\n{ocr_text}")
                    out["ocr_pages"].append({"page": i + 1, "text": ocr_text})
                    continue
            pages.append(t)
        doc.close()
        text = "\n\n".join(p for p in pages if p.strip())
        text, _ = extract_text_tail(text, max_chars)
        out["text"] = text
    except Exception as ex:  # noqa: BLE001
        log.warning("PDF 解析失败: %s", ex)
        out["text"] = ""
        return out
    # 表格（可选依赖）
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for pi, page in enumerate(pdf.pages[:max_pages]):
                tbls = page.extract_tables()
                for tbl in tbls or []:
                    rows = [[(c or "").strip() for c in row] for row in tbl]
                    if any(any(c for c in row) for row in rows):
                        out["tables"].append({"page": pi + 1, "rows": rows[:30]})
    except ImportError:
        pass  # 可选依赖缺失：表格降级
    except Exception as ex:  # noqa: BLE001
        log.debug("pdfplumber 表格提取失败: %s", ex)
    return out


def _extract_docx(docx_bytes: bytes, max_chars: int) -> Dict[str, Any]:
    """DOCX：段落 + 表格。缺 python-docx 时降级返回空。"""
    out: Dict[str, Any] = {"text": "", "tables": []}
    try:
        import docx  # python-docx
    except ImportError:
        return out
    try:
        d = docx.Document(io.BytesIO(docx_bytes))
        parts: List[str] = [p.text.strip() for p in d.paragraphs if p.text.strip()]
        for tbl in d.tables:
            rows = [[(c.text or "").strip() for c in row.cells] for row in tbl.rows]
            if any(any(c for c in row) for row in rows):
                out["tables"].append(rows[:30])
                parts.append("【表格】" + "\n".join(" | ".join(r) for r in rows[:15]))
        text = "\n".join(parts)
        text, _ = extract_text_tail(text, max_chars)
        out["text"] = text
    except Exception as ex:  # noqa: BLE001
        log.warning("DOCX 解析失败: %s", ex)
    return out


def extract_plain(b64_content: str, max_chars: int) -> str:
    """TXT/纯文本：按 UTF-8（失败回退 GBK）解码并截断。"""
    raw = _decode_b64(b64_content)
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    else:
        text = ""
    text, _ = extract_text_tail(text, max_chars)
    return text


def process_document(
    file_type: str,
    b64_content: str,
    filename: str = "",
    max_pages: int = MAX_PDF_PAGES,
    max_chars: int = MAX_PDF_CHARS,
) -> Dict[str, Any]:
    """统一文档入口。file_type: pdf|docx|txt|plain。返回:
    {"text","tables","ocr_pages","encrypted","kind","note"}"""
    ft = (file_type or "").lower()
    result: Dict[str, Any] = {
        "text": "", "tables": [], "ocr_pages": [], "encrypted": False,
        "kind": ft, "note": "",
    }
    if ft == "pdf":
        pdf_bytes = _decode_b64(b64_content)
        if not pdf_bytes:
            result["note"] = "文件缺失或 base64 解码失败"
            return result
        r = _extract_pdf(pdf_bytes, max_pages, max_chars)
        result.update(r)
        if r["encrypted"]:
            result["note"] = "PDF 已加密且无法用空密码解密"
    elif ft in ("docx", "doc"):
        r = _extract_docx(_decode_b64(b64_content), max_chars)
        result.update(r)
        if not r["text"] and not r["tables"]:
            result["note"] = "DOCX 文本提取失败（可能是旧版 .doc 或依赖缺失），请粘贴文字内容"
    else:  # txt / plain / 其他
        result["text"] = extract_plain(b64_content, max_chars)
        if not result["text"]:
            result["note"] = "文本提取失败，请确认为 UTF-8/GBK 编码"
    return result