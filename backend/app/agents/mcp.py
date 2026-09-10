# -*- coding: utf-8 -*-
"""MCP 工具接入（P1-5）：把外部 MCP server 的工具注册进专家工具表。

设计：
- 配置优先读 data/mcp_servers.json；也支持环境变量 MCP_SERVERS_JSON 给出一份
  JSON 数组（部署时免落盘）。未配置 → 功能关闭，零开销。
- 依赖官方 `mcp` SDK（在 requirements-ai.txt，可选增强）：未安装时优雅降级，
  本模块返回空工具表并标记不可用，主流程与其它工具完全不受影响。
- 每个 server 用 stdio transport 起子进程会话；工具名单在启用时缓存，
  单独调用时每次建立一次性会话执行 call_tool（避免长驻服务的进程泄漏）。
- 角色白名单：server 配置里的 roles 控制哪些角色可见；空/缺省=所有角色。
  工具名格式：mcp_<server>_<tool>，避免与内置工具重名。

mcp_servers.json 示例：
{
  "servers": [
    {
      "name": "files",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/sandbox"],
      "env": {},
      "roles": ["law", "forensic"],
      "enabled": true
    }
  ]
}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, List

from app.config import settings

log = logging.getLogger("debate.mcp")

_SDK_MISSING = False
try:  # 可选依赖：pip install -r requirements-ai.txt
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except Exception:  # pragma: no cover - 未安装时降级
    _SDK_MISSING = True

_CONFIG_PATH = None  # 延迟解析（依赖 settings.data_dir）


def _config_file() -> str:
    global _CONFIG_PATH
    if _CONFIG_PATH is None:
        _CONFIG_PATH = os.path.join(settings.data_dir, "mcp_servers.json")
    return _CONFIG_PATH


def sdk_available() -> bool:
    return not _SDK_MISSING


def _load_servers() -> List[Dict]:
    """读取配置：环境变量 JSON 优先，其次 data/mcp_servers.json 文件。"""
    raw = os.getenv("MCP_SERVERS_JSON", "").strip()
    servers: List[Dict] = []
    if raw:
        try:
            parsed = json.loads(raw)
            servers.extend(parsed if isinstance(parsed, list) else parsed.get("servers", []))
        except json.JSONDecodeError as e:
            log.warning("MCP_SERVERS_JSON 解析失败：%s", e)
    if os.path.exists(_config_file()):
        try:
            with open(_config_file(), encoding="utf-8") as fh:
                parsed = json.load(fh)
            items = parsed if isinstance(parsed, list) else parsed.get("servers", [])
            servers.extend(items)
        except Exception as e:
            log.warning("mcp_servers.json 读取失败：%s", e)
    out = []
    for s in servers:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        if s.get("enabled") is False:
            continue
        out.append(s)
    return out


def configured_servers() -> List[Dict]:
    if _SDK_MISSING:
        return []
    return _load_servers()


def _server_name(s: Dict) -> str:
    name = str(s.get("name") or "").strip()
    return "".join(c for c in name if c.isalnum() or c in "_-")[:32] or "mcp"


def _roles_for(s: Dict) -> set:
    roles = s.get("roles")
    if not roles:
        return set()  # 空=全部角色可见
    if isinstance(roles, str):
        roles = [roles]
    return {str(r).strip() for r in roles if str(r).strip()}


async def list_server_tools(server: Dict) -> List[Dict]:
    """列出某 server 的工具清单：[{name, description, inputSchema}]。"""
    if _SDK_MISSING:
        return []
    params = StdioServerParameters(
        command=str(server.get("command") or ""),
        args=[str(a) for a in (server.get("args") or [])],
        env={str(k): str(v) for k, v in (server.get("env") or {}).items()} or None,
    )
    tools: List[Dict] = []
    timeout = int(server.get("timeout") or 30)
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=timeout)
                res = await asyncio.wait_for(session.list_tools(), timeout=timeout)
                for t in (res.tools or []):
                    tools.append(
                        {
                            "name": t.name or "",
                            "description": (t.description or "")[:300],
                            "inputSchema": t.inputSchema or {},
                        }
                    )
    except Exception as e:  # noqa: BLE001
        log.warning("MCP server %s 工具列表获取失败：%s", server.get("name"), e)
    return tools


async def _call_tool(server: Dict, tool_name: str, args: Dict) -> str:
    """执行 MCP 工具调用（一次性 stdio 会话）。"""
    if _SDK_MISSING:
        return "MCP SDK 未安装（pip install -r requirements-ai.txt）"
    params = StdioServerParameters(
        command=str(server.get("command") or ""),
        args=[str(a) for a in (server.get("args") or [])],
        env={str(k): str(v) for k, v in (server.get("env") or {}).items()} or None,
    )
    timeout = int(server.get("timeout") or 60)
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=min(timeout, 30))
                res = await asyncio.wait_for(
                    session.call_tool(tool_name, args or {}), timeout=timeout
                )
                parts = []
                for c in (res.content or []):
                    t = getattr(c, "type", "")
                    try:
                        if t == "text":
                            parts.append(str(c.text))
                        elif t == "image":
                            parts.append("[图片结果（MCP）：数据省略]")
                        else:
                            parts.append(str(getattr(c, "text", c)))
                    except Exception:
                        parts.append(str(c))
                return "\n".join(parts) if parts else "(MCP 工具返回空结果)"
    except Exception as e:  # noqa: BLE001
        return f"MCP 工具调用失败（{server.get('name')}/{tool_name}）：{str(e)[:200]}"


def register_mcp_tools(role_key: str = ""):
    """为角色注册 MCP 工具：返回 langchain Tool 列表（可能为空）。

    同步入口（工具表只在启动/配置变更时构建），内部用事件循环在子线程
    执行异步列举；失败时返回空列表而非抛错，保证主流程稳定。
    """
    if _SDK_MISSING:
        return []
    servers = _load_servers()
    if not servers:
        return []
    from langchain_core.tools import tool as lc_tool

    out: List[Any] = []
    for s in servers:
        roles = _roles_for(s)
        if roles and role_key and role_key not in roles:
            continue
        name = _server_name(s)

        def _mk(server: Dict, tool_name: str, desc: str) -> Any:
            async def _run(args: str = "") -> str:
                seed: Dict = {}
                if args:
                    try:
                        seed = json.loads(args)
                    except json.JSONDecodeError:
                        seed = {"query": str(args)[:400]}
                return await _call_tool(server, tool_name, seed)

            # langchain 从签名推断 args schema（单字符串入参），
            # 不手工传 schema，避免库版本间的兼容分歧
            return lc_tool(
                f"mcp_{_server_name(server)}_{tool_name}",
                desc or f"MCP 工具 {server.get('name')}/{tool_name}",
                return_direct=False,
            )(_run)

        items: List[Dict] = []
        import threading

        box: dict = {"items": items}

        def _fetch() -> None:
            try:
                box["items"] = asyncio.run(list_server_tools(s))
            except Exception as e:  # noqa: BLE001
                log.warning("MCP 工具拉取失败 %s：%s", name, e)

        t = threading.Thread(target=_fetch, daemon=True)
        t.start()
        t.join(timeout=40)
        for spec in box["items"]:
            if not spec.get("name"):
                continue
            out.append(_mk(s, spec["name"], spec.get("description") or ""))
    return out


def mcp_tools_for_role(role_key: str):
    """角色可见的 MCP 工具（含全局 server 工具）。结果按调用缓存，避免重复拉起进程。"""
    if _SDK_MISSING:
        return []
    key = (role_key, _config_signature())
    cached = _role_cache.get(key)
    if cached is not None:
        return cached
    tools = register_mcp_tools(role_key)
    _role_cache[key] = tools
    return tools


def _config_signature() -> str:
    try:
        if os.path.exists(_config_file()):
            with open(_config_file(), encoding="utf-8") as fh:
                raw = os.getenv("MCP_SERVERS_JSON", "") + fh.read()
        else:
            raw = os.getenv("MCP_SERVERS_JSON", "")
        import hashlib

        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return ""

def clear_mcp_cache() -> None:
    _role_cache.clear()


_role_cache: dict = {}


def mcp_status() -> Dict:
    """MCP 能力状态（供管理端点展示）：SDK、已配置 server、角色授权。"""
    servers = _load_servers()
    return {
        "sdk_available": sdk_available(),
        "configured": [s.get("name") for s in servers],
        "enabled": bool(servers and sdk_available()),
        "config_file": _config_file(),
    }