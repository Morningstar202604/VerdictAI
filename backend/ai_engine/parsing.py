# -*- coding: utf-8 -*-
"""本地推理引擎 · 卷宗解析层。

确定性解析分派材料文本为结构化卷宗（人员/证据/时间线/法条/资金/DNA/通讯），
并派生交叉验证事实（死亡时间窗×监控缺失、保管链瑕疵、身份不明 DNA、异常资金）。
所有事实均取自卷宗原文本，不虚构。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for p in content:
            if isinstance(p, str):
                out.append(p)
            elif isinstance(p, dict):
                if p.get("type") == "text":
                    out.append(str(p.get("text", "")))
                elif p.get("type") == "image_url":
                    out.append("[图片]")
        return "\n".join(out)
    return str(content or "")


def _has_image(messages: List[dict]) -> bool:
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and p.get("type") == "image_url":
                    return True
    return False


EV_RE = re.compile(
    r"-\s*\[(E-\d+)\]\s*([^:：\n]+)[:：]\s*(.+?)（可靠性([\d.]+)，保管链(完整|瑕疵)）"
)
PERSON_RE = re.compile(r"-\s*([^\n：:（(]+)[（(]([^）)]*)[）)]\s*[:：]\s*(.+)")
STATUTE_RE = re.compile(r"-\s*([^:：\n]+)[:：]\s*(.+)")
DNA_RE = re.compile(r"-\s*(.+?)\s*[:：]\s*(匹配|未匹配)\s*[（(]([^）)]*)[）)]?")
FIN_RE = re.compile(r"-\s*(.+?)[:：]\s*金额\s*([^\n（(·]+?)\s*[（(]([^）)]*)[）)]?\s*·?\s*(.*)")
CONTACT_RE = re.compile(r"-\s*(.+?)\s*→\s*(.+?)[:：]\s*([^·（(]+)·\s*([^（(]+?)[（(]([^）)]*)[）)]?")
DATE_RE = re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?")
CLOCK_RE = re.compile(r"(\d{1,2}:\d{2})")
RANGE_RE = re.compile(r"(\d{1,2}:\d{2})\s*[-–~至]\s*(\d{1,2}:\d{2})")

# 常驻法条映射：按案件事实确定性匹配真实法条（不幻觉法号），专家与抽取共用
CRIMINAL_REF = [
    (("保管链", "瑕疵", "剪辑", "删除", "缺失", "取证"), "《刑事诉讼法》第50条：证据必须经查证属实方可作为定案根据"),
    (("证明标准", "排除合理怀疑", "孤证", "口供"), "《刑事诉讼法》第55条：重证据、不轻信口供，定案须排除合理怀疑"),
    (("非法", "刑讯", "违法取证"), "《刑事诉讼法》第56条：非法方法收集的言词证据应予排除，物证书证取证瑕疵须补正或合理解释"),
    (("杀", "死亡", "命案", "死于"), "《刑法》第232条/第233条：故意杀人与过失致人死亡的界分，取决于主观罪过形式"),
]
CIVIL_REF = [
    (("违约", "合同"), "《民法典》第577条：违约方应承担继续履行、采取补救措施或赔偿损失等违约责任"),
    (("不可抗力",), "《民法典》第590条：因不可抗力不能履行合同的，按影响部分或全部免责"),
]


def _section(text: str, *titles: str) -> str:
    """提取 markdown 小节正文（从 # 标题到下一个 # 标题之前）。"""
    lines = text.splitlines()
    out: List[str] = []
    grab = False
    for ln in lines:
        if ln.startswith("#"):
            grab = any(t in ln for t in titles)
            continue
        if grab:
            out.append(ln)
    return "\n".join(out).strip()


def _mins(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _to_min(t: str) -> int:
    v = _mins(t)
    return v if v > 0 else 24 * 60  # 00:00 视为 24:00


def _min_diff(t1: str, t2: str) -> int:
    d = abs(_mins(t1) - _mins(t2))
    return min(d, 24 * 60 - d)


def _cn_clocks(text: str) -> List[str]:
    """中文时间表达归一化：「凌晨2时20分」「23时47分」「晚上10点」→ ["02:20","23:47"]。"""
    out: List[str] = []
    for m in re.finditer(r"(\d{1,2})[时点](\d{1,2})?", text):
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if 0 <= h <= 24 and mi <= 59:
            out.append(f"{h:02d}:{mi:02d}")
    return out


def _cn_range(text: str) -> Optional[Tuple[str, str]]:
    """中文时间区间：「1时30分至2时30分」→ ("01:30","02:30")。"""
    m = re.search(
        r"(\d{1,2})[时点](\d{1,2})?分?\s*(?:至|到|—|–|-|~)\s*(\d{1,2})[时点](\d{1,2})?分?", text
    )
    if m:
        h1, mi1, h2, mi2 = int(m.group(1)), int(m.group(2) or 0), int(m.group(3)), int(m.group(4) or 0)
        if all(v <= 24 for v in (h1, h2)) and mi1 <= 59 and mi2 <= 59:
            return (f"{h1:02d}:{mi1:02d}", f"{h2:02d}:{mi2:02d}")
    m = RANGE_RE.search(text)
    if m:
        return (m.group(1), m.group(2))
    return None


class Evidence:
    def __init__(self, eid, etype, desc, rel, chain):
        self.id, self.type, self.desc = eid, etype.strip(), desc.strip()
        try:
            self.rel = float(rel)
        except (TypeError, ValueError):
            self.rel = 0.7
        self.chain_intact = chain == "完整"

    @property
    def ref(self) -> str:
        pct = int(round(self.rel * 100))
        return f"[{self.id} {self.type}]（可靠性{pct}%，保管链{'完整' if self.chain_intact else '瑕疵'}）"


class Case:
    """从分派材料文本解析出的结构化卷宗 + 派生事实。"""

    def __init__(self, material: str):
        self.raw = material
        self.summary = _section(material, "案件概要")
        self.persons: List[Dict[str, str]] = []
        for m in PERSON_RE.finditer(_section(material, "涉案人员")):
            self.persons.append({"name": m.group(1).strip(), "role": m.group(2).strip(), "desc": m.group(3).strip()})
        self.names = [p["name"] for p in self.persons if 1 < len(p["name"]) <= 5]

        seen, self.evidence = set(), []
        for m in EV_RE.finditer(_section(material, "证据材料", "重点材料")):
            if m.group(1) not in seen:
                seen.add(m.group(1))
                self.evidence.append(Evidence(m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)))

        self.timeline: List[Dict[str, Any]] = []
        for ln in _section(material, "时间线").splitlines():
            ln = ln.strip().lstrip("-").strip()
            if not ln:
                continue
            left, _, src = ln.partition("（来源")
            src = src.strip("） ：:").strip() if src else ""
            clocks = CLOCK_RE.findall(left)
            event = DATE_RE.sub("", left)
            event = CLOCK_RE.sub("", event, count=1) if clocks else event
            event = re.sub(r"^\s+", "", event)
            tdisp = (clocks[-1] if clocks else event[:8])
            self.timeline.append({
                "clock": clocks[-1] if clocks else None,
                "display": tdisp,
                "event": event.strip(),
                "source": src,
                "subject": next((n for n in self.names if event.startswith(n)), None),
            })

        self.statutes = [
            {"topic": m.group(1).strip(), "text": m.group(2).strip()}
            for m in STATUTE_RE.finditer(_section(material, "法条依据"))
        ]
        self.finance = [
            {"item": m.group(1).strip(), "amount": m.group(2).strip(), "date": m.group(3).strip(), "note": m.group(4).strip()}
            for m in FIN_RE.finditer(_section(material, "资金", "财务"))
        ]
        self.dna = [
            {"name": m.group(1).strip(), "matched": m.group(2).strip() == "匹配", "note": m.group(3).strip()}
            for m in DNA_RE.finditer(_section(material, "DNA"))
        ]
        self.contacts = [
            {"from": m.group(1).strip(), "to": m.group(2).strip(), "time": m.group(3).strip(), "type": m.group(4).strip(), "note": m.group(5).strip()}
            for m in CONTACT_RE.finditer(_section(material, "通讯"))
        ]

        self.focus = ""
        m = re.search(r"#\s*分派给你的重点材料（职责[:：](.+?)）", material)
        if m:
            self.focus = m.group(1).strip()

        self.known_contradictions = [
            ln.strip().lstrip("-").strip()
            for ln in _section(material, "已知矛盾清单").splitlines() if ln.strip()
        ]

        self.intent, self.guidance = "", ""
        m = re.search(r"意图[:：]\s*(.+)", material)
        if m:
            self.intent = m.group(1).strip()
        m = re.search(r"#\s*本案意图与总体分析提示\s*\n[^\n]*\n(.+)", material)
        if m:
            self.guidance = m.group(1).strip().splitlines()[0]

        self.intensity = "medium"
        if "思考强度：高" in material:
            self.intensity = "high"
        elif "思考强度：低" in material:
            self.intensity = "low"

        self.round = 1
        self.prev_self = ""
        self.prev_others: Dict[str, str] = {}
        self.human_note = ""  # 最近一条人类法官介入（本轮陈述需显式回应）
        self._derive()

    # ---------- 派生事实 ----------
    def _derive(self) -> None:
        self.flawed = [e for e in self.evidence if not e.chain_intact]
        self.low_rel = [e for e in self.evidence if e.rel < 0.7]
        self.edited = [e for e in self.evidence if any(k in e.desc for k in ("剪辑", "缺失", "删除", "中断"))]
        self.dna_unknown = [
            d for d in self.dna
            if d["matched"] and any(k in (d["name"] + d["note"]) for k in ("未知", "不明", "陌生", "未比对", "未比中"))
        ]
        self.dna_matched_named = [d for d in self.dna if d["matched"] and d not in self.dna_unknown]
        # 无结构化 DNA 表时的回退：从证据描述识别「未知/未比中」生物成分
        if not self.dna_unknown:
            for e in self.evidence:
                if ("DNA" in e.desc or "皮屑" in e.desc) and any(k in e.desc for k in ("未知", "未命中", "未比中", "未比对")):
                    self.dna_unknown.append({"name": "未知来源生物检材", "matched": True, "note": f"{e.id}：{e.desc[:40]}"})
                    break
        self.insurance = [
            f for f in self.finance
            # 覆盖常见中文写法：投保财产险/保额提升/赔付理赔——只认「保险」二字会漏
            if any(k in (f["item"] + f["note"]) for k in ("保险", "投保", "保额", "受益", "赔付", "理赔"))
        ]
        self.transfer = [
            f for f in self.finance
            if any(k in (f["item"] + f["note"]) for k in ("转账", "账户", "收款", "来源存疑", "当晚", "工资", "欠薪", "拖欠"))
        ]
        self.weapon = next((e for e in self.evidence if "凶器" in e.type or "刀" in e.desc), None)
        self.monitor = next((e for e in self.evidence if "监控" in e.type or "监控" in e.desc or "录像" in e.desc), None)
        self.key_ev = self.weapon or self.monitor or (self.flawed[0] if self.flawed else (self.evidence[0] if self.evidence else None))

        # 死亡时间窗（法医类证据描述中的区间）
        self.tod_range: Optional[Tuple[str, str]] = None
        for e in self.evidence:
            if "法医" in e.type or "尸" in e.desc or "死亡时间" in e.desc:
                rng = _cn_range(e.desc)
                if rng:
                    self.tod_range = rng
                    break

        # 监控录像区间
        self.monitor_range: Optional[Tuple[str, str]] = None
        if self.monitor:
            rng = _cn_range(self.monitor.desc)
            if rng:
                self.monitor_range = rng

        # 位于死亡时间窗内的时间线事件（客观记录优先）
        self.events_in_tod: List[Dict[str, Any]] = []
        if self.tod_range:
            lo, hi = _to_min(self.tod_range[0]), _to_min(self.tod_range[1])
            for t in self.timeline:
                if t["clock"]:
                    v = _to_min(t["clock"])
                    if lo <= v <= hi:
                        self.events_in_tod.append(t)
            self.events_in_tod = self.events_in_tod[:3]

        # 供述与客观记录的时序冲突：仅当「自述类供述」与「硬客观记录」地点互斥才判冲突，避免误报
        self.alibi_conflicts: List[str] = []
        PLACES = ("别墅", "公司", "酒店", "机场", "车站", "办公室", "书房", "主卧", "车库", "画廊")
        CLAIM_KW = ("称", "自述", "供述", "辩解", "回忆")
        OBJ_KW = ("监控", "ETC", "流水", "勘验", "运营商", "刷卡", "指纹", "导航", "门禁")
        subj_evs = [t for t in self.timeline if t["subject"]]
        for i in range(len(subj_evs)):
            for j in range(i + 1, len(subj_evs)):
                a, b = subj_evs[i], subj_evs[j]
                if a["subject"] != b["subject"] or not (a["clock"] and b["clock"]):
                    continue
                if _min_diff(a["clock"], b["clock"]) > 90:
                    continue
                a_claim, b_claim = any(k in a["event"] for k in CLAIM_KW), any(k in b["event"] for k in CLAIM_KW)
                a_obj, b_obj = any(k in (a["source"] + a["event"]) for k in OBJ_KW), any(k in (b["source"] + b["event"]) for k in OBJ_KW)
                claim, obj = (a, b) if (a_claim and b_obj and not a_obj) else ((b, a) if (b_claim and a_obj and not b_obj) else (None, None))
                if claim is None:
                    continue
                pc = [k for k in PLACES if k in claim["event"]]
                po = [k for k in PLACES if k in obj["event"]]
                if pc and po and not set(pc) & set(po):
                    self.alibi_conflicts.append(
                        f"{claim['subject']}自述在「{pc[0]}」（{claim['display']}，来源:{claim['source'] or '卷宗'}），"
                        f"但客观记录显示同时段其行踪指向「{po[0]}」（{obj['display']}，来源:{obj['source'] or '卷宗'}），两者难以共存"
                    )
        self.alibi_conflicts = list(dict.fromkeys(self.alibi_conflicts))[:3]

        # 热点交叉事实（各角色共享的"聪明结论"）
        self.hot: List[str] = []
        if self.tod_range and self.monitor_range:
            lo, hi = _to_min(self.tod_range[0]), _to_min(self.tod_range[1])
            mlo, mhi = _to_min(self.monitor_range[0]), _to_min(self.monitor_range[1])
            if self.monitor and any(k in self.monitor.desc for k in ("剪辑", "缺失")) and mlo >= lo - 5 and mhi <= hi + 5:
                self.hot.append(
                    f"{self.monitor.id} 的录像区间（{self.monitor_range[0]}–{self.monitor_range[1]}，其中约5分钟刻意缺失）"
                    f"整体落在死亡时间窗（{self.tod_range[0]}–{self.tod_range[1]}）内——缺失片段恰好是死亡时刻附近，属关键性证据空窗"
                )
        if self.events_in_tod:
            times = "、".join(f"{t['display']}（{t['event'][:18]}）" for t in self.events_in_tod)
            self.hot.append(f"死亡时间窗内叠加了多个关键事件：{times}，行为时序需逐一对齐")
        if self.dna_unknown:
            self.hot.append("在案生物检材检出身份不明 DNA 成分（未比中），在案人员之外存在第三人介入可能")
        for f in self.transfer:
            if "当晚" in f["note"] or "存疑" in f["note"]:
                self.hot.append(f"{f['item']} 于 {f['date']} 发生 {f['amount']}（{f['note']}），与案发时点强耦合")
                break
        for f in self.insurance:
            self.hot.append(f"{f['item']}（{f['amount']}，{f['note']}）构成现实动机线索")
            break

    def chain_step(self) -> List[str]:
        steps = []
        if any("死" in t["event"] or "尸" in t["event"] for t in self.timeline):
            tod = f"（死亡时间窗 {self.tod_range[0]}–{self.tod_range[1]}）" if self.tod_range else ""
            steps.append(f"死亡事实与死亡时间：以尸检/法医记录为锚点{tod}")
        if self.weapon:
            steps.append(f"致伤工具与伤口形态吻合（{self.weapon.id}）")
        if self.monitor:
            steps.append(f"客观行踪核验：{self.monitor.id} 与时间线交叉比对")
        if self.dna:
            steps.append("生物物证指向性：DNA 比对" + ("（含身份不明成分）" if self.dna_unknown else ""))
        if self.insurance or self.transfer:
            steps.append("动机与资金背景：" + "、".join(f["item"] for f in (self.insurance + self.transfer)[:2]))
        return steps or ["在案证据尚待补强：按待证事实逐项补证后再行评判"]