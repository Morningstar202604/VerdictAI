# -*- coding: utf-8 -*-
"""LLM-as-judge 质量评估器（检验评价工程 · 可选增强，不进 CI 默认）。

跑一场真实辩论（复用 LangGraph 图与现有预处理链路），然后从事件流汇总
确定性指标（裁决完整性 / 自检 / 引用溯源 / 反思），再用一个独立 judge
模型的 LLM 对"事实一致性 / 证据引用 / 推理 / 完整性 / 不确定性披露"
五个维度打分，输出结构化报告。

用法（在 backend 目录，需先启动本地引擎或用云模型配置）：

    python tools/evaluate.py                     # 用案例库中的第一个案件
    python tools/evaluate.py --case case_001     # 指定案例 ID
    python tools/evaluate.py --text "粘贴案件描述…"
    python tools/evaluate.py --rounds 2 --fail-below 6 --json out.json

mock 模式下只报告确定性指标并跳过 LLM 打分（提示需真实模型）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_core.messages import HumanMessage

from app.agents.tools import activate_case
from app.config import debate_snapshot, settings
from app.graph.builder import build_graph
from app.intake.processor import preprocess
from app.models.llm import get_llm, is_mock, stream_or_invoke

DIMENSIONS = [
    ("factual_consistency", "事实一致性：主张与案卷事实是否一致、有无虚构"),
    ("evidence_citation", "证据引用：结论是否挂接真实证据/法条来源"),
    ("reasoning", "推理质量：论证链条是否严整、能否识别并回应矛盾"),
    ("completeness", "完整性：未解释证据/未解决矛盾/缺法条是否被显式识别"),
    ("uncertainty", "不确定性披露：是否如实披露存疑点与证据强度"),
]


_FORCE_MOCK = False


def _pick_case(case_id: str, text: str) -> dict:
    if case_id:
        p = os.path.join(settings.data_dir, "cases", f"{case_id}.json")
        if not os.path.exists(p):
            raise SystemExit(f"未找到案件 {case_id}（{p}）")
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    if text and text.strip():
        return {
            "id": "case_eval",
            "title": "评估用例",
            "text": text.strip(),
            "summary": text.strip()[:200],
        }
    d = os.path.join(settings.data_dir, "cases")
    files = sorted(f for f in os.listdir(d) if f.endswith(".json")) if os.path.isdir(d) else []
    if not files:
        raise SystemExit("案例库为空。请用 --case <id> 或 --text \"…\" 提供案件。")
    with open(os.path.join(d, files[0]), encoding="utf-8") as f:
        return json.load(f)


def _extract_json_object(text: str) -> dict:
    """从 judge 响应中提取第一个可解析的 JSON 对象（含代码块包裹）。"""
    text = text or ""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def _summarize(events: list) -> dict:
    verdict = next((e.get("verdict") for e in events if e.get("kind") == "verdict"), None)
    selfcheck = next((e.get("selfcheck") for e in events if e.get("kind") == "selfcheck"), None) or {}
    reflections = next((e.get("reflections") for e in events if e.get("kind") == "reflect"), None) or []
    notes = [e for e in events if e.get("kind") == "agent_end"]
    critical = (next((e.get("contradictions") for e in events if e.get("kind") == "critic_end"), []) or [])
    return {
        "verdict": verdict,
        "selfcheck": selfcheck,
        "reflections": reflections,
        "expert_notes": notes,
        "contradictions": critical,
        "citations_count": sum(1 for n in notes if n.get("citations")),
    }


def _deterministic_report(s: dict) -> dict:
    verdict = s["verdict"] or {}
    sc = s["selfcheck"] or {}
    return {
        "verdict_complete": bool(
            verdict.get("truth_hypothesis")
            and isinstance(verdict.get("evidence_chain"), list)
            and verdict.get("recommendation")
        ),
        "selfcheck_ok": bool(sc.get("ok")),
        "selfcheck_strength": round(float(sc.get("strength") or 0), 2),
        "selfcheck_issues": len(sc.get("issues") or []),
        "reflection_count": len(s["reflections"]),
        "grounded_notes": s["citations_count"],
    }


async def _llm_judge(case: dict, s: dict, cfg: dict, judge_model: str | None) -> dict:
    verdict = s["verdict"] or {}
    claims = "\n".join(
        f"- {n.get('name')}：{str(n.get('text') or '')[:160]}"
        for n in s["expert_notes"][:7]
    ) or "（无专家主张）"
    issues = "；".join(s["selfcheck"].get("issues") or []) or "（无）"
    prompt = (
        "你是一位严谨的司法质量评估法官。请评审以下 AI 合议庭的产出，"
        "按五个维度各打 1~10 分并给出简短理由。只输出 JSON，形如：\n"
        '{"factual_consistency": 8, "evidence_citation": 7, "reasoning": 8, '
        '"completeness": 6, "uncertainty": 9, "comments": "…"}\n\n'
        f"## 案卷摘要\n{str(case.get('summary') or case.get('text') or '')[:600]}\n\n"
        f"## 专家主张\n{claims}\n\n"
        f"## 裁决\n证据链: {json.dumps(verdict.get('evidence_chain') or [], ensure_ascii=False)[:300]}\n"
        f"存疑点: {json.dumps(verdict.get('doubts') or [], ensure_ascii=False)[:300]}\n"
        f"建议: {str(verdict.get('recommendation') or '')[:200]}\n\n"
        f"## 确定性自检（完整性/证据强度）\n强度: {s['selfcheck'].get('strength')}；"
        f"待复核项: {issues}"
    )
    llm = get_llm("评估法官", model=judge_model or None, cfg=cfg)
    resp = await stream_or_invoke(llm, [HumanMessage(content=prompt)], timeout=cfg.get("llm_timeout"))
    obj = _extract_json_object(str(resp.content))
    scores = {k: obj.get(k) for k, _ in DIMENSIONS}
    clean = {}
    for k, v in scores.items():
        try:
            clean[k] = max(1.0, min(10.0, float(v)))
        except (TypeError, ValueError):
            clean[k] = None
    clean["comments"] = str(obj.get("comments") or "")[:400]
    return clean


async def _run(case: dict, rounds: int) -> dict:
    cfg = debate_snapshot()
    cfg["max_rounds"] = max(1, min(int(rounds), settings.max_rounds))
    if _FORCE_MOCK:
        cfg["llm_provider"] = "mock"
        cfg["stream_experts"] = "off"
        cfg["parallel_experts"] = "off"
    brief = await preprocess(case, cfg=cfg)
    case = dict(case)
    case["brief"] = brief
    activate_case(case)
    graph = build_graph()
    events: list = []

    async def sink(event: dict) -> None:
        # 事件统一为 dict；个别节点可能直接透传纯文本，这里忽略非结构化项
        if isinstance(event, dict):
            events.append(event)

    config = {
        "configurable": {
            "thread_id": "eval-" + uuid.uuid4().hex[:8],
            "cfg": cfg,
            "sink": sink,
            "human_pop": lambda: None,
            "wait_for_human": lambda timeout=0: None,
            "hitl_timeout": 0,
            "note_tasks": [],
            "usage": {"calls": 0, "in_chars": 0, "out_chars": 0},
        }
    }
    inputs = {
        "case_id": case.get("id"),
        "case": case,
        "max_rounds": cfg["max_rounds"],
        "judge_mode": "ai",
        "agents": [],
    }
    await graph.ainvoke(inputs, config=config)
    await asyncio.gather(*config["configurable"].get("note_tasks", []), return_exceptions=True)
    return events


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM-as-judge 质量评估器")
    ap.add_argument("--case", default="", help="案例 ID（如 case_001）")
    ap.add_argument("--text", default="", help="直接提供案件描述文本")
    ap.add_argument("--dataset", default="", help="评测集名（data/evals/<name>.json）：批量跑多场景并汇总")
    ap.add_argument("--rounds", type=int, default=1, help="辩论轮数（默认 1，节省调用）")
    ap.add_argument("--judge", default="", help="judge 模型名（默认用 LLM_MODEL）")
    ap.add_argument("--fail-below", type=float, default=0, help="平均分低于此值退出码 1（0=不判定）")
    ap.add_argument("--json", default="", help="额外把报告写入该 JSON 文件")
    ap.add_argument(
        "--mock",
        action="store_true",
        help="强制用 mock 供应商（离线确定性回归，CI 用）；覆盖环境变量 LLM_PROVIDER",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="回归检查模式：跑 mock 场景并断言确定性门槛（裁决完整/自检通过等），"
        "任一不达标退出码 1。设计给 CI 快速回归，无需真实模型与 API Key",
    )
    args = ap.parse_args()

    # CI 回归/离线演示：本地强制 mock 快照即可，不改全局 settings/env，
    # 避免 reload 模块造成侧效应（其余 import 仍持有旧 settings 引用）。
    _FORCE_MOCK = args.mock or args.check

    if args.dataset:
        return _run_dataset(args)

    case = _pick_case(args.case, args.text)
    print(f"案件: {case.get('title') or case.get('id')} · 轮数 {args.rounds}")

    events = asyncio.run(_run(case, max(1, int(args.rounds))))
    summary = _summarize(events)
    det = _deterministic_report(summary)
    print("\n== 确定性指标 ==")
    for k, v in det.items():
        print(f"  {k}: {v}")

    report: dict = {"case": case.get("title"), "deterministic": det, "llm_judge": None}
    if args.check:
        # 回归门槛（P0-3）：裁决字段完整、自检无阻断问题、有反思产出。
        # 放缓对轮数的依赖：mock 单轮可收敛，仅要求产出可消费。
        failures = []
        if not det["verdict_complete"]:
            failures.append("裁决字段不完整（truth_hypothesis/evidence_chain/recommendation 缺失）")
        if det["selfcheck_ok"] is False and det["selfcheck_issues"] >= 1:
            if det["selfcheck_strength"] < 0.4:
                failures.append(f"自检强度过低 {det['selfcheck_strength']}，且存在 {det['selfcheck_issues']} 项待复核")
        if det["reflection_count"] == 0:
            failures.append("反思（可证伪性审查）未产出任何条目")
        if failures:
            print("\n✗ 回归检查未通过：")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("\n✓ 回归检查通过（裁决完整 / 自检达标 / 反思产出）")
        report["check"] = "ok"
        return 0
    if is_mock():  # mock 模式下仅确定性指标；真实模型接入后再打分
        print("\nLLM-as-judge 跳过：LLM_PROVIDER=mock（仅确定性指标）。使用真实模型接入后再打分。")
    else:
        cfg = debate_snapshot()
        scores = asyncio.run(_llm_judge(case, summary, cfg, args.judge or None))
        report["llm_judge"] = scores
        print("\n== LLM-as-judge 评分（1-10）==")
        avg = 0.0
        n = 0
        for k, label in DIMENSIONS:
            v = scores.get(k)
            if v is None:
                print(f"  {label}: 解析失败")
                continue
            avg += v
            n += 1
            print(f"  {label}: {v:.1f}")
        if n:
            avg /= n
            print(f"  平均: {avg:.2f}")
            if args.fail_below and avg < args.fail_below:
                print(f"  ✗ 低于阈值 {args.fail_below}")
                return 1
        if scores.get("comments"):
            print(f"  评语: {scores['comments']}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n报告已写入 {args.json}")
    return 0


# ------------------------- 评测集批量（P2-7） -------------------------
# 对标大厂 eval 平台：评测集独立成文件（data/evals/<name>.json），
# 一次批量跑多场景并汇总通过率/平均分，结果落盘 data/evals/results/ 供趋势追踪。
# 集文件格式：{"name": "...", "template": "...可选: 把 {summary} 占位替换为场景正文",
#  "cases": [{"id": "...", "title": "...", "text": "..."}], "expected": {"intent": "..."(可选)}}

EVALS_DIR = os.path.join(settings.data_dir, "evals")
EVALS_RESULTS_DIR = os.path.join(EVALS_DIR, "results")


def _load_dataset(name: str) -> dict:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(name or ""))
    path = os.path.join(EVALS_DIR, f"{safe}.json")
    if not os.path.exists(path):
        files = sorted(f for f in os.listdir(EVALS_DIR) if f.endswith(".json")) if os.path.isdir(EVALS_DIR) else []
        avail = ", ".join(f[:-5] for f in files) or "（无）"
        raise SystemExit(f"评测集 {name} 不存在（{path}）。可用: {avail}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    cases = data.get("cases") or []
    if not cases:
        raise SystemExit(f"评测集 {name} 没有任何场景")
    return {"name": str(data.get("name") or safe), "template": data.get("template") or "", "cases": cases, "expected": data.get("expected") or {}}


def _case_from_scene(scene: dict, tpl: str) -> dict:
    text = str(scene.get("text") or "").strip()
    if tpl and "{summary}" in tpl:
        text = tpl.replace("{summary}", text)
    return {
        "id": str(scene.get("id") or ("eval-" + uuid.uuid4().hex[:8])),
        "title": str(scene.get("title") or ("评估场景" + str(scene.get("id") or ""))),
        "text": text or "评估场景（无正文）",
        "summary": text[:200],
    }


def _run_dataset(args) -> int:
    ds = _load_dataset(args.dataset)
    rounds = max(1, int(args.rounds))
    print(f"== 评测集 {ds['name']}：{len(ds['cases'])} 个场景 × {rounds} 轮 ==")
    total_det = {"verdict_complete": 0, "selfcheck_ok": 0, "reflection_ok": 0, "scores": []}
    results = []
    fails = []
    for i, scene in enumerate(ds["cases"], 1):
        case = _case_from_scene(scene, ds["template"])
        try:
            events = asyncio.run(_run(case, rounds))
            summary = _summarize(events)
            det = _deterministic_report(summary)
            entry = {"index": i, "case": case["id"], "title": case["title"], "deterministic": det}
            total_det["verdict_complete"] += 1 if det["verdict_complete"] else 0
            total_det["selfcheck_ok"] += 1 if det["selfcheck_ok"] else 0
            total_det["reflection_ok"] += 1 if det["reflection_count"] > 0 else 0
            if not is_mock():
                sc = asyncio.run(_llm_judge(case, summary, debate_snapshot(), args.judge or None))
                if sc.get("factual_consistency") is not None:
                    total_det["scores"].append(sc)
                    entry["llm_judge"] = sc
            results.append(entry)
            mark = "✓" if det["verdict_complete"] else "✗"
            print(f"  [{i}/{len(ds['cases'])}] {mark} {case['title']} 裁决完整={det['verdict_complete']} 自检={det['selfcheck_ok']} 反思={det['reflection_count']}")
            if not det["verdict_complete"]:
                fails.append(case["title"])
        except Exception as ex:  # noqa: BLE001
            fails.append(f"{case['title']}（异常：{str(ex)[:120]}）")
            results.append({"index": i, "case": case["id"], "title": case["title"], "error": str(ex)[:160]})

    n = len(ds["cases"])
    report = {
        "dataset": ds["name"],
        "cases": n,
        "rounds": rounds,
        "verdict_complete_rate": round(total_det["verdict_complete"] / n, 3),
        "selfcheck_ok_rate": round(total_det["selfcheck_ok"] / n, 3),
        "reflection_rate": round(total_det["reflection_ok"] / n, 3),
        "results": results,
        "failed_scenes": fails,
    }
    if total_det["scores"]:
        def _avg_of(k) -> float:
            vals = [s.get(k) or 0 for s in total_det["scores"]]
            return round(sum(vals) / len(vals), 2)

        report["llm_judge_avg"] = {k: _avg_of(k) for k, _ in DIMENSIONS}

    print("\n== 汇总 ==")
    print(f"  裁决完整率: {report['verdict_complete_rate']}")
    print(f"  自检通过率: {report['selfcheck_ok_rate']}")
    print(f"  反思产出率: {report['reflection_rate']}")
    if report.get("llm_judge_avg"):
        print("  LLM-as-judge 平均分:")
        for k, _l in DIMENSIONS:
            print(f"    {k}: {report['llm_judge_avg'][k]}")
    if fails:
        print(f"  ✗ 未达标场景: {fails}")

    # 落盘结果（含时间戳）供趋势追踪；保留最近 50 次
    try:
        os.makedirs(EVALS_RESULTS_DIR, exist_ok=True)
        ts = __import__("time").strftime("%Y%m%d-%H%M%S")
        out_path = os.path.join(EVALS_RESULTS_DIR, f"{ds['name']}-{ts}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"  结果已落盘: {out_path}")
    except Exception as e:  # noqa: BLE001
        print(f"  （结果落盘失败：{e}）")

    if args.json:
        try:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f"  完整报告已写入 {args.json}")
        except Exception as e:  # noqa: BLE001
            print(f"  （报告写入失败：{e}）")

    # 门槛判定：任一场景裁决不完整即失败（与 --check 语义一致）
    if fails and args.fail_below:
        print(f"\n✗ 有 {len(fails)} 个场景未达标，门槛 --fail-below 触发")
        return 1
    if fails and args.check:
        return 1
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())