from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from fastapi import WebSocket

# 会话事件缓冲上限：重连续看只需最近的历史，超限丢弃最旧的事件
_BUFFER_CAP = 5000


class ConnectionManager:
    """按会话管理 WebSocket 连接，并支持人工复核时的阻塞等待。

    除连接与人工介入队列外，还为每个会话维护：
    - 事件缓冲（buffers）：直播的每一帧都顺手存档，断线重连时
      先补发快照再续直播，庭审不再因网络抖动而作废；
    - 辩论任务注册表（tasks）：任务挂在会话上而非某个连接的局部
      变量，重连后的新连接同样能停止/取消进行中的辩论。
    """

    def __init__(self) -> None:
        self.active: Dict[str, WebSocket] = {}
        self.human_queues: Dict[str, "asyncio.Queue[str]"] = {}
        self.final_queues: Dict[str, "asyncio.Queue[str]"] = {}
        self.buffers: Dict[str, List[dict]] = {}
        self.tasks: Dict[str, "asyncio.Task"] = {}

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self.active[session_id] = ws
        self.human_queues.setdefault(session_id, asyncio.Queue())
        self.final_queues.setdefault(session_id, asyncio.Queue())
        self.buffers.setdefault(session_id, [])

    def disconnect(self, session_id: str, ws: Optional[WebSocket] = None) -> None:
        """断开清理。传入 ws 时做守护：若该会话已被更新的连接接管
        （重连场景），旧连接的清理不得误删新连接的注册项。

        人工介入/落槌队列在脱离期间保留：宽限期内重连，排队中的
        介入消息与人类落槌等待都不丢。"""
        if ws is not None and self.active.get(session_id) is not ws:
            return
        self.active.pop(session_id, None)
        # buffers / tasks / 队列保留：跨重连续看，新庭审 start 时显式清空

    def cleanup_session(self, session_id: str, task) -> None:
        """任务终结后的最终清理：仅当注册表仍指向该任务时生效。"""
        if self.tasks.get(session_id) is task:
            self.tasks.pop(session_id, None)
        self.human_queues.pop(session_id, None)
        self.final_queues.pop(session_id, None)

    def reset_session_queues(self, session_id: str) -> None:
        """新庭审开局：丢弃上一场遗留的人工介入/落槌队列内容。"""
        self.human_queues[session_id] = asyncio.Queue()
        self.final_queues[session_id] = asyncio.Queue()

    async def send(self, session_id: str, obj: dict, buffer: bool = True) -> None:
        if buffer:
            buf = self.buffers.setdefault(session_id, [])
            buf.append(obj)
            if len(buf) > _BUFFER_CAP:
                del buf[: len(buf) - _BUFFER_CAP]
        ws = self.active.get(session_id)
        if ws is not None:
            try:
                await ws.send_json(obj)
            except Exception:
                pass

    def buffer(self, session_id: str) -> List[dict]:
        return list(self.buffers.get(session_id, []))

    def clear_buffer(self, session_id: str) -> None:
        self.buffers.pop(session_id, None)

    async def push_human(
        self, session_id: str, text: str, subtype: str = "intervene"
    ) -> bool:
        """投入一条人工介入消息。

        返回 False 表示队列不存在（辩论未开始/已终结）——此时消息会被丢弃，
        调用方必须据此回执用户，否则用户以为插话成功，实际石沉大海。
        """
        q = (self.final_queues if subtype == "final" else self.human_queues).get(
            session_id
        )
        if q is None:
            return False
        await q.put(text)
        return True

    def drain_human(self, session_id: str) -> "list[str]":
        """取出并清空所有待处理的人工介入消息（终结时用于提示未消费内容）。"""
        q = self.human_queues.get(session_id)
        if q is None:
            return []
        out = []
        while not q.empty():
            try:
                out.append(q.get_nowait())
            except asyncio.QueueEmpty:  # pragma: no cover - 竞态保护
                break
        return out

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
            return None
        try:
            if timeout and timeout > 0:
                return await asyncio.wait_for(q.get(), timeout=timeout)
            return await q.get()
        except asyncio.TimeoutError:
            return None


manager = ConnectionManager()
