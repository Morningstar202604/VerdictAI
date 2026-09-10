# -*- coding: utf-8 -*-
"""本地推理引擎 · JSON 节点：书记员 / 纠错官 / 审判长 / 裁决质询。"""

from __future__ import annotations

import re
from typing import List, Optional

from ai_engine.parsing import Case, Evidence
from ai_engine.state import LOCK, STATE, _touch_case


def _clean_claim_line(ln: str) -> str:
    ln = re.sub(r"^[#>\-\*\d\.\s、①②③④]+", "", ln).strip()
    return ln


def clerk_json(text: str) -> dict:
    """合议庭书记员：把某专家发言提炼为结构化记录。"""
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


def critic_json() -> dict:
    """纠错官：对比各专家主张，输出矛盾/纠错清单（逐轮消化，不原地循环）。"""
    case: Optional[Case] = STATE.get("last_case")
    case_hash = getattr(case, "hash", "") if case else ""
    with LOCK:
        _touch_case(case_hash)
        rnd = STATE["critic_by_case"].get(case_hash, 0) + 1
        STATE["critic_by_case"][case_hash] = rnd
        emitted: List[str] = STATE.setdefault("critic_emitted_by_case", {}).setdefault(case_hash, [])
    issues: List[dict] = []
    if case:
        pool: List[tuple] = []
        if case.dna_unknown:
            pool.append(("身份不明 DNA 成分与「仅在场人员涉案」的假设直接冲突，须先完成入库比对与第三人排查", ["evidence", "prosecutor", "defense"]))
        if case.edited:
            pool.append((f"{case.edited[0].id} 为剪辑产物、{('缺失片段落在死亡时间窗内' if any('死亡时间窗' in h for h in case.hot) else '缺失时段事实不明')}，依赖该时段的任何推断均不成立", ["evidence", "law", "psych"]))
        if case.flawed:
            pool.append((f"{case.flawed[0].id} 保管链瑕疵未回溯补证，物证指向性结论为时尚早", ["evidence", "law", "prosecutor"]))
        for c in case.alibi_conflicts:
            pool.append((c[:70], ["scene", "psych"]))
        # 只提尚未处理过的矛盾：让辩论逐轮消化矛盾并收敛，
        # 而不是同一批问题在轮次间原地循环
        fresh = [p for p in pool if p[0] not in emitted]
        for issue, parties in fresh[:2]:
            emitted.append(issue)
            issues.append({"round": rnd, "issue": issue[:90], "parties": parties})
        if not fresh:
            issues.append({
                "round": rnd,
                "issue": "前述矛盾点已逐项排入核验计划，剩余分歧集中在补证时序与证明标准评估，建议审判长评估收敛",
                "parties": ["judge"],
            })
    if not issues:
        issues.append({
            "round": rnd,
            "issue": "各专家对本轮关键证据（口供与物证时间）的交叉验证仍不充分，结论前置风险存在",
            "parties": ["evidence", "psych"],
        })
    # 后端的 _extract_json 只接受 dict（列表会被静默丢弃），故包裹为 dict 返回
    return {"contradictions": issues[:2]}


def judge_json(case: Case) -> dict:
    """审判长：综合专家主张与矛盾，输出结构化裁决。"""
    doubts = [h[:60] for h in case.hot[:2]]
    doubts += [f"{e.id} 保管链存在瑕疵，真实性需回溯补证" for e in case.flawed]
    if not doubts:
        doubts = list(case.alibi_conflicts)
    motive = "、".join(f["item"] for f in (case.insurance + case.transfer)[:2]) if (case.insurance or case.transfer) else "待查利益线索"
    # 案件性质决定叙事模型：命案/盗窃/民事各用各的话术，避免张冠李戴。
    # 除意图标签外同时扫案件文本——存量案件的意图可能是旧版引擎生成的。
    # 刑事关键词（命案/死亡/凶器等）优先于民事关键词：卷宗是命案时，
    # 即便正文含「合同/违约」字样（如股权对赌协议）也不得落入民事模板。
    intent = case.intent or ""
    case_text = (case.raw or "")[:2000]
    _crime_kw = ("命案", "死亡", "尸体", "杀人", "他杀", "死于", "凶", "故意杀人", "抢劫")
    _civil_kw = ("借款", "借贷", "合同", "违约", "欠款")
    if any(k in intent + case_text for k in ("盗窃", "窃取", "侵占", "职务侵占")):
        model = "熟悉现场与值守规律的人员作案"
    elif any(k in intent + case_text for k in _crime_kw):
        model = "熟人预谋作案"
    elif "民事" in intent or any(k in intent + case_text for k in _civil_kw):
        model = "合同履行事实与违约责任的按因认定"
    else:
        model = "熟人预谋作案"
    subject = "、".join(case.names[:3]) if case.names else "在案各方"
    hypo = (
        "真相推定：在案证据更支持「" + model + "」——"
        + f"涉案主体：{subject}；"
        + (f"动机与资金层面：{motive}；" if (case.insurance or case.transfer) else "")
        + (f"手段层面 {case.weapon.id} 与致伤方式吻合；" if case.weapon else "")
        + (f"条件层面 {case.edited[0].id} 缺失时段提供了行为窗口；" if case.edited else "")
        + ("但在案生物检材检出身份不明 DNA，使「第三人介入」模型暂不能被排除。" if case.dna_unknown else "但关键待证事项仍需在案证据进一步印证。")
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
    civil_case = "民事" in intent or any(k in intent + case_text for k in _civil_kw)
    crime_case = any(k in intent + case_text for k in _crime_kw) or any(
        k in intent + case_text for k in ("盗窃", "窃取", "侵占", "职务侵占")
    )
    loan_case = any(k in intent + case_text for k in ("借款", "借贷"))
    if loan_case:
        recommendation = (
            "建议：①核对借款合同与转账凭证原件，确认债务数额与利息计算；"
            "②审查抵押未登记对担保效力的影响及保证期间是否届满；"
            "③查明已还款项的性质（本金/利息）与抵充顺序；"
            "④经审理后依法判决——本系统结论仅供辅助参考。"
        )
    elif civil_case and not crime_case:
        recommendation = (
            "建议：①围绕争议法律关系固定证据原件（合同/记录/凭证）；"
            "②明确双方权利义务与实际履行事实；"
            "③核算请求数额与责任比例；"
            "④经审理后依法裁判——本系统结论仅供辅助参考。"
        )
    else:
        recommendation = "建议：①调取并封存原始监控与电子数据，修复缺失时段；②对身份不明 DNA 入库比对并排查社会关系；③回溯在案瑕疵物证的保管链；④补充侦查后由人类法官作出最终裁判。"
    return {
        "truth_hypothesis": hypo,
        "evidence_chain": case.chain_step(),
        "doubts": doubts[:5] or ["证据链已收敛，无明显存疑点"],
        "recommendation": recommendation,
        "next_steps": steps[:6],
        "disclaimer": "本结论由AI辅助生成，仅供研究演示，不构成任何法律意见或判决。",
    }


def qa_answer(case: Case, verdict: dict, question: str, facts: Optional[dict] = None) -> str:
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
        f"- 真相推定：{hypo}\n"
        + (f"- 证据链关键环：{chain[0][:60]}\n" if chain else "")
        + (f"- 相关存疑点：{doubts[0][:60]}\n" if doubts else "")
        + (("\n**证据依据**\n\n" + "\n".join(ev_lines) + "\n") if ev_lines else "")
        + "\n**边界说明**：以上仅基于在案卷宗与已作出之裁决；"
        "超出卷宗范围的事项（如需原始载体、鉴定新证据）属补充侦查/审查范畴，本庭不予臆断。"
    )
    return body