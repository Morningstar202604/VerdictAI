# -*- coding: utf-8 -*-
"""联网搜索 Provider：searxng（默认，自托管无需 API Key）| bing_html（抓取兜底）| tavily（可选 API）。

统一返回 [{"title","url","snippet"}, ...]。任一 Provider 失败自动降级：
searxng → bing_html → 空结果（真实告知，不编造）。
"""

from __future__ import annotations

import http.client
import json
import logging
import re
import time
import urllib.parse
from typing import Dict, List, Tuple

from app.config import settings

log = logging.getLogger("verdictai.search")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 搜索结果 TTL 缓存（M1.5）：同一查询 30 分钟内不重复抓取；键含 Provider。
_CACHE: Dict[str, Tuple[float, List[Dict]]] = {}
_CACHE_TTL = 1800.0


def _cache_key(q: str) -> str:
    return f"{settings.search_provider}|{q.strip().lower()}"


def _norm_url(url: str) -> str:
    """URL 归一化（去 query/fragment/trailing slash），用于来源去重。"""
    try:
        parts = urllib.parse.urlsplit(url or "")
        return parts._replace(query="", fragment="").geturl().rstrip("/")
    except ValueError:
        return (url or "").rstrip("/")


def _http_get(host: str, path: str, timeout: int, https: bool = False, headers=None) -> str:
    conn_cls = http.client.HTTPSConnection if https else http.client.HTTPConnection
    conn = conn_cls(host, timeout=timeout)
    try:
        conn.request("GET", path, headers=headers or {"User-Agent": _UA})
        resp = conn.getresponse()
        if resp.status != 200:
            return ""
        return resp.read().decode("utf-8", "ignore")
    finally:
        conn.close()


def search_searxng(query: str, timeout: int) -> List[Dict]:
    """自托管 SearXNG JSON 端点：GET {base}/search?q=..&format=json"""
    base = (settings.search_base_url or "").rstrip("/")
    if not base:
        return []
    parsed = urllib.parse.urlparse(base)
    host = parsed.netloc
    if not host:
        return []
    path = parsed.path + "/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "language": "zh-CN", "safesearch": "0"}
    )
    try:
        text = _http_get(host, path, timeout, https=parsed.scheme == "https")
    except Exception as ex:  # noqa: BLE001
        log.warning("SearXNG 搜索失败: %s", ex)
        return []
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = []
    for r in (data.get("results") or [])[:8]:
        items.append({
            "title": str(r.get("title") or "").strip(),
            "url": str(r.get("url") or "").strip(),
            "snippet": str(r.get("content") or "").strip(),
        })
    return items


def search_bing_html(query: str, timeout: int) -> List[Dict]:
    """兜底：Bing 国内源 HTML 抓取（固定主机，仅查询串动态）。"""
    path = "/search?q=" + urllib.parse.quote(query) + "&count=8"
    try:
        html = _http_get(
            "cn.bing.com", path, timeout, https=True,
            headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"},
        )
    except Exception as ex:  # noqa: BLE001
        log.warning("Bing 抓取失败: %s", ex)
        return []
    if not html:
        return []
    items = []
    for ch in html.split('<li class="b_algo"')[1:]:
        mh = re.search(r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', ch, re.S)
        if not mh:
            continue
        mp = re.search(r'<p[^>]*>(.*?)</p>', ch, re.S)
        items.append({
            "title": re.sub(r"<[^>]+>", "", mh.group(2)).strip(),
            "url": mh.group(1),
            "snippet": re.sub(r"<[^>]+>", "", mp.group(1) if mp else "").strip(),
        })
    return items


def search_tavily(query: str, timeout: int) -> List[Dict]:
    """可选 API Provider（预留）：需要 TAVILY_API_KEY 环境变量。"""
    api_key = __import__("os").getenv("TAVILY_API_KEY", "")
    if not api_key:
        return []
    body = json.dumps({
        "api_key": api_key, "query": query,
        "max_results": 8, "search_depth": "basic",
    }).encode("utf-8")
    conn = http.client.HTTPSConnection("api.tavily.com", timeout=timeout)
    try:
        conn.request("POST", "/search", body=body, headers={
            "Content-Type": "application/json",
            "User-Agent": _UA,
        })
        resp = conn.getresponse()
        if resp.status != 200:
            return []
        data = json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception as ex:  # noqa: BLE001
        log.warning("Tavily 搜索失败: %s", ex)
        return []
    finally:
        conn.close()
    return [
        {"title": str(r.get("title") or "").strip(),
         "url": str(r.get("url") or "").strip(),
         "snippet": str(r.get("content") or "").strip()}
        for r in (data.get("results") or [])[:8]
    ]


def web_search(query: str, limit: int = 5) -> List[Dict]:
    """入口：按 SEARCH_PROVIDER 路由，失败自动降级 + 结果 TTL 缓存 +
    来源聚合去重（searxng 结果不足时用 bing 补充，按归一化 URL 去重）。"""
    provider = (settings.search_provider or "searxng").lower()
    timeout = settings.search_timeout or 12
    key = _cache_key(query)
    now = time.time()
    cached = _CACHE.get(key)
    if cached and now - cached[0] < _CACHE_TTL:
        log.info("搜索缓存命中：%s", query[:40])
        return list(cached[1])[:limit]

    items: List[Dict] = []
    if provider == "tavily":
        items = search_tavily(query, timeout)
    elif provider == "searxng":
        items = search_searxng(query, timeout)
        if len(items) < limit:
            # 来源聚合：主 Provider 结果不足时用兜底源补充，扩大覆盖面
            extra = search_bing_html(query, timeout)
            items = items + extra
    else:  # bing_html / 其他
        items = search_bing_html(query, timeout)

    # 按归一化 URL 去重合并（同源不同查询串只保留先出现者）
    merged: List[Dict] = []
    seen: set = set()
    for it in items:
        u = _norm_url(it.get("url") or "")
        if not u or u in seen:
            continue
        seen.add(u)
        merged.append(it)
    merged = merged[:limit]

    _CACHE[key] = (now, list(merged))
    return merged