from __future__ import annotations

import asyncio
import json
from typing import Dict, List, Optional

from app.config import settings
from app.models.llm import get_llm, is_mock

# 每个角色在现实中应重点看到的材料类型（用于分案分发）
ROLE_FOCUS: Dict[str, str] = {
    "scene": "现场空间、出入口、动线、痕迹分布、物品位移",
    "forensic": "死因、伤情、死亡时间、生物学/尸检证据",
    "evidence": "指纹、DNA、凶器、监控、电子数据、保管链",
    "psych": "口供可信度、行为人动机、心理画像、供述矛盾",
    "law": "证据资格、非法证据排除、证明标准、程序正义",
    "prosecutor": "整合证据形成指控逻辑链、指出证明缺口",
    "defense": "质疑控方链节、提出替代解释与合理怀疑",
    "judge": "全局事实汇总、矛盾点、收敛判断",
}

ROLE_EVIDENCE_KEYWORDS: Dict[str, List[str]] = {
    "forensic": ["法医", "死因", "伤情", "死亡时间", "尸检", "生物学", "血迹", "致伤"],
    "evidence": [
        "dna",
        "指纹",
        "凶器",
        "监控",
        "电子数据",
        "短信",
        "微信",
        "物证",
        "保管链",
        "链条",
        "视频",
    ],
    "psych": ["口供", "供述", "动机", "心理", "嫌疑", "证人", "辩解"],
    "law": ["法条", "非法", "排除", "程序", "资格", "证明标准", "诉讼", "合规"],
    "scene": [
        "现场",
        "出入口",
        "动线",
        "痕迹",
        "书房",
        "主卧",
        "平面",
        "位置",
        "空间",
        "阳台",
        "门窗",
    ],
    "prosecutor": [],
    "defense": [],
    "judge": [],
}

INTENSITY_SUFFIX: Dict[str, str] = {
    "low": "（思考强度：低）请简明给出要点与结论，避免冗长推理。",
    "medium": "（思考强度：中）请给出有条理、分点的分析，标注依据。",
    "high": "（思考强度：高）请深度逐步推理（chain-of-thought），充分展开证据比对、反事实推演与对不利解释的检验。",
}


def _intensity_norm(v: str) -> str:
    v = (v or "").strip().lower()
    if v in ("low", "弱", "轻"):
        return "low"
    if v in ("high", "强", "深"):
        return "high"
    return "medium"


def _build_dossier_text(case: dict, image_captions: Optional[List[str]] = None) -> str:
    parts: List[str] = []
    if case.get("summary"):
        parts.append("# 案件概要\n" + case["summary"])
    if case.get("persons"):
        parts.append(
            "# 涉案人员\n"
            + "\n".join(
                f"- {p.get('name', '')}({p.get('role', '')}):{p.get('desc', '')}"
                for p in case["persons"]
            )
        )
    if case.get("timeline"):
        parts.append(
            "# 时间线\n"
            + "\n".join(
                f"- {t.get('time', '')} {t.get('event', '')}（来源:{t.get('source', '')}）"
                for t in case["timeline"]
            )
        )
    if case.get("evidence"):
        parts.append(
            "# 证据材料\n"
            + "\n".join(
                f"- [{e.get('id', '')}]{e.get('type', '')}:{e.get('desc', '')}"
                f"（可靠性{e.get('reliability', 0)}，保管链{'完整' if e.get('chain_intact') else '瑕疵'}）"
                for e in case["evidence"]
            )
        )
    if case.get("statutes"):
        parts.append(
            "# 法条依据\n"
            + "\n".join(
                f"- {s.get('topic', '')}: {s.get('text', '')}" for s in case["statutes"]
            )
        )
    if case.get("finance"):
        parts.append(
            "# 资金/财务数据\n"
            + "\n".join(
                f"- {f.get('item', '')}：金额{f.get('amount', '')}（{f.get('date', '')}）· {f.get('note', '')}"
                for f in case["finance"]
            )
        )
    if case.get("dna_persons"):
        parts.append(
            "# DNA 比对结果\n"
            + "\n".join(
                f"- {d.get('name', '')}：{'匹配' if d.get('matched') else '未匹配'}（{d.get('note', '')}）"
                for d in case["dna_persons"]
            )
        )
    if case.get("contacts"):
        parts.append(
            "# 通讯记录\n"
            + "\n".join(
                f"- {ct.get('from', '')} → {ct.get('to', '')}：{ct.get('time', '')}·{ct.get('type', '')}"
                f"（{ct.get('note', '')}）"
                for ct in case["contacts"]
            )
        )
    if image_captions:
        parts.append(
            "# 图片材料（已识别）\n" + "\n".join(f"- {c}" for c in image_captions)
        )
    return "\n\n".join(parts)


def _route_evidence(case: dict, role_key: str) -> List[dict]:
    evidence = case.get("evidence", []) or []
    kws = ROLE_EVIDENCE_KEYWORDS.get(role_key, [])
    if not kws:
        return evidence
    rel = [
        e
        for e in evidence
        if any(
            k.lower() in (str(e.get("type", "")) + str(e.get("desc", ""))).lower()
            for k in kws
        )
    ]
    return rel if rel else evidence


def build_role_material(
    case: dict, intent: str, guidance: str, contradictions: Optional[List] = None
) -> Dict[str, str]:
    """为每位角色生成差异化的分案材料（模拟现实中不同角色拿到不同卷宗）。"""
    base = _build_dossier_text(case)
    out: Dict[str, str] = {}
    for key, focus in ROLE_FOCUS.items():
        rel = _route_evidence(case, key)
        ev_lines = "\n".join(
            f"- [{e.get('id', '')}]{e.get('type', '')}:{e.get('desc', '')}"
            f"（可靠性{e.get('reliability', 0)}，保管链{'完整' if e.get('chain_intact') else '瑕疵'}）"
            for e in rel
        )
        block = f"{base}\n\n# 分派给你的重点材料（职责：{focus}）\n{ev_lines}\n"
        if contradictions:
            block += "\n# 当前已知矛盾清单\n" + "\n".join(
                f"- {c.get('issue', '')}（涉及：{', '.join(c.get('parties', []))}）"
                for c in contradictions
            )
        block += f"\n\n# 本案意图与总体分析提示\n意图：{intent}\n{guidance}\n"
        out[key] = block
    return out


def _extract_json(text: str) -> Optional[dict | list]:
    """容错解析：兼容干净 JSON、代码块包裹、被整体转义的二次编码。

    返回 dict 或 list——纠错官节点要求输出 JSON 数组，若只接受 dict，
    数组会被静默丢弃导致矛盾检测永远为空。文本被前后缀说明包裹时，
    对象切片内部也含数组、数组切片内部也含对象，单一固定顺序必有一类
    被抢先：这里取「解析成功的最长切片」，让最完整的结构胜出。"""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("```", 2)
        if len(parts) >= 2:
            t = parts[1]
            if t.lstrip().startswith("json"):
                t = t.lstrip()[4:]
    t = t.strip()
    candidates = [t, t.replace('\\"', '"').replace("\\\\", "\\")]
    i, j = t.find("{"), t.rfind("}")
    if i != -1 and j > i:
        c = t[i : j + 1]
        candidates.extend([c, c.replace('\\"', '"').replace("\\\\", "\\")])
    a, b = t.find("["), t.rfind("]")
    if a != -1 and b > a:
        c = t[a : b + 1]
        candidates.extend([c, c.replace('\\"', '"').replace("\\\\", "\\")])

    def _try(cand: str) -> Optional[dict | list]:
        try:
            obj = json.loads(cand)
            if isinstance(obj, (dict, list)):
                return obj
        except Exception:
            pass
        try:
            inner = json.loads(cand)
            if isinstance(inner, str):
                return json.loads(inner)
        except Exception:
            pass
        return None

    best: tuple[int, dict | list] | None = None
    for cand in candidates:
        obj = _try(cand)
        if obj is not None and (best is None or len(cand) > best[0]):
            best = (len(cand), obj)
    return best[1] if best else None


async def _intake_llm(dossier: str, retries: int = 3) -> Optional[dict]:
    prompt = (
        "你是一个严格的 JSON 生成器。只输出一个 JSON 对象，禁止任何额外文字、"
        '禁止 markdown 代码块、禁止对引号做转义（直接输出 {"key":"value"} 形式）。\n'
        "请阅读案件材料，识别调查意图、判断所需思考强度，并给出给全体专家的总体分析提示词与问题摘要。\n"
        "JSON 字段如下（不要增减字段）：\n"
        '{"intent":"一句话概括本案性质与调查意图（如：刑事案件·真相还原/民事纠纷·责任划分/合规审查）",'
        '"intent_tags":["标签1","标签2"],'
        '"reasoning_intensity":"low|medium|high",'
        '"global_guidance":"给所有专家的总体分析提示词（200字内：分析重点、应避免的偏差、需特别核验的事项）",'
        '"summary":"对材料分类概括后的问题摘要（300字内：事实梗概+核心争议+关键疑点）",'
        '"extracted":{"persons":[{"name":"涉案人员姓名","role":"身份/角色","desc":"与案件的关系或描述"}],'
        '"evidence":[{"id":"E-01","type":"物证/书证/笔录等","desc":"证据描述（含保管链、可靠性提示）"}],'
        '"timeline":[{"time":"时间","event":"事件","source":"来源"}],'
        '"statutes":[{"topic":"法条主题","text":"条文要点"}],'
        '"finance":[{"item":"项目","amount":"金额描述","date":"日期","note":"备注"}]'
        "}}\n\n"
        f"案件材料：\n{dossier}"
    )
    last = None
    for _ in range(retries):
        try:
            llm = get_llm("分案法官", model=settings.intake_model, temperature=0.1)
            resp = await llm.ainvoke([{"role": "user", "content": prompt}])
            text = resp.content if hasattr(resp, "content") else str(resp)
            obj = _extract_json(text)
            if isinstance(obj, dict) and obj:
                return obj
            last = text
        except Exception:
            await asyncio.sleep(1)
    return None


async def _extract_images(case: dict) -> List[str]:
    imgs = case.get("images") or []
    captions: List[str] = []
    for im in imgs:
        name = im.get("name", "图片")
        data_url = im.get("data_url") or im.get("content") or ""
        if not data_url:
            captions.append(f"{name}：（图片已附，待专家结合视觉/工具分析）")
            continue
        try:
            llm = get_llm("分案法官")
            msg = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "请简要描述这张图片中与案件相关的信息（场景/文字/物品），用于卷宗预处理。",
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ]
            resp = await llm.ainvoke(msg)
            captions.append(
                f"{name}：{resp.content if hasattr(resp, 'content') else resp}"
            )
        except Exception:
            captions.append(f"{name}：（图片已附，待专家结合视觉/工具分析）")
    return captions


async def preprocess(raw: dict, use_llm: bool = True) -> dict:
    """卷宗预处理：意图识别 + 思考强度 + 提示词 + 分类概括 + 分角色分发。

    注意：抽取到的人员/证据/时间线等结构会回写到传入的 raw（同一对象），
    调用方（如上传接口）应在调用后把 raw 持久化到案件文件，前端案卷与
    图表才能展示抽取结果；只读场景（开庭时补跑预处理）不受影响。
    """
    case = raw
    image_captions = await _extract_images(case) if use_llm else []
    dossier = _build_dossier_text(case, image_captions)

    intent = "未指定"
    intent_tags: List[str] = []
    intensity = "medium"
    guidance = "请基于卷宗客观分析，标注依据，区分事实与推测。"
    summary = case.get("summary", "")

    if use_llm:
        res = await _intake_llm(dossier)
        if res:
            intent = res.get("intent") or intent
            intent_tags = res.get("intent_tags") or []
            intensity = _intensity_norm(res.get("reasoning_intensity", "medium"))
            guidance = res.get("global_guidance") or guidance
            summary = res.get("summary") or summary
            # PDF/纯文本卷宗没有结构化字段：AI 预处理从正文中抽取
            # 人员/证据/时间线/法条并回写案件，左侧案卷、图表与专家材料才有据可依
            extracted = res.get("extracted")
            if isinstance(extracted, dict):
                merged = False
                for k in ("persons", "evidence", "timeline", "statutes", "finance"):
                    v = extracted.get(k)
                    if v and not case.get(k):
                        case[k] = v
                        merged = True
                if merged:
                    case["ai_extracted"] = True
                if any(case.get(k) for k in ("persons", "evidence", "timeline")):
                    dossier = _build_dossier_text(case, image_captions)

    per_role_material = build_role_material(case, intent, guidance)
    return {
        "intent": intent,
        "intent_tags": intent_tags,
        "reasoning_intensity": intensity,
        "global_guidance": guidance,
        "summary": summary,
        "images": [
            {"name": im.get("name", "图片"), "caption": c}
            for im, c in zip(case.get("images", []) or [], image_captions)
        ],
        "per_role_material": per_role_material,
        "intake_done": True,
    }
