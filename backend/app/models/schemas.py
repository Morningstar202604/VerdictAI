# -*- coding: utf-8 -*-
"""结构化 Schema（Pydantic v2）：卷宗预处理 / 裁决 / 矛盾清单的校验与清洗。

设计原则：清洗而非拒绝——任何来源（云端 LLM / 本地确定性引擎 / mock，
甚至用户的 agent_config 手工编辑）产出结构都先经这里清洗：
非法值回退默认、字段缺失补空、强度值规范化，绝不让坏结构打断辩论。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from pydantic import BaseModel, Field, field_validator

log = logging.getLogger("verdictai.schemas")

# 常驻"案由"清单：用于从卷宗文本确定性推导案件类型（不依赖模型字段）
CAUSE_CASE_MAP = [
    # (触发关键词, 案由, 建议策略预设)
    (("故意杀", "命案", "他杀", "尸体", "窒息", "凶器"), "故意杀人案", "刑事·严格证据攻防"),
    (("伤害", "殴打", "打伤", "轻伤", "重伤"), "故意伤害案", "刑事·严格证据攻防"),
    (("盗窃", "窃取", "入室", "盗走"), "盗窃案", "刑事·严格证据攻防"),
    (("诈骗", "骗取", "虚构事实", "电信诈骗"), "诈骗案", "刑事·严格证据攻防"),
    (("抢劫", "抢夺", "持刀"), "抢劫/抢夺案", "刑事·严格证据攻防"),
    (("职务侵占", "挪用", "侵占"), "职务侵占/挪用案", "刑事·严格证据攻防"),
    (("交通", "肇事", "酒驾", "醉驾"), "交通肇事案", "民事·责任划分"),
    (("借贷", "借款", "欠款", "还款", "利息"), "民间借贷纠纷", "民事·责任划分"),
    (("合同", "违约", "履行", "对赌"), "合同纠纷", "民事·责任划分"),
    (("劳动关系", "工资", "欠薪", "工伤", "劳动合同", "解除"), "劳动纠纷", "民事·责任划分"),
    (("离婚", "抚养", "赡养", "财产分割"), "婚姻家庭纠纷", "民事·责任划分"),
    (("保险", "理赔", "保额", "赔付"), "保险纠纷", "刑事·严格证据攻防"),
    (("行政", "处罚", "复议", "许可", "征收"), "行政争议", "刑事·严格证据攻防"),
]

_INTENSITY_VALUES = ("low", "medium", "high")


def _clean_str(v: Any, default: str = "", limit: int = 4000) -> str:
    s = str(v or "").strip()
    if not s or s.lower() == "none":
        return default
    return s[:limit]


def _clean_str_list(v: Any, limit: int = 30) -> List[str]:
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        s = str(x or "").strip()
        if s and s not in out:
            out.append(s[:120])
        if len(out) >= limit:
            break
    return out


def cause_from_text(text: str) -> tuple[str, str]:
    """确定性案由分类：返回 (案由, 建议策略预设)。命中即返回第一个匹配。"""
    t = text or ""
    for kws, cause, preset in CAUSE_CASE_MAP:
        if any(k in t for k in kws):
            return cause, preset
    if "民事" in t or any(k in t for k in ("合同", "违约", "纠纷")):
        return "民事纠纷", "民事·责任划分"
    return "案件审查", ""


def causes_from_text(text: str, limit: int = 3) -> List[Dict[str, Any]]:
    """多案由识别（M1.1 扩展）：返回文本命中的所有案由（按命中关键词数降序）。

    复杂卷宗常同时涉及多个案由（如"借贷 + 合同 + 担保"），单一主案由会
    丢失信息。返回列表形如 [{"cause": "...", "preset": "...", "hits": n}, ...]，
    首项即主案由（与 cause_from_text 保持一致）；未命中返回空列表。"""
    t = text or ""
    scored: Dict[str, Dict[str, Any]] = {}
    for kws, cause, preset in CAUSE_CASE_MAP:
        n = sum(1 for k in kws if k in t)
        if n == 0:
            continue
        prev = scored.get(cause)
        if prev is None or n > prev["hits"]:
            scored[cause] = {"cause": cause, "preset": preset, "hits": n}
    items = sorted(scored.values(), key=lambda x: (-x["hits"], x["cause"]))
    return items[:limit]


# ----------------------------- 意图路由（M1.5） -----------------------------

_GREETING = ("你好", "您好", "谢谢", "感谢", "hello", "hi", "哈哈", "嗯", "哦", "？", "?", "在吗", "有人吗", "拜拜", "再见", "测试一下", "试验")

# 实体槽位抽取用的最小正则集（确定性托底；复杂实体留给 LLM intake 兜底）
_RE_PARTY = re.compile(r"(?:被告人|犯罪嫌疑人|原告|被告|上诉人|被上诉人|受害人|被害人|证人)\s*[:：]?\s*([\u4e00-\u9fa5·A-Za-z]{1,6})")
_RE_DATE = re.compile(r"(\d{4}年)?\d{1,2}月\d{1,2}[日号]?(?:\s*凌晨|\s*上午|\s*下午|\s*傍晚|\s*夜间|\s*晚上|\s*深夜)?|(?:凌晨|上午|下午|傍晚|夜间|晚上|深夜)\s*\d{1,2}[点时]?")
_RE_AMOUNT = re.compile(r"(?:现金|金额|数额|涉案金额|赔偿|借款|欠款|赃款|资金|转入|提取)?\d+(?:\.\d+)?\s*(?:万|元|块|美元|万元|亿|人民币)")
_RE_PLACE = re.compile(r"(?:位于|进入|潜入|侵入|来到|赶往|前往|出入|藏匿于|发生于)\s*([\u4e00-\u9fa5]{2,10})")

# 人名捕获后紧跟的常见连接词/介词，用于把"张三于"截断为"张三"
_PARTY_STOP = "于在与和及把被向到的出入其间"
# 地点捕获后的动作/量词边界，用于止住"西山区别墅窃取现金"这类贪吃
_PLACE_STOP = "窃取窃得盗偷拿走取现现金金额返回离开搭乘驾车前往拿了二十三十万"


def extract_entities(text: str) -> Dict[str, List[str]]:
    """确定性实体槽位抽取：当事人 / 日期时间 / 金额 / 地点。能力有限，定位是
    给向导路由快速填充检索条件，准确实体标注最终以 LLM intake 为准。"""
    t = text or ""
    parties, dates, amounts, places = [], [], [], []
    for m in re.finditer(_RE_PARTY, t):
        v = m.group(1).strip()
        cut = next((i for i, ch in enumerate(v) if ch in _PARTY_STOP), len(v))
        if cut:
            v = v[:cut]
        if v and v not in parties:
            parties.append(v)
    for m in re.finditer(_RE_DATE, t):
        v = m.group(0).strip()
        if v and v not in dates:
            dates.append(v)
    for m in re.finditer(_RE_AMOUNT, t):
        v = m.group(0).strip().rstrip(".")
        if v and v not in amounts:
            amounts.append(v)
    for m in re.finditer(_RE_PLACE, t):
        raw = re.sub(r"^(?:位于|进入|潜入|侵入|来到|赶往|前往|出入|藏匿于|发生于|在)", "", m.group(1).strip())
        cut = next((i for i, ch in enumerate(raw) if ch in _PLACE_STOP), len(raw))
        v = raw[:cut] if cut else raw
        if v and v not in places:
            places.append(v)
    return {
        "parties": parties[:6],
        "datetimes": dates[:6],
        "amounts": amounts[:6],
        "places": places[:4],
    }


def gate_input(text: str) -> tuple[bool, str]:
    """无关输入门禁：明显与案件无关的寒暄/无效输入在此拦截，避免浪费模型调用。
    返回 (是否相关, 拒绝理由)。宽松策略——宁可放行回退回退，不可误杀真实案情。"""
    t = (text or "").strip()
    if len(t) < 2:
        return False, "输入过短，请粘贴案件描述或上传卷宗"
    if len(t) <= 12 and any(g == t or t.startswith(g) for g in ("你好", "您好", "谢谢", "hello", "hi", "在吗", "测试", "哈哈")):
        return False, "检测为寒暄/无关输入，请提供案件描述"
    if t in _GREETING:
        return False, "检测为寒暄/无关输入，请提供案件描述"
    # 含案件关键词或足够长 → 视为相关
    for kws, _cause, _preset in CAUSE_CASE_MAP:
        if any(k in t for k in kws):
            return True, ""
    if len(t) >= 20:
        return True, ""
    return True, ""


def intent_router(text: str) -> Dict[str, Any]:
    """意图路由：门禁 → 案由（多候选）→ 预设 → 置信度 → 实体槽位。一个函数给前端/向导复用的全量结果。"""
    t = (text or "").strip()
    relevant, reason = gate_input(t)
    cause, preset = cause_from_text(t)
    causes = causes_from_text(t)
    if causes and not cause.startswith("案件"):
        # 主案由与多候选保持一致；多候选优先返回复杂卷宗命中的全部案由
        cause, preset = causes[0]["cause"], causes[0]["preset"]
    entities = extract_entities(t) if relevant else {"parties": [], "datetimes": [], "amounts": [], "places": []}
    # 置信度启发式：命中案由关键词越直接、文本越结构化越高
    conf = 0.5
    if relevant and cause != "案件审查":
        hits = sum(1 for kws, c, _p in CAUSE_CASE_MAP if c == cause for k in kws if k in t)
        conf = 0.75 + min(0.2, hits * 0.05)
        if len(t) >= 40:
            conf = min(0.98, conf + 0.08)
    elif relevant and len(t) >= 30:
        conf = 0.6
    return {
        "relevant": relevant,
        "reject_reason": reason,
        "cause": cause,
        "suggested_preset": preset,
        "causes": causes,
        "confidence": round(conf, 2),
        "entities": entities,
        "length": len(t),
    }


class IntakeResult(BaseModel):
    """卷宗预处理结果（intake）清洗后的规范结构。"""

    intent: str = "未指定"
    cause: str = "案件审查"
    cause_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    suggested_preset: str = ""
    intent_tags: List[str] = Field(default_factory=list)
    reasoning_intensity: str = "medium"
    global_guidance: str = ""
    summary: str = ""

    @field_validator("reasoning_intensity", mode="before")
    @classmethod
    def _norm_intensity(cls, v):
        s = str(v or "medium").strip().lower()
        if s in ("low", "弱", "轻"):
            return "low"
        if s in ("high", "强", "深"):
            return "high"
        return "medium" if s in _INTENSITY_VALUES else "medium"

    @field_validator("cause_confidence", mode="before")
    @classmethod
    def _norm_conf(cls, v):
        try:
            f = float(v)
            return max(0.0, min(1.0, f))
        except (TypeError, ValueError):
            return 0.5


class Verdict(BaseModel):
    """审判长裁决的规范结构。"""

    truth_hypothesis: str = ""
    evidence_chain: List[str] = Field(default_factory=list)
    doubts: List[str] = Field(default_factory=list)
    recommendation: str = ""
    next_steps: List[str] = Field(default_factory=list)
    disclaimer: str = "本结论由AI辅助生成，仅供研究演示，不构成任何法律意见或判决。"


class Contradiction(BaseModel):
    """纠错官矛盾条目的规范结构。"""

    round: int = 0
    issue: str = ""
    parties: List[str] = Field(default_factory=list)

    @field_validator("parties", mode="before")
    @classmethod
    def _norm_parties(cls, v):
        if not isinstance(v, list):
            return []
        return [str(p) for p in v if str(p or "").strip()][:8]


# --------------------- 结构化输出契约（P2-1，强约束 JSON） ---------------------
# 供 llm.with_structured_output 使用的 Pydantic 契约（模型原生 schema 强制解析，
# 最大程度消除 JSON 漂移）；字段全默认 → 解析宽容，坏结构回退默认而非拒绝，
# 与既有 clean_* 清洗入口语义一致。

class ReflectionItem(BaseModel):
    """反思/可证伪性审查单条记录的结构。"""

    role: str = ""
    subject: str = ""
    objection: str = ""


class NoteItem(BaseModel):
    """合议书记录单条记录的结构。"""

    claim: str = ""
    evidence_ids: List[str] = Field(default_factory=list)
    doubts: List[str] = Field(default_factory=list)
    implicates: List[str] = Field(default_factory=list)


class ContradictionList(BaseModel):
    """矛盾清单的结构化输出包装（列表型契约）。"""

    items: List[Contradiction] = Field(default_factory=list)


class ReflectionList(BaseModel):
    """反思清单的结构化输出包装（列表型契约）。"""

    items: List[ReflectionItem] = Field(default_factory=list)


# ----------------------------- 清洗入口 -----------------------------


def clean_intake(obj: Any, text_hint: str = "") -> Dict[str, Any]:
    """清洗/规范化 intake 响应；text_hint 用于确定性案由推导（兼容 mock/引擎契约）。"""
    raw = obj if isinstance(obj, dict) else {}
    try:
        m = IntakeResult(**raw)
    except Exception as ex:  # noqa: BLE001
        log.warning("intake schema 清洗失败，回退默认: %s", ex)
        m = IntakeResult()
    cause, preset = cause_from_text(text_hint or (raw.get("summary") or "") or m.summary)
    # 模型/引擎未给出案由时，以确定性推导为准；给出则沿用
    cause = cause if not raw.get("cause") else str(raw.get("cause"))
    confidence = m.cause_confidence
    if not raw.get("cause"):
        # 启发式置信度：结构越完整越可信
        confidence = 0.6 + min(0.3, (len(_clean_str_list(raw.get("intent_tags"))) * 0.05)) if not raw else confidence
    suggested = preset or m.suggested_preset
    return {
        "intent": m.intent,
        "cause": cause,
        "cause_confidence": round(float(confidence), 2),
        "suggested_preset": suggested,
        "intent_tags": m.intent_tags,
        "reasoning_intensity": m.reasoning_intensity,
        "global_guidance": m.global_guidance,
        "summary": m.summary,
    }


def clean_verdict(obj: Any) -> Dict[str, Any]:
    """清洗/规范化裁决；坏结构回退默认值，保证复盘与导出不崩。"""
    raw = obj if isinstance(obj, dict) else {}
    try:
        m = Verdict(**raw)
    except Exception as ex:  # noqa: BLE001
        log.warning("verdict schema 清洗失败，回退默认: %s", ex)
        m = Verdict()
    return {
        "truth_hypothesis": m.truth_hypothesis,
        "evidence_chain": _clean_str_list(m.evidence_chain, 30),
        "doubts": _clean_str_list(m.doubts, 20),
        "recommendation": m.recommendation,
        "next_steps": _clean_str_list(m.next_steps, 10),
        "disclaimer": m.disclaimer,
    }


def clean_contradictions(obj: Any) -> List[Dict[str, Any]]:
    """清洗/规范化矛盾清单（critic 节点输出）。"""
    items = obj if isinstance(obj, list) else (obj.get("contradictions", []) if isinstance(obj, dict) else [])
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            m = Contradiction(**it)
        except Exception:  # noqa: BLE001
            continue
        out.append({
            "round": max(0, int(m.round or 0)),
            "issue": (m.issue or "")[:300],
            "parties": m.parties,
        })
    return out[:10]