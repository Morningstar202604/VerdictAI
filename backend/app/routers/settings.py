# -*- coding: utf-8 -*-
"""运行设置路由：读取 / 更新（持久化 .env）/ 连通性自检。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import require_admin
from app.runtime import current as current_settings
from app.runtime import update as update_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])

# 浏览器 UA：规避部分中转站 WAF 对 openai SDK 默认 UA 的拦截
_BROWSER_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
}


@router.get("")
def get_settings():
    return current_settings()


@router.post("")
def post_settings(payload: dict, _: dict = Depends(require_admin)):
    return update_settings(payload)


@router.post("/test")
def test_settings(payload: dict):
    """测试 LLM 连接是否可用，返回连通状态和耗时。"""
    import time as _time

    provider = (payload or {}).get("llm_provider", "openai_compatible").strip().lower()
    api_key = (payload or {}).get("llm_api_key", "").strip()
    base_url = (payload or {}).get("llm_base_url", "").strip() or None
    model = (payload or {}).get("llm_model", "").strip() or "gpt-4o-mini"
    result: dict = {"ok": False, "model": model, "provider": provider}
    if provider == "mock":
        result["ok"] = True
        result["message"] = "Mock 模式：离线占位演示，未调用真实模型"
        return result
    if not api_key:
        # 本地引擎无需 API Key（OpenAI 兼容端点不校验密钥）
        api_key = "EMPTY"
    try:
        from openai import OpenAI

        # 部分 OpenAI 兼容中转的 WAF 会按 User-Agent 拦截 openai SDK 默认 UA
        # （返回 403 "Your request was blocked"），注入浏览器 UA 绕过。
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=_BROWSER_UA,
            max_retries=1,  # 默认重试 2 次 × 60s 会让自检拖到 3 分钟
        )
        t0 = _time.time()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "回复：ok"}],
            max_tokens=4,
            # 中转站高峰期响应可达 30s+，15s 会误报超时
            timeout=60.0,
        )
        elapsed = round(_time.time() - t0, 2)
        used_model = resp.model or model
        text = (resp.choices[0].message.content or "").strip()
        result.update({"ok": True, "model": used_model, "elapsed_s": elapsed, "message": text})
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    return result