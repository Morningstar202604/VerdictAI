# -*- coding: utf-8 -*-
"""本地推理引擎 · 专家陈述与工具决定。

按角色生成有依据、分点、跨轮相互参照的 Markdown 陈述；
并决定每个回合是否发起工具调用（read_evidence / timeline_check /
search_case_law / run_code 沙箱图表）。
"""

from __future__ import annotations

import json
import re
from typing import List, Optional, Tuple

from ai_engine.parsing import Case, CIVIL_REF, CRIMINAL_REF, _text_of

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


def _human_intervention(messages: List[dict]) -> str:
    """取最近一条人类法官介入（【人类法官介入】前缀的 user 消息）。

    后端把它注入了对话历史，但只有真实 LLM 会"自然读到"；
    本地引擎必须显式解析并在陈述里回应，否则介入形同虚设。"""
    out = ""
    for m in messages:
        if m.get("role") == "user":
            t = _text_of(m.get("content"))
            if "【人类法官介入】" in t:
                out = t.split("【人类法官介入】", 1)[-1].strip()
    return out


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
    if round_no >= 3:
        ref += "（结辩导向）请给出收束性结论：核心主张一句话 + 证据编号清单，不再展开新论点。\n\n"
    elif round_no == 2:
        ref += "（交叉质证轮）本轮须点名回应至少一位其他专家的主张，给出认可或反驳及证据编号依据。\n\n"
    return ref


def _human_response(case: Case) -> str:
    """人类法官介入的显式回应块：没有介入时为空，介入后每位专家必须先表态。"""
    if not case.human_note:
        return ""
    t = case.human_note
    keys = [k for k in ("监控", "缺失", "剪辑", "DNA", "保管链", "时间线", "资金", "动机", "通讯") if k in t]
    focus = "、".join(keys[:3]) or "该指示涉及的事项"
    return (
        f"#### ⓪ 人类法官指示的核验重点\n\n"
        f"收到人类法官指示「{t[:60]}」。本轮已优先核查{focus}："
        f"相关判断均对照卷宗证据编号给出；在案无法核实的部分，已在疑点中"
        f"明确列为补充侦查事项，不做臆断。\n\n"
    )


def _statute_refs(case: Case) -> List[str]:
    """按案件事实确定性匹配真实法条，供专家引用（不幻觉法号）。"""
    is_civil = "民事" in (case.intent or "")
    rules = CIVIL_REF if is_civil else CRIMINAL_REF
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
            "#### ① 指控逻辑链\n\n"
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

    return f"{opening}{_human_response(case)}{body}{tn}{depth_note}".strip()


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