# -*- coding: utf-8 -*-
"""法条引用核查引擎（对标 2026 主流法律 AI 的"幻觉防火墙"/引用信号灯设计）。

设计原则（与 Shepard's/KeyCite、智合 AI 幻觉防火墙同源）：
- 不调用任何模型，纯确定性匹配：法条引用要么能在「本案卷宗法条 + 内置法条库」
  中命中（verified），要么标记为待人工核对（unverified）——绝不静默放过；
- 规范化归一：《中华人民共和国刑法》/《刑法》/刑法 → 同一 key；
  中文数字（第二百六十六条）与阿拉伯数字（266 条）归一；
- 「之一/之二」修正案条款单独保留。

核心数据结构：
- statute_key(law, art, alt) -> "刑法|第266条" 形式的唯一键；
- extract_citations(text) -> [{raw, law, article, alt, key}]
- check_text(text, case_statutes) -> 逐条 status/source
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# ---------------- 中文数字 → 阿拉伯数字 ----------------

_CN_DIG = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
           "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}


def chn_to_int(s: str) -> Optional[int]:
    """中文数字转 int（支持到千位，覆盖民法典 1260 条量级）。失败返回 None。
    容忍「第」前缀与「条」尾缀（如「第二百六十六」）。"""
    if not s:
        return None
    s = str(s).strip().lstrip("第").rstrip("条").strip()
    if s.isdigit():
        return int(s)
    total, num, seen = 0, 0, False
    for ch in s:
        if ch in _CN_DIG:
            num = _CN_DIG[ch]
            seen = True
        elif ch in _CN_UNIT:
            if not seen:
                num = 1  # 「十」前置省略一：十X → 10+X
            total += num * _CN_UNIT[ch]
            num, seen = 0, False
        else:
            return None
    if not (seen or total):
        return None
    return total + num


# 常见简称 → 规范名（与内置法条库/卷宗法条对齐）
_LAW_ALIAS = {
    "刑诉法": "刑事诉讼法",
    "民诉法": "民事诉讼法",
    "行政诉讼法": "行政诉讼法",
    "刑诉解释": "刑诉法解释",
}

# 引用正则：有书名号（《中华人民共和国刑法》第266条）与无书名号（刑法第266条）两种写法
_CITE_RE = re.compile(
    r"(?:《(?P<law>[^《》]{2,25}?)》|(?P<law2>[\u4e00-\u9fff]{1,12}?法))"
    r"\s*第\s*(?P<art>[零〇一二两三四五六七八九十百千\d]{1,10})\s*条"
    r"(?P<alt>之[一二三四])?"
)

# 从条目标题中提取引用（内置库 title / 卷宗 statutes.name 共用）
_TITLE_CITE_RE = re.compile(
    r"《(?P<law>[^《》]{2,25}?)》\s*第\s*(?P<art>[零〇一二两三四五六七八九十百千\d]{1,10})\s*条(?P<alt>之[一二三四])?"
)


# 无书名号引用常见的动词/连接词前缀噪声（循环修剪：同时刑法→刑法、并引用刑诉法→刑诉法）
_LAW_PREFIX_NOISE = re.compile(
    r"^(?:同时|此外|而且|并且|并|另|另据|又|及|或|且|但|而|则|即|也|还|再|"
    r"依照|依据|根据|参照|按照|关于|对于|适用|符合|违反|触犯|引用|参见|援引|"
    r"如|若|凡|据|按|涉|涉及|我国|本)"
)


def normalize_law(law: str) -> str:
    """规范法律名：去书名号/空白/「中华人民共和国」前缀，修剪修饰语噪声，应用别名表。"""
    law = (law or "").strip().strip("《》〈〉「」").replace(" ", "").replace("\u3000", "")
    law = law.replace("中华人民共和国", "")
    prev = None
    while prev != law:
        prev = law
        law = _LAW_PREFIX_NOISE.sub("", law)
    return _LAW_ALIAS.get(law, law)


def statute_key(law: str, art: str, alt: str = "") -> str:
    """法条唯一键："刑法|第266条"。无法解析条文号返回空串。"""
    n = chn_to_int(art)
    if not law or n is None:
        return ""
    return f"{normalize_law(law)}|第{n}条{alt or ''}"


def extract_citations(text: str) -> List[dict]:
    """从文本中提取全部法条引用（保序去重，同一 key 只留首个 raw 写法）。"""
    out: List[dict] = []
    seen: set = set()
    if not text:
        return out
    for m in _CITE_RE.finditer(text):
        law = m.group("law") or m.group("law2") or ""
        alt = m.group("alt") or ""
        key = statute_key(law, m.group("art"), alt)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({
            "raw": m.group(0).strip(),
            "law": normalize_law(law),
            "article": chn_to_int(m.group("art")),
            "alt": alt,
            "key": key,
        })
    return out


# ---------------- 已知法条索引 ----------------

def _keys_from_name(name: str) -> List[str]:
    """从法条名（如《刑法》第266条 / 《中华人民共和国刑法》第232条）提取 key。
    返回列表以兼容一个名字里含多个引用的极端情况。"""
    if not name:
        return []
    keys = []
    for m in _TITLE_CITE_RE.finditer(name):
        k = statute_key(m.group("law"), m.group("art"), m.group("alt") or "")
        if k:
            keys.append(k)
    # 兜底：整串直接当 key 试一次（处理「刑法 第266条」等无书名号写法）
    if not keys:
        m = _CITE_RE.search(name)
        if m:
            k = statute_key(m.group("law") or m.group("law2") or "",
                            m.group("art"), m.group("alt") or "")
            if k:
                keys.append(k)
    return keys


def known_statute_index(case_statutes: Optional[List[dict]] = None) -> Dict[str, dict]:
    """构建「案件卷宗法条 + 内置法条库」的已知法条索引。
    key -> {name, source}，source ∈ {case, builtin}；案件法条优先。"""
    index: Dict[str, dict] = {}
    # 内置法条库（延迟导入避免循环依赖）
    try:
        from app.legal.knowledge import BUILTIN
        for e in BUILTIN:
            for k in _keys_from_name(e.get("title", "")):
                index.setdefault(k, {"name": e.get("title", ""), "source": "builtin"})
    except Exception:  # noqa: BLE001 — 内置库异常不阻断核查
        pass
    for s in case_statutes or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name") or s.get("topic") or "")
        for k in _keys_from_name(name):
            index[k] = {"name": name, "source": "case"}
    return index


def check_text(text: str, index: Dict[str, dict]) -> dict:
    """核查单段文本中的全部法条引用。"""
    cites = extract_citations(text)
    results = []
    for c in cites:
        hit = index.get(c["key"])
        results.append({
            "raw": c["raw"],
            "key": c["key"],
            "status": "verified" if hit else "unverified",
            "source": hit["source"] if hit else None,
            "ref_name": hit["name"] if hit else None,
        })
    verified = sum(1 for r in results if r["status"] == "verified")
    return {
        "citations": results,
        "total": len(results),
        "verified": verified,
        "unverified": len(results) - verified,
    }


def check_texts(texts: List[str], case_statutes: Optional[List[dict]] = None) -> dict:
    """批量核查多段文本（专家发言 / 裁决全文 / QA 记录），输出汇总。"""
    index = known_statute_index(case_statutes)
    results = [check_text(t, index) for t in (texts or [])[:200]]
    all_cites: Dict[str, dict] = {}
    for r in results:
        for c in r["citations"]:
            cur = all_cites.get(c["key"])
            if cur is None or (cur["status"] == "unverified" and c["status"] == "verified"):
                all_cites[c["key"]] = c
    cites = list(all_cites.values())
    return {
        "results": results,
        "citations": cites,
        "stats": {
            "texts": len(results),
            "unique_citations": len(cites),
            "verified": sum(1 for c in cites if c["status"] == "verified"),
            "unverified": sum(1 for c in cites if c["status"] == "unverified"),
            "known_statutes": len(index),
        },
    }
