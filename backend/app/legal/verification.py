# -*- coding: utf-8 -*-
"""法条引用核验（B 阶段）：把裁决里的 law_citations / sentencing 与内置法条库做
确定性比对，标记「已核验 / 库内该法未收录此条 / 法名不在库内（待人工核验）」，
以及量刑建议是否落在罪名法定刑区间内。

设计约束（对标实务）：
- 内置库只收录编号稳定的核心条文，未命中 ≠ 虚构，只降级为「待人工核验」；
  法名在库但条号不在，标记「条文未收录」并提示核对——这是虚构引用的典型形态。
- 纯确定性规则，不依赖 LLM；核验结果作为标记附加到裁决，供人类法官复核。
"""
from __future__ import annotations

import re
from typing import Dict, List

from app.legal.knowledge import (
    article_numbers_of_law,
    canon_law,
    cn_to_int,
    find_statute,
    find_statute_by_charge,
    parse_article_no,
)

# 「X年 / X个月 / 无期徒刑 / 死刑」刑期抽取
_YEARS_RE = re.compile(r"(\d+|[一二两三四五六七八九十百]+)\s*年")
_MONTHS_RE = re.compile(r"(\d+|[一二两三四五六七八九十]+)\s*个?月")


def _parse_years(text: str) -> float | None:
    """从量刑文本抽出代表性刑期（年）；「五年以上十年以下」取下限。"""
    if not text:
        return None
    if "无期" in text or "死刑" in text:
        return float("inf")
    m = _YEARS_RE.search(text)
    if m:
        raw = m.group(1)
        n = int(raw) if raw.isdigit() else cn_to_int(raw)
        if n > 0:
            return float(n)
    m = _MONTHS_RE.search(text)
    if m:
        raw = m.group(1)
        n = int(raw) if raw.isdigit() else cn_to_int(raw)
        if n > 0:
            return n / 12.0
    return None


def verify_law_citations(citations: List[dict]) -> List[dict]:
    """逐条核验 law_citations。返回 [{title, article, status, note}]：
    status ∈ verified | not_in_library | unknown_law"""
    out: List[dict] = []
    for c in citations or []:
        if not isinstance(c, dict):
            continue
        title = str(c.get("title") or "").strip()
        article = str(c.get("article") or "").strip()
        canon = canon_law(title)
        if not canon:
            out.append({"title": title, "article": article, "status": "unknown_law",
                        "note": "法名不在内置法条库（可能正确，建议人工核对条文原文）"})
            continue
        no = parse_article_no(article)
        if no < 0:
            out.append({"title": title, "article": article, "status": "unknown_law",
                        "note": f"《{canon}》在库，但引用未写明条号，无法定位核验"})
            continue
        hit = find_statute(canon, article)
        if hit:
            out.append({"title": title, "article": f"第{no}条", "status": "verified",
                        "note": "与内置条文原文比对通过", "ref_id": hit.get("id")})
        else:
            known = article_numbers_of_law(canon)
            hint = f"库内收录条号：{'、'.join(f'第{k}条' for k in known)}" if known else "库内该法暂无收录条文"
            out.append({"title": title, "article": f"第{no}条", "status": "not_in_library",
                        "note": f"《{canon}》第{no}条未收录，疑似编号有误——{hint}，请人工核对"})
    return out


def verify_sentencing(sentencing: str, citations: List[dict],
                      verdict_text: str = "") -> Dict | None:
    """量刑建议 vs 罪名法定刑区间。罪名定位：law_citations 中的罪名条文优先，
    其次从量刑/裁决全文匹配库内罪名。无罪名或无刑期可抽时返回 None（不产噪声）。"""
    text = f"{sentencing or ''} {verdict_text or ''}"
    statute = None
    for c in citations or []:
        if not isinstance(c, dict):
            continue
        hit = find_statute(str(c.get("title") or ""), str(c.get("article") or ""))
        if hit and hit.get("penalty_range"):
            statute = hit
            break
    if not statute:
        for e_key in ("故意杀人", "过失致人死亡"):
            if e_key in text:
                charge_hit = find_statute_by_charge(e_key)
                if charge_hit and charge_hit.get("penalty_range"):
                    statute = charge_hit
                    break
    if not statute:
        return None
    years = _parse_years(sentencing or "")
    rng = statute.get("penalty_range") or {}
    lo = rng.get("min_years", 0)
    hi = rng.get("max_years")
    kinds = rng.get("kinds") or []
    base = {
        "charge": statute.get("charge") or statute.get("title"),
        "statute": statute.get("title"),
        "range_text": f"{lo}年至{'无期/死刑' if hi is None else str(hi) + '年'}" +
                      (f"（刑种：{'、'.join(kinds)}）" if kinds else ""),
        "suggested_years": None if years is None or years == float("inf") else years,
    }
    if years is None:
        return {**base, "ok": True, "note": "未从量刑建议中解析出明确刑期，不作区间判定"}
    if years == float("inf"):
        if "无期" in kinds or "死刑" in kinds or hi is None:
            return {**base, "ok": True, "note": "无期/死缓类建议在该罪名法定刑种类内"}
        return {**base, "ok": False, "note": f"建议无期/死刑超出「{base['charge']}」法定刑种类（{base['range_text']}）"}
    if hi is not None and years > hi:
        return {**base, "ok": False, "note": f"建议 {years:g} 年超出法定上限 {hi} 年"}
    if years < lo:
        return {**base, "ok": False, "note": f"建议 {years:g} 年低于法定下限 {lo} 年"}
    return {**base, "ok": True, "note": "量刑建议落在该罪名法定刑区间内"}


def run_verification(verdict: Dict) -> Dict:
    """对一份裁决做引用+量刑核验，返回可挂到 selfcheck 的结构。"""
    cites = verdict.get("law_citations") or []
    results = verify_law_citations(cites)
    issues: List[str] = []
    for r in results:
        if r["status"] == "not_in_library":
            issues.append(f"疑似虚构/错误引用：{r['note']}")
        elif r["status"] == "unknown_law":
            issues.append(f"引用待人工核验：{r['title'] or '未写法律名'} {r['article'] or ''}（{r['note']}）")
    sent = verdict.get("sentencing") or ""
    sent_check = None
    if sent:
        sent_check = verify_sentencing(
            sent, cites, verdict_text=str(verdict.get("ruling") or ""))
        if sent_check and not sent_check.get("ok"):
            issues.append(f"量刑越界：{sent_check['note']}")
    return {
        "citations": results,
        "sentencing_check": sent_check,
        "issues": issues,
        "verified": sum(1 for r in results if r["status"] == "verified"),
        "flagged": sum(1 for r in results if r["status"] != "verified"),
    }
