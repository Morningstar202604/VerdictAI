# -*- coding: utf-8 -*-
"""本地推理引擎 · 分案法官（intake）。

从纯文本卷宗（如 PDF 提取的叙述性正文）确定性抽取结构化字段：
涉案人员 / 证据材料 / 时间线 / 可引用法条 / 资金线索，并识别意图与思考强度。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ai_engine.parsing import CIVIL_REF, CRIMINAL_REF, EV_RE, _cn_clocks, _section

_EV_TYPE_KW = [
    ("监控", "监控/视频"), ("录像", "监控/视频"), ("DNA", "生物物证"), ("指纹", "痕迹物证"),
    ("血迹", "痕迹物证"), ("鉴定", "鉴定意见"), ("凶器", "凶器"), ("毒", "理化检验"),
    ("转账", "电子数据"), ("账户", "电子数据"), ("聊天记录", "电子数据"), ("合同", "书证"),
    ("勘验", "勘验笔录"), ("笔录", "笔录"), ("现场提取", "物证"), ("痕迹", "痕迹物证"),
]
_DATE_RE = re.compile(r"(20\d{2}年)?\d{1,2}月\d{1,2}日(?:\s?(?:凌晨|清晨|上午|中午|下午|傍晚|晚上|深夜|当晚|当日))?(?:\s*\d{1,2}[时点]\d{1,2}分?)?")
# 身份词后允许序号（被告一/原告二）与冒号/逗号/括号，再接人名——
# 否则「被告一偿还…」会把「一偿还」当成名字
_PERSON_RE = re.compile(
    r"(?:被告人|犯罪嫌疑人|嫌疑人|被害人|死者|证人|报案人|原告|被告|上诉人|驾驶人|司机|法定代表人"
    r"|值班员|装卸工|仓管员|经理|保安|老板|财务|受害人|被害者)(?:[一二三四五六七八九十\d]{1,2})?[：:，,（(\s]*"
    r"([\u4e00-\u9fa5]{2,3})"
)
_NAME_TRAIL = "系的与和及于在已曾称说是就又"
_NAME_STOP_PREFIX = ("指甲", "皮屑", "血液", "现场", "手机", "仓库", "工资", "通话", "监控", "录像", "火灾", "提取物")
# 常见姓氏白名单：首字不像姓氏的候选（如「名下轿」「保存有」「到期不」）直接排除，
# 这是中文人名抽取最稳的规则；动词/虚词黑名单只作第二道兜底
_SURNAMES = set(
    "李王张刘陈杨赵黄周吴徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程"
    "苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝"
    "龚邵万钱严覃武戴莫孔向汤温康施文柯桂米邱常齐殷施聂伍余倪凌殷穆祝郝洪阮龚龚代盛童邱"
)
# 常见动词/虚词：出现在候选名里基本可断定不是人名（偿还/抵押/签约…）
_NAME_BAD_CHARS = set("的了与和及其于在已曾称说是就又对为这向由从被还偿押签诉请确享受优先允诺承应当须将愿按依经通过逾超未均已此各该")


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
        # 首字必须是常见姓氏，且候选名不含动词/虚词（如「偿还」「抵押」）
        if nm[0] not in _SURNAMES or any(ch in _NAME_BAD_CHARS for ch in nm):
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
    for kws, txt in (CIVIL_REF if is_civil else CRIMINAL_REF):
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
        # 覆盖民事资金线（借款/工资/补偿）而不仅是保险
        if any(k in s for k in ("保险", "保额", "赔付", "赔偿金", "借款", "本金", "利息", "还款", "归还", "工资", "欠薪", "补偿金")) and any(ch.isdigit() for ch in s):
            s2 = re.sub(r"^\d+[.、]\s*", "", s)
            # item 必须是干净短标签（进裁决/发言），原始句子进 note——否则整句被拼进动机文案
            if "工资" in s2 or "欠薪" in s2:
                label = "拖欠工资"
            elif "补偿" in s2:
                label = "经济补偿"
            elif "归还" in s2 or "还款" in s2 or "偿还" in s2:
                label = "还款记录"
            elif "本金" in s2 or "借款" in s2:
                label = "借款本金"
            elif "保额" in s2 and any(k in s2 for k in ("提高", "提升", "增加")):
                label = "火灾险保额异常提升"
            elif "投保" in s2:
                label = "投保记录"
            elif "赔付" in s2 or "理赔" in s2:
                label = "赔付/理赔"
            elif "保额" in s2:
                label = "保险保额"
            else:
                label = "资金往来"
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


def intake_json(dossier: str) -> dict:
    # 只对「案件材料：」之后的正文分类——提示词自带的字段示例里含
    # 「民事纠纷」等字样，在全文上匹配关键词会误判意图。
    if "案件材料：" in dossier:
        dossier = dossier.split("案件材料：", 1)[-1]
    summary = _section(dossier, "案件概要") or dossier[:300]
    CRIMINAL_KW = ("命案", "死亡", "尸体", "杀人", "他杀", "死于", "凶", "盗窃", "窃取", "抢劫", "blood", "murder", "homicide", "arson", "theft", "body was found")
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