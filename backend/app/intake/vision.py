# -*- coding: utf-8 -*-
"""视觉层：案情图片处理（现场/物证/文书扫描）。

- 多模态模型可用（openai_compatible 系支持 image_url）→ 语义描述 + 文字识别；
- mock / 本地引擎 / 多模态不可用 → RapidOCR 兜底（若开启且装好）；
- 全失败 → 返回如实说明（绝不编造图像内容）。
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Optional

from app.config import settings
from app.models.llm import get_llm, is_mock

log = logging.getLogger("verdictai.vision")

_VISION_TIMEOUT = 30


def data_url_to_bytes(data_url: str) -> bytes:
    try:
        return base64.b64decode((data_url or "").split(",", 1)[-1])
    except Exception:
        return b""


def ocr_data_url(data_url: str) -> str:
    """对图片 data URL 做本地 OCR（RapidOCR，可选能力）。失败返回空串。"""
    if not settings.ocr_enabled:
        return ""
    try:
        from app.intake.documents import ocr_image_bytes

        return ocr_image_bytes(data_url_to_bytes(data_url))
    except Exception as ex:  # noqa: BLE001
        log.debug("图片 OCR 失败: %s", ex)
        return ""


async def describe_image(data_url: str, name: str = "图片", cfg: Optional[dict] = None) -> str:
    """返回该图片的案情描述。优先级：多模态 LLM → OCR → 如实占位。"""
    ocr = await asyncio.to_thread(ocr_data_url, data_url)
    if not is_mock(cfg):
        try:
            llm = get_llm("分案法官", cfg=cfg)
            msg = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "请用中文简要描述这张图片中与案件相关的信息"
                                    "（场景/文字/物品/人员/伤势等），用于卷宗预处理。"
                                    "若无法识别请如实说明。",
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ]
            resp = await asyncio.wait_for(llm.ainvoke(msg), timeout=_VISION_TIMEOUT)
            text = str(resp.content or "").strip()
            if text and not text.lower().startswith("不支持") and "无法识别" not in text[:20]:
                return text
        except asyncio.TimeoutError:
            log.warning("图片多模态描述超时（%ss）: %s", _VISION_TIMEOUT, name)
        except Exception as ex:  # noqa: BLE001
            log.warning("图片多模态描述失败: %s", ex)
    if ocr:
        return f"（OCR识别）\n{ocr}"
    return "（图片已附：当前模型不支持视觉或识别失败，建议由专家结合卷宗文本分析）"