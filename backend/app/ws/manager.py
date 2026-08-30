from __future__ import annotations

import asyncio
from typing import Dict

from fastapi import WebSocket


class ConnectionManager:
    """按会话管理 WebSocket 连接，并支持人工复核时的阻塞等待。"""

    def __init__(self) -> None:
        self.active: Dict[str, WebSocket] = {}
        self.human_queues: Dict[str, "asyncio.Queue[str]"] = {}
        self.final_queues: Dict[str, "asyncio.Queue[str]"] = {}

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self.active[session_id] = ws
        self.human_queues[session_id] = asyncio.Queue()
        self.final_queues[session_id] = asyncio.Queue()

    def disconnect(self, session_id: str) -> None:
        self.active.pop(session_id, None)
        self.human_queues.pop(session_id, None)
        self.final_queues.pop(session_id, None)

    async def send(self, session_id: str, obj: dict) -> None:
        ws = self.active.get(session_id)
        if ws is not None:
            try:
                await ws.send_json(obj)
            except Exception:
                pass

    async def push_human(
        self, session_id: str, text: str, subtype: str = "intervene"
    ) -> None:
        q = (self.final_queues if subtype == "final" else self.human_queues).get(
            session_id
        )
        if q is not None:
            await q.put(text)

    def pop_human(self, session_id: str) -> "str | None":
        """非阻塞取出一条人工介入消息（用于辩论中途注入下一轮）。"""
        q = self.human_queues.get(session_id)
        if q is None:
            return None
        return q.get_nowait() if not q.empty() else None

    async def wait_for_human(self, session_id: str, timeout: float = 0) -> "str | None":
        """阻塞等待人类落槌。timeout>0 时限时等待，超时返回 None（由调用方兜底）。"""
        q = self.final_queues.get(session_id)
        if q is None:
            return ""
        try:
            if timeout and timeout > 0:
                return await asyncio.wait_for(q.get(), timeout=timeout)
            return await q.get()
        except asyncio.TimeoutError:
            return None


manager = ConnectionManager()
