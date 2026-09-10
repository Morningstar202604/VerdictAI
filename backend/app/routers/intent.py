# -*- coding: utf-8 -*-
"""意图路由路由：轻量预览端点，供前端新庭审输入实时识别（M1.5）。

与完整预处理的分工：
- 本路由 = 确定性意图路由（门禁/案由/预设/实体槽位/置信度），零模型调用，即时返回；
- POST /api/cases/upload = 完整卷宗预处理（LLM intake + 文档/图片解析），重流程走那里。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import intent_router

router = APIRouter(prefix="/api/intent", tags=["intent"])


@router.get("/preview")
def preview(text: str = ""):
    """输入实时意图预览：门禁判定 + 案由/预设 + 置信度 + 实体槽位。"""
    return intent_router(text)