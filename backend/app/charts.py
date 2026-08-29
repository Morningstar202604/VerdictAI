from __future__ import annotations

import os
from typing import Dict, List

import matplotlib
from matplotlib import font_manager

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

from app.config import settings

# 注册中文字体，避免图表中文显示为方块
for _cand in (
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/NotoSansSC-VF.ttf",
):
    if os.path.exists(_cand):
        try:
            font_manager.fontManager.addfont(_cand)
            plt.rcParams["font.sans-serif"] = [
                font_manager.FontProperties(fname=_cand).get_name()
            ]
            plt.rcParams["axes.unicode_minus"] = False
            break
        except Exception:
            pass


def _out_dir(case_id: str) -> str:
    d = os.path.join(settings.data_dir, "cases", "assets", case_id)
    os.makedirs(d, exist_ok=True)
    return d


def _bar(ax, labels, values, title, color="#1f3a5f"):
    ax.bar(range(len(labels)), values, color=color)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=7, rotation=30, ha="right")
    ax.set_title(title, fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def generate_charts(case: dict) -> Dict[str, str]:
    """根据案件数据生成图表，返回 {标签: 访问URL}。仅生成有数据支撑的图。"""
    case_id = case.get("id") or "case"
    out = _out_dir(case_id)
    charts: Dict[str, str] = {}
    plt.rcParams["figure.dpi"] = 110

    # 1. 证据可靠性
    evs = case.get("evidence") or []
    if evs:
        fig, ax = plt.subplots(figsize=(4, 2.4))
        labels = [e.get("id", "?") for e in evs]
        vals = [(e.get("reliability") or 0) * 100 for e in evs]
        _bar(ax, labels, vals, "证据可靠性 (%)", "#7f1d1d")
        p = os.path.join(out, "evidence.png")
        fig.tight_layout()
        fig.savefig(p)
        plt.close(fig)
        charts["证据可靠性"] = f"/static/data/cases/assets/{case_id}/evidence.png"

    # 2. 关键时间线
    tl = case.get("timeline") or []
    if tl:
        fig, ax = plt.subplots(figsize=(4, 2.4))
        ys = list(range(len(tl)))[::-1]
        for y, t in zip(ys, tl):
            ax.plot([0, 1], [y, y], color="#94a3b8", lw=1)
            ax.text(0.02, y, (t.get("time", "") or "")[:12], fontsize=7, va="center")
            ax.text(0.15, y, (t.get("event", "") or "")[:22], fontsize=7, va="center")
        ax.set_xlim(0, 1)
        ax.set_ylim(-0.5, len(tl) - 0.5)
        ax.set_yticks([])
        ax.set_xticks([])
        ax.set_title("关键时间线", fontsize=9)
        for s in ("top", "right", "left", "bottom"):
            ax.spines[s].set_visible(False)
        p = os.path.join(out, "timeline.png")
        fig.tight_layout()
        fig.savefig(p)
        plt.close(fig)
        charts["关键时间线"] = f"/static/data/cases/assets/{case_id}/timeline.png"

    # 3. 通讯关系网
    comm = case.get("communication") or []
    if comm:
        fig, ax = plt.subplots(figsize=(4, 2.4))
        persons = case.get("persons") or []
        names = [p.get("name", f"P{i}") for i, p in enumerate(persons)] or [
            "A",
            "B",
            "C",
        ]
        pos = {n: (i / max(1, len(names) - 1), 0.5) for i, n in enumerate(names)}
        for c in comm:
            a = c.get("from") or (names[0] if names else "A")
            b = c.get("to") or (names[-1] if names else "B")
            if a in pos and b in pos:
                arrow = FancyArrowPatch(
                    pos[a],
                    pos[b],
                    arrowstyle="-|>",
                    mutation_scale=8,
                    color="#2563eb",
                    lw=1,
                )
                ax.add_patch(arrow)
        for n, (x, y) in pos.items():
            ax.plot(x, y, "o", color="#1f3a5f", markersize=8)
            ax.text(x, y + 0.08, n, fontsize=7, ha="center")
        ax.set_xlim(-0.1, 1.1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.set_title("通讯关系网", fontsize=9)
        p = os.path.join(out, "communication.png")
        fig.tight_layout()
        fig.savefig(p)
        plt.close(fig)
        charts["通讯关系网"] = f"/static/data/cases/assets/{case_id}/communication.png"

    # 4. 资金/动机流向
    fin = case.get("financial") or case.get("motive") or []
    if fin:
        fig, ax = plt.subplots(figsize=(4, 2.4))
        labels = [f.get("from", "?") + "→" + f.get("to", "?") for f in fin][:8]
        vals = [abs(f.get("amount", 0)) or 1 for f in fin][:8]
        _bar(ax, labels, vals, "资金/动机流向", "#b45309")
        p = os.path.join(out, "motive.png")
        fig.tight_layout()
        fig.savefig(p)
        plt.close(fig)
        charts["资金/动机流向"] = f"/static/data/cases/assets/{case_id}/motive.png"

    return charts
