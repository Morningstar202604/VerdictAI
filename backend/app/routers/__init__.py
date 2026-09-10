# -*- coding: utf-8 -*-
"""REST 路由集合：按领域拆分，避免 main.py 单文件膨胀。"""

from app.routers import (
    agents,
    cases,
    debates,
    knowledge,
    presets,
    qa,
    sandbox,
    settings as settings_router,
)

__all__ = [
    "agents",
    "cases",
    "debates",
    "knowledge",
    "presets",
    "qa",
    "sandbox",
    "settings_router",
]