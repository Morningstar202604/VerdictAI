from __future__ import annotations

import json
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Rectangle

from app.config import settings

# 选择系统中存在的中文字体，避免图表中文乱码
_CANDIDATES = [
    "Microsoft YaHei",
    "SimHei",
    "SimSun",
    "Arial Unicode MS",
    "Noto Sans CJK SC",
]
_AVAIL = {f.name for f in font_manager.fontManager.ttflist}
_FONT = next((c for c in _CANDIDATES if c in _AVAIL), None)
if _FONT:
    plt.rcParams["font.sans-serif"] = [_FONT]
    plt.rcParams["axes.unicode_minus"] = False


CASE = {
    "id": "case_001",
    "title": "江城「3·15」别墅命案",
    "summary": (
        "2026年3月15日凌晨，江城市西山区碧水别墅区A3栋发生一起命案。"
        "女主人林晚（34岁）被发现死于二楼主卧，初步判定为他杀。"
        "主要嫌疑人系其丈夫周明远（38岁，明远科技创始人）与商业伙伴高野（40岁，合伙人）。"
        "现场留有争执痕迹、一把带血水果刀（E-01）、被剪辑过的监控录像（E-02），"
        "以及一份近期大幅提升保额的人身保险（F-03）。"
        "命案背后牵涉巨额股权对赌协议、一笔蹊跷的跨境转账，以及刀柄上一个身份不明的男性DNA——案件证据犬牙交错、相互矛盾。"
    ),
    "persons": [
        {
            "name": "林晚",
            "role": "被害人",
            "age": 34,
            "desc": "别墅女主人，生前经营「晚·画廊」，同时是明远科技股东（持股24%）",
            "height": 165,
            "weight": 52,
            "medical": "无重大疾病，无遗嘱、子女",
        },
        {
            "name": "周明远",
            "role": "嫌疑人/丈夫",
            "age": 38,
            "desc": "明远科技创始人、第一大股东（持股51%），与林晚婚后关系紧张，正办理离婚",
            "height": 178,
            "weight": 76,
            "medical": "右肩旧伤，长期服用安眠药",
        },
        {
            "name": "高野",
            "role": "嫌疑人/商业伙伴",
            "age": 40,
            "desc": "明远科技合伙人（持股25%），与林晚有暧昧传闻，案发当晚曾到访别墅",
            "height": 182,
            "weight": 84,
            "medical": "左颊有陈旧刀疤",
        },
        {
            "name": "保姆张姨",
            "role": "证人",
            "age": 56,
            "desc": "当晚住于别墅一层佣人房，自称听见二楼争吵，但细节前后矛盾",
            "height": 158,
            "weight": 60,
            "medical": None,
        },
        {
            "name": "程Sir",
            "role": "警官/现场指挥",
            "age": 45,
            "desc": "西山区刑侦一队队长，负责本案侦查",
            "height": None,
            "weight": None,
            "medical": None,
        },
        {
            "name": "钱经理",
            "role": "明远科技财务总监",
            "age": 41,
            "desc": "掌握公司账目，称替周明远处理过高野的『特别支出』",
            "height": None,
            "weight": None,
            "medical": None,
        },
    ],
    "timeline": [
        {
            "time": "2026-03-14 19:40",
            "event": "林晚离开画廊，微信告知周明远『今晚早点回来谈离婚』",
            "source": "林晚手机微信",
        },
        {
            "time": "2026-03-14 20:50",
            "event": "周明远从公司出发回家，驾车路线显示曾绕行至城南高架",
            "source": "ETC/导航记录",
        },
        {
            "time": "2026-03-14 21:30",
            "event": "周明远与高野在别墅一楼书房饮酒谈股权对赌",
            "source": "高野供述/指纹",
        },
        {
            "time": "2026-03-14 22:15",
            "event": "林晚到中介公司咨询出售名下股权事宜",
            "source": "中介登记",
        },
        {
            "time": "2026-03-14 22:40",
            "event": "林晚返家，与周明远发生激烈争吵（保姆听见玻璃碎裂声）",
            "source": "保姆证词",
        },
        {
            "time": "2026-03-14 23:05",
            "event": "监控显示高野沿楼梯上二楼，23:50返回",
            "source": "一楼走廊监控",
        },
        {
            "time": "2026-03-14 23:20",
            "event": "周明远手机向高野发送『搞定没』，随后信息被删除",
            "source": "运营商数据",
        },
        {
            "time": "2026-03-15 00:05",
            "event": "一座境外银行账户向高野账户转入 200 万美元",
            "source": "资金流水",
        },
        {
            "time": "2026-03-15 00:15",
            "event": "周明远称自己在书房独处至凌晨，两次向高野电话",
            "source": "周明远供述/通话记录",
        },
        {
            "time": "2026-03-15 01:40",
            "event": "监控显示一楼走廊出现一个戴帽子男子的身影（约3秒，身份不明）",
            "source": "监控回放",
        },
        {
            "time": "2026-03-15 07:20",
            "event": "保姆发现林晚死于主卧并报警",
            "source": "报警记录",
        },
        {
            "time": "2026-03-15 07:35",
            "event": "警方到场，封锁现场并提取血迹、凶器、指纹",
            "source": "现场勘验",
        },
    ],
    "evidence": [
        {
            "id": "E-01",
            "type": "凶器",
            "desc": "主卧床头带血水果刀，刀柄提取到混合DNA（含林晚与一未知男性），刀刃与林晚伤口吻合",
            "reliability": 0.92,
            "chain_intact": True,
            "tag": "关键物证",
        },
        {
            "id": "E-02",
            "type": "监控",
            "desc": "一楼走廊监控23:05-23:50记录高野上楼，录像存在约5分钟刻意缺失",
            "reliability": 0.6,
            "chain_intact": False,
            "tag": "矛盾",
        },
        {
            "id": "E-03",
            "type": "法医",
            "desc": "林晚死因为单刃锐器刺中心脏，死亡时间推定23:00-00:00，颈上有扼痕",
            "reliability": 0.95,
            "chain_intact": True,
            "tag": "关键物证",
        },
        {
            "id": "E-04",
            "type": "电子数据",
            "desc": "周明远手机23:20向高野发送『搞定没』，随后删除；00:15两次拨打高野",
            "reliability": 0.85,
            "chain_intact": True,
            "tag": "矛盾",
        },
        {
            "id": "E-05",
            "type": "物证",
            "desc": "书房沙发下发现高野袖扣一枚，扣眼附着一根非林晚的浅色卷发",
            "reliability": 0.72,
            "chain_intact": True,
            "tag": None,
        },
        {
            "id": "E-06",
            "type": "口供",
            "desc": "周明远称整晚未上二楼且不知高野上楼，与监控、门磁记录存在冲突",
            "reliability": 0.3,
            "chain_intact": True,
            "tag": "矛盾",
        },
        {
            "id": "F-01",
            "type": "资金",
            "desc": "案发前两周，一处境外离岸账户与周明远控股的瑞昇贸易存在频繁往来",
            "reliability": 0.7,
            "chain_intact": True,
            "tag": None,
        },
        {
            "id": "F-02",
            "type": "资金",
            "desc": "00:05 高野账户收到 200 万美元转账，付款方为林晚曾咨询出售股权的股东",
            "reliability": 0.66,
            "chain_intact": True,
            "tag": "矛盾",
        },
        {
            "id": "F-03",
            "type": "保单",
            "desc": "案发前一个月，林晚人寿保险保额由 300 万骤升至 2000 万，受益人为周明远",
            "reliability": 0.88,
            "chain_intact": True,
            "tag": "动机",
        },
        {
            "id": "F-04",
            "type": "合同",
            "desc": "周明远与高野签有股权对赌协议：若明远科技2026年财报未达约定，周需向高野让渡15%股权",
            "reliability": 0.9,
            "chain_intact": True,
            "tag": "动机",
        },
    ],
    "statutes": [
        {
            "topic": "故意杀人",
            "text": "《刑法》第232条：故意杀人的，处死刑、无期徒刑或十年以上有期徒刑。",
        },
        {
            "topic": "保险诈骗",
            "text": "《刑法》第198条：投保人、被保险人或者受益人以非法占有为目的编造保险事故的，构成保险诈骗罪。",
        },
        {
            "topic": "非法证据排除",
            "text": "《刑事诉讼法》第56条：以非法方法收集的证据应当予以排除；物证、书证不符合法定程序，可能严重影响司法公正的，应当排除或作出补正。",
        },
        {
            "topic": "证明标准",
            "text": "刑事诉讼证明标准：事实清楚，证据确实、充分，排除合理怀疑。",
        },
    ],
    "finance": [
        {
            "item": "境外离岸账户→瑞昇贸易",
            "amount": "$340 万",
            "date": "03-01",
            "note": "往来频繁",
        },
        {
            "item": "林晚人寿保额提升",
            "amount": "300万→2000万",
            "date": "02-12",
            "note": "受益人为周",
        },
        {
            "item": "高野账户收款",
            "amount": "$200 万",
            "date": "03-15 00:05",
            "note": "案发当晚",
        },
        {
            "item": "周明远境外账户",
            "amount": "$180 万",
            "date": "02-20",
            "note": "资金来源存疑",
        },
    ],
    "dna_persons": [
        {"name": "林晚", "matched": True, "note": "主卧血迹（被害人）"},
        {"name": "周明远", "matched": False, "note": "书房酒杯/指纹"},
        {"name": "高野", "matched": False, "note": "一楼门把手指纹"},
        {"name": "未知男性", "matched": True, "note": "刀柄混合DNA·未比对成功"},
        {"name": "保姆张姨", "matched": False, "note": "佣人房个人物品"},
    ],
    "contacts": [
        {
            "from": "周明远",
            "to": "高野",
            "time": "23:20",
            "type": "短信·已删除",
            "note": "『搞定没』",
        },
        {
            "from": "周明远",
            "to": "高野",
            "time": "00:15",
            "type": "电话",
            "note": "时长 42s",
        },
        {
            "from": "林晚",
            "to": "周明远",
            "time": "19:40",
            "type": "语音",
            "note": "谈离婚",
        },
        {
            "from": "高野",
            "to": "未知号码",
            "time": "22:02",
            "type": "短信",
            "note": "内容已恢复",
        },
    ],
    "contradictions": [],
}

ASSETS_REL = "assets"


def _save_case(path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(CASE, f, ensure_ascii=False, indent=2)


def _chart_timeline(out: str) -> None:
    events = CASE["timeline"]
    fig, ax = plt.subplots(figsize=(10, 3.2))
    for i, e in enumerate(events):
        ax.plot([i, i], [0, 1], color="#334155", lw=1, alpha=0.4)
        ax.scatter(i, 0.5, s=120, color="#38bdf8", zorder=3)
        ax.text(i, 0.62, e["time"].split(" ")[1], rotation=45, ha="right", fontsize=8)
        ax.text(
            i,
            0.38,
            e["event"][:18],
            rotation=45,
            ha="right",
            fontsize=7,
            color="#475569",
        )
    ax.set_ylim(-0.1, 1.1)
    ax.set_xlim(-0.5, len(events) - 0.5)
    ax.axis("off")
    ax.set_title("关键时间线（含证据来源）", fontsize=11, color="#0f172a")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def _chart_evidence(out: str) -> None:
    items = CASE["evidence"]
    names = [f"{e['id']}\n{e['type']}" for e in items]
    vals = [e["reliability"] for e in items]
    colors = ["#34d399" if e["chain_intact"] else "#f87171" for e in items]
    fig, ax = plt.subplots(figsize=(10, 3.6))
    bars = ax.bar(names, vals, color=colors)
    ax.set_ylim(0, 1)
    ax.set_ylabel("可靠性", fontsize=9)
    ax.set_title(
        "证据可靠性与保管链（绿=完整 / 红=瑕疵）", fontsize=11, color="#0f172a"
    )
    for b, v in zip(bars, vals):
        ax.text(
            b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.2f}", ha="center", fontsize=8
        )
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def _chart_scene(out: str) -> None:
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.add_patch(Rectangle((0, 0), 10, 10, fill=False, lw=2, color="#334155"))
    ax.add_patch(Rectangle((1, 1), 4, 3, fill=True, color="#e2e8f0", lw=1))  # 书房
    ax.add_patch(Rectangle((6, 6), 3, 3, fill=True, color="#fee2e2", lw=1))  # 主卧
    ax.text(3, 2.5, "书房", ha="center", fontsize=9)
    ax.text(7.5, 7.5, "主卧(案发现场)", ha="center", fontsize=9, color="#b91c1c")
    ax.plot([3, 7.5], [2.5, 7.5], "--", color="#38bdf8", lw=1.5)
    ax.scatter([3, 7.5], [2.5, 7.5], color="#38bdf8", s=60)
    # 一楼走廊监控位
    ax.add_patch(Rectangle((1, 7.5), 2, 0.8, fill=False, color="#64748b", lw=1))
    ax.text(2, 8.1, "一楼走廊·监控位", ha="center", fontsize=8, color="#64748b")
    ax.set_xlim(-0.5, 10.5)
    ax.set_ylim(-0.5, 10.5)
    ax.axis("off")
    ax.set_title(
        "现场平面图（示意：书房→主卧动线＋走廊监控）", fontsize=11, color="#0f172a"
    )
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def _parse_amount(s: str) -> float:
    """宽松解析金额字符串为数值（万元/万美元单位）。区间取最大值。"""
    import re as _re
    s = str(s or "").replace("$", "").strip()
    nums = _re.findall(r"([\d.]+)\s*(万|亿)?", s)
    if not nums:
        return 0.0
    is_range = "→" in s or "至" in s or "~" in s
    values = []
    for num, unit in nums:
        try:
            n = float(num)
        except ValueError:
            continue
        if unit == "亿":
            n *= 10000
        values.append(n)
    return max(values) if is_range else (sum(values) if values else 0.0)


def _chart_motive(out: str) -> None:
    """资金/动机流向图（横向条形 + 金额标注）。"""
    items = CASE.get("finance", [])
    labels = [it["item"] for it in items]
    amounts = [_parse_amount(it["amount"]) for it in items]
    # 按粗略金额排序展示
    fig, ax = plt.subplots(figsize=(10, 3.6))
    y = range(len(items))
    bars = ax.barh(list(y), amounts, color=["#f472b6", "#60a5fa", "#fb7185", "#34d399"])
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=8.5)
    for b, it in zip(bars, items):
        ax.text(
            b.get_width() + 5,
            b.get_y() + b.get_height() / 2,
            it["amount"],
            va="center",
            fontsize=8,
        )
    ax.set_xlabel("相对金额（万美元/万元，示意）", fontsize=8)
    ax.invert_yaxis()
    ax.set_title(
        "资金与动机流向图（受益人/转账/对赌/保单）", fontsize=11, color="#0f172a"
    )
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def _chart_dna(out: str) -> None:
    """DNA 比对矩阵（热力图式）。"""
    persons = CASE.get("dna_persons", [])
    rows = [p["name"] for p in persons]
    vals = [1.0 if p["matched"] else 0.0 for p in persons]
    fig, ax = plt.subplots(figsize=(9, 3.4))
    colors = ["#b91c1c" if v else "#cbd5e1" for v in vals]
    ax.barh(range(len(rows)), [1] * len(rows), color=colors, alpha=0.85)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(rows, fontsize=9)
    for i, p in enumerate(persons):
        ax.text(
            0.5,
            i,
            "√ 匹配" if p["matched"] else "× 未匹配",
            ha="center",
            va="center",
            fontsize=8,
            color="#fff" if p["matched"] else "#334155",
        )
    ax.set_xticks([])
    ax.set_xlim(0, 1)
    ax.invert_yaxis()
    ax.set_title("DNA 比对结果（红=命中 · 灰=未命中）", fontsize=11, color="#0f172a")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def _chart_communication(out: str) -> None:
    """通讯关系网络图。"""
    contacts = CASE.get("contacts", [])
    nodes = {}
    edges = []
    for c in contacts:
        if c["from"] not in nodes:
            nodes[c["from"]] = len(nodes)
        if c["to"] not in nodes:
            nodes[c["to"]] = len(nodes)
        edges.append((nodes[c["from"]], nodes[c["to"]], c["type"], c["note"]))
    fig, ax = plt.subplots(figsize=(6, 5))
    # 简单环形布局
    n = len(nodes)
    import math

    coords = {
        i: (math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n))
        for i in range(n)
    }
    for a, b, typ, note in edges:
        x1, y1 = coords[a]
        x2, y2 = coords[b]
        ax.plot([x1, x2], [y1, y2], "-", color="#94a3b8", lw=1.2, alpha=0.7)
        ax.text((x1 + x2) / 2, (y1 + y2) / 2, typ, fontsize=6.5, color="#64748b")
    for idx, (name, i) in enumerate(nodes.items()):
        x, y = coords[i]
        color = "#f87171" if "未知" in name or "未知号码" in name else "#38bdf8"
        ax.scatter(x, y, s=520, color=color, zorder=3, edgecolor="#fff")
        ax.text(
            x,
            y - 0.18,
            name,
            ha="center",
            fontsize=8,
            color="#0f172a",
            fontweight="bold",
        )
    ax.set_xlim(-1.5, 1.5)
    ax.set_ylim(-1.5, 1.5)
    ax.axis("off")
    ax.set_title("案发前后通讯关系（短信/电话/语音）", fontsize=11, color="#0f172a")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def _chart_bloodstain(out: str) -> None:
    """血迹分布示意（散点 + 中心冲击点）。"""
    fig, ax = plt.subplots(figsize=(6, 5))
    import random

    random.seed(42)
    # 中心点血迹
    ax.scatter([0], [0], s=300, color="#991b1b", zorder=4)
    # 溅射血迹
    for _ in range(90):
        ang = random.uniform(0, 2 * 3.14159)
        r = random.uniform(0.3, 2.4)
        x = r * random.uniform(0.6, 1) * math.cos(ang)
        y = r * random.uniform(0.6, 1) * math.sin(ang)
        ax.scatter(x, y, s=random.uniform(6, 22), color="#b91c1c", alpha=0.55)
    # 刀痕方向
    ax.annotate(
        "",
        xy=(1.8, 0.6),
        xytext=(-1.6, -0.5),
        arrowprops=dict(arrowstyle="->", color="#fbbf24", lw=2),
    )
    ax.text(1.9, 0.75, "刺入方向", fontsize=9, color="#92400e")
    ax.set_xlim(-3, 3)
    ax.set_ylim(-3, 3)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("主卧血迹分布与刺入方向（示意）", fontsize=11, color="#0f172a")
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)


def generate() -> str:
    d = os.path.join(settings.data_dir, "cases")
    os.makedirs(d, exist_ok=True)
    assets = os.path.join(d, ASSETS_REL)
    os.makedirs(assets, exist_ok=True)
    _save_case(os.path.join(d, f"{CASE['id']}.json"))
    _chart_timeline(os.path.join(assets, "timeline.png"))
    _chart_evidence(os.path.join(assets, "evidence.png"))
    _chart_scene(os.path.join(assets, "scene.png"))
    _chart_motive(os.path.join(assets, "motive.png"))
    _chart_dna(os.path.join(assets, "dna.png"))
    _chart_communication(os.path.join(assets, "communication.png"))
    _chart_bloodstain(os.path.join(assets, "bloodstain.png"))
    base = f"/static/data/cases/{ASSETS_REL}/"
    CASE["charts"] = {
        "关键时间线": base + "timeline.png",
        "证据可靠性": base + "evidence.png",
        "现场平面图": base + "scene.png",
        "资金/动机流向": base + "motive.png",
        "DNA 比对": base + "dna.png",
        "通讯关系网": base + "communication.png",
        "血迹分布与刺入方向": base + "bloodstain.png",
    }
    _save_case(os.path.join(d, f"{CASE['id']}.json"))
    return os.path.join(d, f"{CASE['id']}.json")


if __name__ == "__main__":
    p = generate()
    print("case generated:", p)
