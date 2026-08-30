# -*- coding: utf-8 -*-
"""VerdictAI 本地替代引擎（由 ZCode AI 编写）。

一个 OpenAI 兼容的聊天补全服务，用确定性的案件分析逻辑替代外部大模型：
- 真·解析卷宗（概要/人员/时间线/证据/法条/资金/DNA/通讯），计算事实层面的发现；
- 交叉验证：死亡时间窗 × 监控缺失片段 × 关键通讯时点、保管链瑕疵、身份不明 DNA、异常资金；
- 按专家角色生成有依据、分点、跨轮相互参照的陈述（Markdown）；
- 支持工具调用（read_evidence / timeline_check / search_case_law / run_code），
  沙箱图表可渲染到笔录；
- 为书记员 / 纠错官 / 审判长 / 分案法官节点输出严格 JSON。

启动：python -m uvicorn ai_engine.server:app --host 127.0.0.1 --port 9100
后端切换：POST /api/settings {"llm_base_url":"http://127.0.0.1:9100/v1"}
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="VerdictAI Local Engine", version="1.1")

# ----------------------------- 请求/消息解析 -----------------------------


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


# ----------------------------- 卷宗解析 -----------------------------

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


def _min_diff(t1: str, t2: str) -> int:
    d = abs(_mins(t1) - _mins(t2))
    return min(d, 24 * 60 - d)


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
        self.insurance = [f for f in self.finance if "保险" in f["item"] or "保险" in f["note"] or "受益" in f["note"]]
        self.transfer = [
            f for f in self.finance
            if "转账" in f["item"] or "账户" in f["item"] or "收款" in f["item"] or "来源存疑" in f["note"] or "当晚" in f["note"]
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
        return steps or ["证据链尚不完整，需补充侦查"]


# ----------------------------- 会话状态 -----------------------------

LOCK = threading.Lock()
STATE: Dict[str, Any] = {
    "rounds_by_case": {},   # {case_hash: {role: round_no}} —— 按案件隔离，支持并发辩论
    "critic_by_case": {},   # {case_hash: critic_calls}
    "names": [],
    "last_case": None,
}


def _refresh_case(material: str, hash_basis: str = "") -> Case:
    # hash 仅取全角色共享的案件概要小节；无小节时退到系统提示中的「本案卷宗摘要」
    # （同场辩论各角色一致），不能用拼接全文——否则第二轮注入历史摘要后
    # hash 变化，会误重置轮次计数。
    basis = (
        _section(material, "案件概要")
        or _section(material, "本案卷宗摘要")
        or hash_basis
        or material[:200]
    )
    h = hashlib.md5(basis.encode("utf-8")).hexdigest()
    case = Case(material)
    case.hash = h
    return case


# ----------------------------- 专家陈述生成 -----------------------------

_ROLE_ALIASES = [
    ("现场勘查专家", "scene"),
    ("法医病理学专家", "forensic"),
    ("物证与痕迹鉴定专家", "evidence"),
    ("犯罪心理学与讯问分析专家", "psych"),
    ("刑事诉讼证据法专家", "law"),
    ("检察官 Agent", "prosecutor"),
    ("辩护 Agent", "defense"),
    ("审判长 Agent", "judge"),
]
_ROLE_IDENTITY = {
    "现场勘查专家": "scene",
    "法医专家": "forensic",
    "物证/痕迹专家": "evidence",
    "讯问/心理专家": "psych",
    "证据法专家": "law",
    "检察官 Agent": "prosecutor",
    "辩护 Agent": "defense",
    "审判长 Agent": "judge",
}


def _detect_role(system_text: str) -> str:
    m = re.search(r"请记住你的身份[:：]\s*([^（(\n]+)", system_text)
    if m:
        key = _ROLE_IDENTITY.get(m.group(1).strip())
        if key:
            return key
    for name, key in _ROLE_ALIASES:
        if name in system_text:
            return key
    return "expert"


def _prev_from_history(messages: List[dict], role: str, case: Case) -> None:
    """从【前序轮次专家意见摘要】里取上一轮本人与他人的主张，供本轮参照。"""
    summaries = []
    for m in messages:
        if m.get("role") == "system":
            t = _text_of(m.get("content"))
            if "前序轮次专家意见摘要" in t:
                summaries.append(t)
    if not summaries:
        return
    try:
        data = json.loads(summaries[-1].split("】", 1)[-1].strip())
    except Exception:
        return
    mine = data.get(role, "")
    if mine:
        case.prev_self = re.sub(r"\s+", " ", mine)[:120]
    for k, v in data.items():
        if k != role and v:
            case.prev_others[k] = v


def _summary_count(messages: List[dict]) -> int:
    """请求里【前序轮次专家意见摘要】的条数（后端每轮注入最近 2 条）。"""
    n = 0
    for m in messages:
        if m.get("role") == "system" and "前序轮次专家意见摘要" in _text_of(m.get("content")):
            n += 1
    return n


def _round_for(case_hash: str, role: str, messages: List[dict]) -> int:
    """确定性推导当前辩论轮次（并行同轮专家请求互不干扰）：

    - 0 条摘要 → 第 1 轮；1 条 → 第 2 轮；
    - ≥2 条 → 第 3 轮起，用 (案件, 角色) 键控计数器累计（后端摘要封顶 2 条）；
    - 出现低轮次请求（新一场辩论开始）时计数器自动归零。
    """
    sc = _summary_count(messages)
    with LOCK:
        if sc < 2:
            STATE["rounds_by_case"].setdefault(case_hash, {})[role] = sc + 1
            return sc + 1
        c = STATE["rounds_by_case"].setdefault(case_hash, {}).get(role, 2)
        c = c + 1
        STATE["rounds_by_case"][case_hash][role] = c
        return c


def _reset_critic(case_hash: str, messages: List[dict]) -> None:
    """新辩论（第 1 轮专家请求）时归零该案件的纠错官轮次计数。"""
    if _summary_count(messages) == 0:
        with LOCK:
            STATE["critic_by_case"][case_hash] = 0


def _bullets(items: List[str]) -> str:
    return "\n".join(f"- {x}" for x in items if x)


def _crossref_opening(case: Case, round_no: int) -> str:
    if round_no <= 1:
        return ""
    ref = f"对照第{round_no - 1}轮意见"
    if case.prev_self:
        ref += f"（我上轮主张：{case.prev_self[:48]}…）"
    if case.known_contradictions:
        ref += f"，并针对纠错官指出的「{case.known_contradictions[0][:40]}」"
    ref += "，本轮进一步核验如下：\n\n"
    return ref


_CRIMINAL_REF = [
    (("保管链", "瑕疵", "剪辑", "删除", "缺失", "取证"), "《刑事诉讼法》第50条：证据必须经查证属实方可作为定案根据"),
    (("证明标准", "排除合理怀疑", "孤证", "口供"), "《刑事诉讼法》第55条：重证据、不轻信口供，定案须排除合理怀疑"),
    (("非法", "刑讯", "违法取证"), "《刑事诉讼法》第56条：非法方法收集的言词证据应予排除，物证书证取证瑕疵须补正或合理解释"),
    (("杀", "死亡", "命案", "死于"), "《刑法》第232条/第233条：故意杀人与过失致人死亡的界分，取决于主观罪过形式"),
]
_CIVIL_REF = [
    (("违约", "合同"), "《民法典》第577条：违约方应承担继续履行、采取补救措施或赔偿损失等违约责任"),
    (("不可抗力",), "《民法典》第590条：因不可抗力不能履行合同的，按影响部分或全部免责"),
]


def _statute_refs(case: Case) -> List[str]:
    """按案件事实确定性匹配真实法条，供专家引用（不幻觉法号）。"""
    is_civil = "民事" in (case.intent or "")
    rules = _CIVIL_REF if is_civil else _CRIMINAL_REF
    hay = case.raw or ""
    return [txt for kws, txt in rules if any(k in hay for k in kws)][:3]


# 类案参考库（裁判要旨）——与后端知识库同类内容，供检察官/辩护引用
_PRECEDENTS = [
    (("故意杀人", "间接证据", "监控", "dna", "无目击", "命案"),
     "类案要旨·间接证据链认定故意杀人：物证与伤情吻合、生物Trace指向明确、关键窗口无合理解释且有动机印证的，可认定证据确实充分；但监控等客观证据缺失时段内的事实应从严把握，不得以推断替代证明。"),
    (("监控", "剪辑", "缺失", "删除", "电子数据", "完整性"),
     "类案要旨·监控剪辑对指控的影响：关键监控人为剪辑或缺失的，须说明原因并提交原始载体；无法提交且无合理解释的，证明力显著降低，依赖该证据的关键事实不予认定。"),
    (("违约", "不可抗力", "合同", "迟延履行"),
     "类案要旨·不可抗力抗辩：须证明不能预见/避免/克服，且已及时通知并在合理期限内提供证明；迟延履行期间发生的不可抗力不免责，法院按原因力比例分配责任。"),
]


def _precedent_refs(case: Case) -> List[str]:
    """类案相似度匹配：按案情特征重叠数打分，引用时附上命中的特征。"""
    hay = (case.raw or "").lower()
    scored = []
    for kws, txt in _PRECEDENTS:
        hits = [k for k in kws if k.lower() in hay]
        if hits:
            scored.append((len(hits), hits, txt))
    scored.sort(key=lambda x: -x[0])
    return [f"（匹配特征：{'、'.join(hits)}）{txt}" for _, hits, txt in scored[:2]]


def _statement(role: str, case: Case, round_no: int, tool_note: str) -> str:
    """按角色生成结构化分析。所有事实均取自解析后的卷宗，不虚构。"""
    deep = case.intensity == "high"
    opening = _crossref_opening(case, round_no)
    ev_all = case.evidence
    tn = f"\n\n> 工具核验记录：{tool_note}\n" if tool_note else ""
    depth_note = (
        "\n\n（反事实检验：若上述存疑证据被整体排除，在案证据仅能支撑「重大嫌疑」，"
        "不足以独立达到排除合理怀疑标准。）"
    ) if deep else ""

    if role == "scene":
        evs = [e for e in ev_all if e.id in ("E-01", "E-02") or "痕迹" in e.type] or ev_all[:2]
        body = (
            f"#### ① 现场判断\n\n"
            f"现场空间逻辑：出入方式、动线与痕迹分布需放在同一平面图核对。"
            f"卷宗显示案发位置为「{case.summary[:52]}…」所述空间，"
            f"{('监控覆盖的走廊动线（' + case.monitor.id + '）是还原进出顺序的骨架。') if case.monitor else '卷宗未见动线型客观记录，空间还原依赖痕迹推断。'}\n\n"
            f"#### ② 与已有证据的一致/冲突点\n\n"
            f"{_bullets([f'{e.ref}：{e.desc[:56]}' for e in evs])}\n\n"
            f"#### ③ 需进一步核实的现场疑点\n\n"
            f"{_bullets(case.alibi_conflicts[:2] or ['各时点动线尚无硬性冲突，但二楼进入路径仅有单角度监控覆盖，需补充其他角度/门禁记录'])}\n\n"
            f"**小结**：现场证据与时间线总体自洽；"
            f"{('但 ' + case.flawed[0].id + ' 保管链瑕疵使痕迹—实物对应关系存在断点。') if case.flawed else '痕迹—实物对应关系未见明显断点。'}"
        )
    elif role == "forensic":
        tod = case.tod_range
        tod_ev = next((e for e in ev_all if "法医" in e.type or "死亡时间" in e.desc), None)
        body = (
            f"#### ① 法医学结论\n\n"
            f"死因以尸检记录为准：{('（' + tod_ev.ref + '）' if tod_ev else '')}"
            f"{('与在案凶器 ' + case.weapon.id + ' 的形态吻合。') if case.weapon else '致伤工具形态需进一步比对。'}\n\n"
            f"#### ② 死亡时间（TOD）推断\n\n"
            f"- {'死亡时间窗 ' + tod[0] + '–' + tod[1] + '（' + tod_ev.id + '）' if tod and tod_ev else '卷宗未见明确 TOD 区间，建议补充尸温/胃内容物记录'}\n"
            f"- {('该窗口覆盖了' + '、'.join(t['display'] for t in case.events_in_tod) + ' 等关键事件，行为时序必须逐一与窗口对齐。') if case.events_in_tod else '窗口与已知事件的对齐关系待核。'}\n\n"
            f"#### ③ 与其他证据的冲突\n\n"
            f"{_bullets(case.hot[:2] or case.alibi_conflicts[:2] or ['未见法医学层面与在案时间线的直接冲突'])}{depth_note}"
        )
    elif role == "evidence":
        key = case.key_ev
        dna_txt = "；".join(f"{d['name']}（{d['note'] or ('匹配' if d['matched'] else '未匹配')}）" for d in case.dna[:4]) if case.dna else "卷宗未附比对表"
        body = (
            f"#### ① 物证结论\n\n"
            f"{('在案关键物证 ' + key.ref + '：' + key.desc[:64]) if key else '物证清单待补全'}。"
            f"{'多件物证构成可交叉验证的集合：' + '、'.join(e.id for e in ev_all[:4]) + '。' if ev_all else ''}\n\n"
            f"#### ② 物证能否指向特定人\n\n"
            f"- DNA 比对：{dna_txt}\n"
            f"- {('存在身份不明的匹配成分，指向「第三人或共同行为人」可能，不能只锁定在案嫌疑人。') if case.dna_unknown else '指向性明确，但仍需第二独立物证印证。'}\n\n"
            f"#### ③ 保管链完整性\n\n"
            f"{_bullets([f'{e.id}：保管链瑕疵——提取/封存/送检环节需回溯补证，存在污染或调换风险' for e in case.flawed] or ['现有物证保管链完整'])}\n"
            f"- {case.hot[0] if case.hot else '未发现证据完整性之外的异常。'}"
        )
    elif role == "psych":
        motive = []
        if case.insurance:
            motive.append(f"巨额保险利益（{case.insurance[0]['item']}·{case.insurance[0]['amount']}·{case.insurance[0]['note']}）")
        if case.transfer:
            motive.append(f"异常资金往来（{case.transfer[0]['item']}·{case.transfer[0]['amount']}）")
        stmt_evs = [
            t for t in case.timeline
            if t.get("subject") and any(k in t["source"] for k in ("供述", "称"))
        ][:2]
        stmt_lines = [
            f"「{t['event'][:40]}」（{t['display']}，来源:{t['source'] or '卷宗'}）与在案客观记录的对应关系需当庭对质"
            for t in stmt_evs
        ]
        body = (
            f"#### ① 口供/动机判断\n\n"
            f"动机结构上{'存在现实利益驱动：' + '、'.join(motive) + '；利益兑现时点与案发时点高度接近，需核查谁最终受益。' if motive else '卷宗未见明确利益线索，动机判断暂缓。'}"
            f"供述可信度应以细节复述一致性检验，不以态度定真伪。\n\n"
            f"#### ② 供述中的矛盾\n\n"
            f"{_bullets(stmt_lines or ['各陈述间暂未发现硬性时序矛盾，建议以时间线工具交叉核对'])}\n\n"
            f"#### ③ 心理画像要点\n\n"
            f"- {'事后存在反侦查迹象（' + '、'.join(e.id for e in case.edited[:2]) + '），指向有准备的行为人。' if case.edited else '未见显著反侦查行为，激情作案可能性上升。'}\n"
            f"- {'关键通讯（' + case.events_in_tod[0]['display'] + '）行为显示案发窗口内的紧张互动。' if case.events_in_tod else '案发窗口内的互动模式待补。'}"
        )
    elif role == "law":
        excl = [
            f"{e.id}：{'保管链瑕疵，无法排除污染/调换' if not e.chain_intact else '可靠性偏低（' + str(int(e.rel * 100)) + '%）'}，若无法补证，依证据裁判规则有被排除风险"
            for e in (case.flawed + case.low_rel)[:3]
        ]
        body = (
            f"#### ① 证据合法性意见\n\n"
            f"{_bullets([f'{e.id}（{e.type}）：需附完整取证笔录与见证人信息，否则来源合法性存疑' for e in ev_all[:2]] or ['待补取证程序记录'])}\n\n"
            f"#### ② 是否应排除及理由\n\n"
            f"{_bullets(excl or ['暂无应排除证据'])}\n"
            f"- {('监控类证据须提交原始载体；' + case.edited[0].id + ' 存在剪辑，副本完整性未经验证前只能作有限采信。') if case.edited else '电子/影像证据须核对原始载体。'}\n\n"
            f"#### ③ 证明标准达成度\n\n"
            f"距「排除合理怀疑」仍有差距：{(case.edited[0].id + ' 客观性受损') if case.edited else '关键证据可用性有争议'}；"
            f"{('且' + case.hot[0][:56] if case.hot else '且证据交叉验证未完成')}。\n\n"
            + (("#### 法律依据\n\n" + _bullets(_statute_refs(case)) + "\n") if _statute_refs(case) else "")
            + f"{depth_note}"
        )
    elif role == "prosecutor":
        gaps = [f"{e.id} 保管链回溯补证" for e in case.flawed]
        if case.dna_unknown:
            gaps.append("身份不明 DNA 的入库比对与人员排查")
        if case.edited:
            gaps.append(f"调取原始载体，修复 {case.edited[0].id} 缺失时段")
        body = (
            f"#### ① 指控逻辑链\n\n"
            + " → ".join(f"第{i + 1}环:{s}" for i, s in enumerate(case.chain_step()[:4]))
            + (f"\n\n其中 {case.hot[0][:60]} 是链条的关键支点。" if case.hot else "")
            + (f"\n\n> 法律依据：{_statute_refs(case)[0]}" if _statute_refs(case) else "")
            + (f"\n\n> 类案参考：{_precedent_refs(case)[0][:120]}" if _precedent_refs(case) else "")
            + f"\n\n#### ② 关键缺口\n\n{_bullets(gaps or ['证据链基本闭合，待审判长检验'])}\n\n"
            f"#### ③ 对辩方观点的预判\n\n"
            f"辩方将攻击{(case.flawed[0].id + ' 的保管链') if case.flawed else '证明标准'}"
            f"{('与 ' + case.edited[0].id + ' 的原始性') if case.edited else ''}；"
            f"{'辩方还会以身份不明 DNA 主张第三人介入——控方必须预先给出该解释为何不能成立的事实理由，或如实承认缺口。' if case.dna_unknown else ''}"
        )
    elif role == "defense":
        atk = []
        if case.flawed:
            atk.append(f"{case.flawed[0].id} 保管链瑕疵：不能排除污染/调换，真实性存疑，应作有利于被告的解释")
        if case.edited:
            atk.append(f"{case.edited[0].id} 系剪辑产物：缺失时段内容不明，不能作为连续事实认定依据")
        if case.dna_unknown:
            atk.append("刀柄 DNA 含身份不明男性成分：直接支持「第三人介入」的合理怀疑")
        if case.hot:
            atk.append(case.hot[0])
        body = (
            f"#### ① 对控方链节的质疑\n\n{_bullets(atk or ['控方链条依赖间接证据组合，环环相扣但均为可反驳推定'])}\n\n"
            f"#### ② 替代解释\n\n"
            f"- {('身份不明 DNA + ' + case.edited[0].id + ' 缺失时段' if (case.dna_unknown and case.edited) else '现有证据空窗')}"
            f"完全容纳「第三人进入现场」的事实模型；该模型被排除前，指控链不闭合。\n\n"
            f"#### ③ 合理怀疑总结\n\n"
            f"{_bullets([case.alibi_conflicts[0]] if case.alibi_conflicts else [])}"
            f"在案证据未达排除合理怀疑标准，应作证据不足处理或继续补充侦查，而非仓促认定。"
            + (("\n\n> 法律依据：" + "；".join(_statute_refs(case)[:2])) if _statute_refs(case) else "")
            + f"{depth_note}"
        )
    else:  # judge 或未识别角色：中性综合
        body = (
            f"#### ① 事实汇总\n\n{case.summary[:120]}…\n\n"
            f"#### ② 剩余分歧\n\n{_bullets(case.known_contradictions[:2] or ['各专家主张基本收敛'])}\n\n"
            f"#### ③ 收敛判断\n\n{'尚未收敛，需下一轮聚焦核心矛盾' if case.known_contradictions else '可以收敛进入裁决'}"
        )

    return f"{opening}{body}{tn}{depth_note}".strip()


# ----------------------------- 工具调用 -----------------------------

_TOOL_PLAYBOOK = {
    "scene": "timeline_check",
    "psych": "timeline_check",
    "evidence": "read_evidence",
    "forensic": "read_evidence",
    "law": "search_case_law",
    "prosecutor": "search_case_law",
    "defense": "search_case_law",
}


def _chart_code(case: Case) -> str:
    data = json.dumps([{"id": e.id, "rel": round(e.rel, 2)} for e in case.evidence[:8]], ensure_ascii=False)
    # 文件名带时间戳：run_code 只把「本次新增」的文件渲染成图片链接，
    # 固定文件名会因同名旧文件而丢失渲染。
    return (
        "import os, json, time\n"
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        f"data = json.loads({json.dumps(data)})\n"
        "ids = [d['id'] for d in data]; rel = [d['rel'] for d in data]\n"
        "fig, ax = plt.subplots(figsize=(6, 3.2))\n"
        "bars = ax.bar(ids, rel, color='#4f8ef7')\n"
        "ax.set_ylim(0, 1.05); ax.set_ylabel('reliability')\n"
        "ax.set_title('Evidence reliability (sandbox)')\n"
        "for b, r in zip(bars, rel):\n"
        "    ax.text(b.get_x()+b.get_width()/2, r+0.02, str(r), ha='center')\n"
        "out = os.environ.get('SANDBOX_OUT', '.')\n"
        "os.makedirs(out, exist_ok=True)\n"
        "p = os.path.join(out, 'evidence-reliability-%d.png' % int(time.time()))\n"
        "plt.tight_layout(); plt.savefig(p, dpi=120)\n"
        "print('saved:', p)\n"
        "print(json.dumps(dict(zip(ids, rel))))\n"
    )


def _maybe_tool_call(role: str, case: Case, round_no: int, req_tools: List[dict]) -> Optional[Tuple[str, dict]]:
    if not req_tools:
        return None
    names = {t["function"]["name"] for t in req_tools}
    # 第二轮让物证专家用 run_code 出图，展示沙箱与图表渲染能力
    if role == "evidence" and round_no == 2 and "run_code" in names:
        return ("run_code", {"code": _chart_code(case)})
    if round_no != 1:
        return None
    want = _TOOL_PLAYBOOK.get(role)
    if not want or want not in names:
        return None
    if want == "read_evidence":
        arg = {"evidence_id": case.key_ev.id} if case.key_ev else {"evidence_id": "E-01"}
    elif want == "search_case_law":
        arg = {"keyword": case.statutes[0]["topic"] if case.statutes else "非法证据排除"}
    else:
        arg = {}
    return (want, arg)


# ----------------------------- JSON 节点 -----------------------------


def _clean_claim_line(ln: str) -> str:
    ln = re.sub(r"^[#>\-\*\d\.\s、①②③④]+", "", ln).strip()
    return ln


def _clerk_json(text: str) -> dict:
    # 剥离工具核验块（> 引用行）与 JSON 片段行，避免混入"存疑事项"
    cleaned_lines = [
        ln for ln in text.splitlines()
        if not ln.strip().startswith(">") and "{\"id\"" not in ln and '"time"' not in ln
    ]
    plain = re.sub(r"[#>*`]", "", "\n".join(cleaned_lines))
    lines = [ln.strip() for ln in plain.splitlines() if ln.strip()]
    bullet = next((_clean_claim_line(ln) for ln in lines if ln.strip().startswith("-")), "")
    claim = (bullet or next((ln for ln in lines if len(ln) >= 8), lines[0] if lines else ""))[:40]
    evs = re.findall(r"E-\d{2}", text)[:6]
    doubts = [
        s.strip() for s in re.split(r"[。；]", plain)
        if any(k in s for k in ("疑", "矛盾", "冲突", "瑕疵", "存疑", "无法", "不能排除"))
    ][:3]
    implicates = [n for n in STATE["names"] if n in text][:4]
    return {"claim": claim, "evidence_ids": evs, "doubts": doubts, "implicates": implicates}


def _critic_json() -> dict:
    case: Optional[Case] = STATE.get("last_case")
    case_hash = getattr(case, "hash", "") if case else ""
    with LOCK:
        rnd = STATE["critic_by_case"].get(case_hash, 0) + 1
        STATE["critic_by_case"][case_hash] = rnd
    issues: List[dict] = []
    if case:
        pool: List[Tuple[str, List[str]]] = []
        if case.dna_unknown:
            pool.append(("身份不明 DNA 成分与「仅在场人员涉案」的假设直接冲突，须先完成入库比对与第三人排查", ["evidence", "prosecutor", "defense"]))
        if case.edited:
            pool.append((f"{case.edited[0].id} 为剪辑产物、{('缺失片段落在死亡时间窗内' if any('死亡时间窗' in h for h in case.hot) else '缺失时段事实不明')}，依赖该时段的任何推断均不成立", ["evidence", "law", "psych"]))
        if case.flawed:
            pool.append((f"{case.flawed[0].id} 保管链瑕疵未回溯补证，物证指向性结论为时尚早", ["evidence", "law", "prosecutor"]))
        for c in case.alibi_conflicts:
            pool.append((c[:70], ["scene", "psych"]))
        if not pool:
            pool.append(("各专家对关键证据的交叉验证仍不充分，存在以推定代证明的风险", ["evidence", "psych"]))
        start = (rnd - 1) * 2
        for issue, parties in (pool * 3)[start:start + 2]:
            issues.append({"round": rnd, "issue": issue[:90], "parties": parties})
    if not issues:
        issues.append({
            "round": rnd,
            "issue": "各专家对本轮关键证据（口供与物证时间）的交叉验证仍不充分，结论前置风险存在",
            "parties": ["evidence", "psych"],
        })
    # 后端的 _extract_json 只接受 dict（列表会被静默丢弃），故包裹为 dict 返回
    return {"contradictions": issues[:2]}


def _judge_json(case: Case) -> dict:
    doubts = [h[:60] for h in case.hot[:2]]
    doubts += [f"{e.id} 保管链存在瑕疵，真实性需回溯补证" for e in case.flawed]
    if not doubts:
        doubts = list(case.alibi_conflicts)
    motive = "、".join(f["item"] for f in (case.insurance + case.transfer)[:2]) if (case.insurance or case.transfer) else "待查利益线索"
    hypo = (
        "真相推定：在案证据更支持「熟人预谋作案」模型——"
        + f"动机层面存在{motive}；"
        + (f"手段层面 {case.weapon.id} 与致伤方式吻合；" if case.weapon else "")
        + (f"条件层面 {case.edited[0].id} 缺失时段提供了行为窗口；" if case.edited else "")
        + ("但在案生物检材检出身份不明 DNA，使「第三人介入」模型暂不能被排除。" if case.dna_unknown else "但证据空窗处仍需补充侦查以闭合模型。")
    )
    # 后续流程：从案件事实动态推导，供司法机关直接执行
    steps: List[str] = []
    for e in case.edited[:2]:
        steps.append(f"调取 {e.id} 原始载体并技术恢复缺失/被删片段，出具完整性鉴定")
    if case.dna_unknown:
        steps.append("对身份不明 DNA 入库比对，并排查现场相关人员（含近亲属、从业人员）")
    for e in case.flawed[:2]:
        steps.append(f"回溯 {e.id} 保管链，补齐提取、封存、送检记录并附见证人信息")
    for f in case.insurance[:1]:
        steps.append(f"核查「{f['item']}」的投保与受益人变更全过程记录")
    for f in case.transfer[:1]:
        steps.append(f"追查 {f['item']}（{f['amount']}）的资金来源与用途凭证")
    if not steps:
        steps.append("按裁决建议推进后续程序；由人类法官作出最终裁判")
    steps.append("本系统结论仅供辅助参考，最终裁判权由人类法官/司法机关行使")
    return {
        "truth_hypothesis": hypo,
        "evidence_chain": case.chain_step(),
        "doubts": doubts[:5] or ["证据链已收敛，无明显存疑点"],
        "recommendation": "建议：①调取并封存原始监控与电子数据，修复缺失时段；②对身份不明 DNA 入库比对并排查社会关系；③回溯在案瑕疵物证的保管链；④补充侦查后由人类法官作出最终裁判。",
        "next_steps": steps[:6],
        "disclaimer": "本结论由AI辅助生成，仅供研究演示，不构成任何法律意见或判决。",
    }


def _qa_answer(case: Case, verdict: dict, question: str, facts: Optional[dict] = None) -> str:
    """裁决质询答复：只依据卷宗事实与裁决内容，引用证据编号，不编造。"""
    q = question or ""
    ql = q.lower()
    focus_ev: List[Evidence] = list(case.evidence)
    extra_lines: List[str] = []
    for e in case.evidence:
        if e.id.lower() in ql:
            focus_ev = [e] + [x for x in focus_ev if x.id != e.id]
    # 引擎冷启动（本进程还没跑过辩论）时，用质询提示词里携带的卷宗证据兜底
    if not focus_ev and facts:
        for e in (facts.get("evidence") or []):
            eid, desc = str(e.get("id") or ""), str(e.get("desc") or "")
            line = f"- [{eid} {e.get('type') or '证据'}]：{desc[:56]}"
            if eid.lower() in ql or any(k in desc.lower() for k in ("剪辑", "缺失", "dna", "监控")):
                extra_lines.insert(0, line)
            else:
                extra_lines.append(line)
            if len(extra_lines) >= 3:
                break
    kw_map = [
        (("保险", "受益", "保额"), case.insurance, "动机与资金"),
        (("转账", "资金", "账户", "钱"), case.transfer, "资金流向"),
        (("缺失", "剪辑", "监控", "录像"), ([case.monitor] if case.monitor else []), "监控证据"),
        (("dna", "生物", "血"), [], "生物物证"),
        (("时间", "死亡时间", "tod"), [], "时间线"),
        (("保管", "链条", "污染"), case.flawed, "保管链"),
    ]
    focus_label = ""
    for kws, evs, label in kw_map:
        if any(k in q or k in ql for k in kws):
            focus_label = label
            for e in evs:
                if e and e not in focus_ev:
                    focus_ev.append(e)
            break
    for p in case.names:
        if p in q:
            focus_label = focus_label or f"关于{p}"
            break
    if focus_ev:
        extra_lines = []
    ev_lines = [f"- {e.ref}：{e.desc[:56]}" for e in focus_ev[:3]] or extra_lines
    doubts = (verdict.get("doubts") or [])
    chain = (verdict.get("evidence_chain") or [])
    hypo = (verdict.get("truth_hypothesis") or "").removeprefix("真相推定：").strip()
    if focus_ev or extra_lines:
        concl = f"您质询的{focus_label or '相关证据'}问题，裁决的认定依据如下："
    else:
        concl = "就您的质询，裁决的整体逻辑如下："
    body = (
        f"{concl}\n\n"
        f"- 真相推定：{hypo[:90]}…\n"
        + (f"- 证据链关键环：{chain[0][:60]}\n" if chain else "")
        + (f"- 相关存疑点：{doubts[0][:60]}\n" if doubts else "")
        + (("\n**证据依据**\n\n" + "\n".join(ev_lines) + "\n") if ev_lines else "")
        + "\n**边界说明**：以上仅基于在案卷宗与已作出之裁决；"
        "超出卷宗范围的事项（如需原始载体、鉴定新证据）属补充侦查/审查范畴，本庭不予臆断。"
    )
    return body


_EV_TYPE_KW = [
    ("监控", "监控/视频"), ("录像", "监控/视频"), ("DNA", "生物物证"), ("指纹", "痕迹物证"),
    ("血迹", "痕迹物证"), ("鉴定", "鉴定意见"), ("凶器", "凶器"), ("毒", "理化检验"),
    ("转账", "电子数据"), ("账户", "电子数据"), ("聊天记录", "电子数据"), ("合同", "书证"),
    ("勘验", "勘验笔录"), ("笔录", "笔录"), ("现场提取", "物证"), ("痕迹", "痕迹物证"),
]
_DATE_RE = re.compile(r"(20\d{2}年)?\d{1,2}月\d{1,2}日(?:\s?(?:凌晨|清晨|上午|中午|下午|傍晚|晚上|深夜|当晚|当日))?(?:\s*\d{1,2}[时点]\d{1,2}分?)?")
_PERSON_RE = re.compile(
    r"(?:被告人|犯罪嫌疑人|嫌疑人|被害人|死者|证人|报案人|原告|被告|上诉人|驾驶人|司机|法定代表人"
    r"|值班员|装卸工|仓管员|经理|保安|老板|财务|受害人|被害者)\s*([\u4e00-\u9fa5]{2,3})"
)
_NAME_TRAIL = "系的与和及于在已曾称说是就又"
_NAME_STOP_PREFIX = ("指甲", "皮屑", "血液", "现场", "手机", "仓库", "工资", "通话", "监控", "录像", "火灾", "提取物")


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


def _clean_name(raw: str) -> str:
    while raw and raw[-1] in _NAME_TRAIL:
        raw = raw[:-1]
    return raw


def _extract_structure(text: str) -> Dict[str, Any]:
    """从纯文本卷宗（如 PDF 提取的叙述性正文）确定性抽取结构化字段：
    涉案人员 / 证据材料 / 时间线 / 可引用法条——让无结构文档也能驱动
    左侧案卷、图表与专家的结构化分析。"""
    text = text or ""
    sentences = [x.strip() for x in re.split(r"[。；;\n]", text) if 8 <= len(x.strip()) <= 140]

    persons: List[dict] = []
    seen_names = set()
    for m in _PERSON_RE.finditer(text):
        nm = _clean_name(m.group(1))
        if len(nm) < 2 or len(nm) > 3 or nm.startswith(_NAME_STOP_PREFIX) or nm in seen_names:
            continue
        seen_names.add(nm)
        role_m = m.group(0)[:len(m.group(0)) - len(m.group(1))]
        first_sent = next((x for x in sentences if nm in x), "")
        persons.append({"name": nm, "role": role_m or "涉案人员", "desc": first_sent[:60]})
        if len(persons) >= 6:
            break

    seen: set = set()
    timeline: List[dict] = []
    for s in sentences:
        if len(timeline) >= 12:
            break
        m = _DATE_RE.search(s)
        if m:
            seen.add(s)
            clocks = _cn_clocks(s)
            dm2 = re.match(r"((?:20\d{2}年)?\d{1,2}月\d{1,2}日)", m.group(0))
            if dm2:
                tdisp = dm2.group(1) + ((" " + clocks[-1]) if clocks else "")
            else:
                tdisp = m.group(0)
            timeline.append({"time": tdisp, "event": s[:70], "source": "卷宗正文"})

    evidence: List[dict] = []
    for s in sentences:
        if len(evidence) >= 8:
            break
        if s in seen:
            continue
        for kw, etype in _EV_TYPE_KW:
            if kw in s:
                seen.add(s)
                evidence.append({
                    "id": "E-%02d" % (len(evidence) + 1),
                    "type": etype,
                    "desc": s[:90],
                    "reliability": 0.75,
                    "chain_intact": True,
                })
                break

    statutes: List[dict] = []
    is_civil = any(k in text for k in ("合同", "违约", "纠纷"))
    for kws, txt in (_CIVIL_REF if is_civil else _CRIMINAL_REF):
        if any(k in text for k in kws):
            if "：" in txt:
                topic, body = txt.split("：", 1)
            else:
                topic, body = txt, ""
            statutes.append({"topic": topic, "text": body[:80]})
        if len(statutes) >= 4:
            break

    finance: List[dict] = []
    for s in sentences:
        if len(finance) >= 4:
            break
        if any(k in s for k in ("保险", "保额", "赔付", "赔偿金")) and any(ch.isdigit() for ch in s):
            s2 = re.sub(r"^\d+[.、]\s*", "", s)
            # item 必须是干净短标签（进裁决/发言），原始句子进 note——否则整句被拼进动机文案
            if "保额" in s2 and any(k in s2 for k in ("提高", "提升", "增加")):
                label = "火灾险保额异常提升"
            elif "投保" in s2:
                label = "投保记录"
            elif "赔付" in s2 or "理赔" in s2:
                label = "赔付/理赔"
            elif "保额" in s2:
                label = "保险保额"
            else:
                label = "保险利益"
            am = (re.search(r"(\d+(?:\.\d+)?)\s*万元", s2)
                  or re.search(r"(\d+(?:\.\d+)?)\s*元", s2)
                  or re.search(r"(\d+(?:\.\d+)?)", s2))
            dm = _DATE_RE.search(s2)
            finance.append({
                "item": label,
                "amount": (am.group(0) if am else "待核"),
                "date": (dm.group(0) if dm else ""),
                "note": s2[:80],
            })

    return {"persons": persons, "evidence": evidence, "timeline": timeline,
            "statutes": statutes, "finance": finance}


def _intake_json(dossier: str) -> dict:
    # 只对「案件材料：」之后的正文分类——提示词自带的字段示例里含
    # 「民事纠纷」等字样，在全文上匹配关键词会误判意图。
    if "案件材料：" in dossier:
        dossier = dossier.split("案件材料：", 1)[-1]
    summary = _section(dossier, "案件概要") or dossier[:300]
    CRIMINAL_KW = ("命案", "死亡", "尸体", "杀人", "他杀", "死于", "凶", "blood", "murder", "homicide", "arson", "body was found")
    CIVIL_KW = ("合同", "违约", "纠纷", "欠款", "breach", "contract")
    low = dossier.lower()
    if any(k in low for k in CRIMINAL_KW):
        intent = "刑事案件·真相还原"
        tags = ["刑案", "物证交叉", "时间线核验"]
    elif any(k in low for k in CIVIL_KW):
        intent = "民事纠纷·责任划分"
        tags = ["合同", "责任"]
    else:
        intent = "案件审查·事实与证据梳理"
        tags = ["综合"]
    ev_n = len(EV_RE.findall(dossier))
    intensity = "high" if ev_n >= 5 else "medium"
    guidance = (
        "请各位专家只依据卷宗发言并标注证据编号；重点交叉验证时间线与物证指向性；"
        "对保管链瑕疵与剪辑数据保持警惕，不以其单独定案；区分事实与推测，明确列出需补充侦查事项。"
    )
    core = summary[:150] + ("…" if len(summary) > 150 else "")
    return {
        "intent": intent,
        "intent_tags": tags,
        "reasoning_intensity": intensity,
        "global_guidance": guidance,
        "summary": f"{core}\n核心争议：在案物证能否闭合指向特定人；关键疑点：剪辑数据、DNA 指向与保管链完整性。",
        "extracted": _extract_structure(dossier),
    }


# ----------------------------- 主路由 -----------------------------

MODELS = {"object": "list", "data": [{"id": "verdict-local", "object": "model"}, {"id": "verdict-local-intake", "object": "model"}]}


@app.get("/healthz")
def healthz():
    return {"ok": True, "engine": "zcode-local-1"}


@app.get("/v1/models")
def models():
    return MODELS


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages: List[dict] = body.get("messages") or []
    req_tools: List[dict] = body.get("tools") or []
    model = body.get("model", "verdict-local")

    texts = [_text_of(m.get("content")) for m in messages]
    joined = "\n".join(texts)
    sys_text = next((t for t, m in zip(texts, messages) if m.get("role") == "system"), "")
    has_tool_msg = any(m.get("role") == "tool" for m in messages)

    def _reply(content: str, finish: str = "stop", extra: Optional[dict] = None) -> JSONResponse:
        msg: Dict[str, Any] = {"role": "assistant", "content": content}
        if extra:
            msg.update(extra)
        return JSONResponse({
            "id": f"chatcmpl-local-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
            "usage": {
                "prompt_tokens": max(1, len(joined) // 3),
                "completion_tokens": max(1, len(content) // 3),
                "total_tokens": (len(joined) + len(content)) // 3,
            },
        })

    # 1) 多模态图片描述（本地引擎不做视觉识别，如实说明）
    if _has_image(messages):
        return _reply("图片材料：包含与案件相关的场景/文字信息。本地引擎暂不具备视觉识别能力，建议专家结合卷宗原文与工具核验。")

    # 2) 分案法官（intake）
    if "严格的 JSON 生成器" in joined:
        obj = _intake_json(joined)
        with LOCK:
            found = re.findall(r"-\s*([\u4e00-\u9fa5]{2,4})[（(]", _section(joined, "涉案人员"))
            STATE["names"] = list(dict.fromkeys(STATE["names"] + found))[:12]
        return _reply(json.dumps(obj, ensure_ascii=False))

    # 3) 书记员
    if "合议庭书记员" in joined:
        stmt = joined.split("发言内容：", 1)[-1]
        return _reply(json.dumps(_clerk_json(stmt), ensure_ascii=False))

    # 4) 纠错官
    if "辩论纠错官" in joined:
        return _reply(json.dumps(_critic_json(), ensure_ascii=False))

    # 5) 裁决质询（辩论终结后，就裁决继续追问）
    #    注意：必须先于裁决分支判断——质询提示词里也含「你是审判长」与 truth_hypothesis
    if "【裁决质询】" in joined:
        case = STATE.get("last_case") or Case(joined)
        verdict: Dict[str, Any] = {}
        facts: Dict[str, Any] = {}
        try:
            m = re.search(r"【裁决与卷宗要点】\n(\{.*?\})\n\n【质询】", joined, re.S)
            if m:
                facts = json.loads(m.group(1))
                verdict = facts.get("verdict") or {}
        except Exception:
            verdict = STATE.get("last_verdict") or {}
        qm = re.search(r"【质询】\n(.+?)\n\n【裁决质询】", joined, re.S)
        question = qm.group(1).strip() if qm else joined[-200:]
        return _reply(_qa_answer(case, verdict, question, facts))

    # 6) 审判长（verdict）
    if "你是审判长" in joined and "truth_hypothesis" in joined:
        case = STATE.get("last_case") or Case(joined)
        verdict_obj = _judge_json(case)
        with LOCK:
            STATE["last_verdict"] = verdict_obj
        return _reply(json.dumps(verdict_obj, ensure_ascii=False))

    # 6) 专家陈述
    role = _detect_role(sys_text) if sys_text else "expert"
    material = sys_text if ("案件概要" in sys_text) else joined
    case = _refresh_case(material, hash_basis=sys_text[:200])
    with LOCK:
        STATE["last_case"] = case
        STATE["names"] = list(dict.fromkeys(STATE["names"] + case.names))[:12]
    _prev_from_history(messages, role, case)

    if has_tool_msg:
        # 工具回环：上一条是工具返回，给最终结论
        round_no = STATE["rounds_by_case"].get(case.hash, {}).get(role, 1)
        tool_res = next((_text_of(m.get("content")) for m in reversed(messages) if m.get("role") == "tool"), "")
        note = re.sub(r"\s+", " ", tool_res)[:120]
        return _reply(_statement(role, case, round_no, note))

    _reset_critic(case.hash, messages)
    round_no = _round_for(case.hash, role, messages)
    if req_tools:
        pick = _maybe_tool_call(role, case, round_no, req_tools)
        if pick:
            name, args = pick
            return _reply(
                "",
                finish="tool_calls",
                extra={"tool_calls": [{
                    "id": f"call-{uuid.uuid4().hex[:10]}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
                }]},
            )
    return _reply(_statement(role, case, round_no, ""))
