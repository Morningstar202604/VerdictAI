# -*- coding: utf-8 -*-
"""垂直领域知识库：内置法条库（真实条文）+ 用户自定义知识条目。

三级检索顺序：本案卷宗自带法条（由 tools.search_case_law 处理）
→ 用户自定义知识库（data/knowledge_base.json）
→ 内置法条库（builtin，关键词命中）。

条文只收录广为人知、编号稳定的条款，避免模型幻觉法号；
检索为确定性的关键词/子串匹配，离线可用。
"""
from __future__ import annotations

import json
import os
import threading
import uuid

from app.config import settings
from app.data.store import atomic_write_json

_KB_LOCK = threading.Lock()


def _kb_path() -> str:
    return os.path.join(settings.data_dir, "knowledge_base.json")


# ----------------------------- 内置法条库 -----------------------------

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9,
              "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5,
              "陆": 6, "柒": 7, "捌": 8, "玖": 9}
_CN_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}


def cn_to_int(s: str) -> int:
    """中文数字（至多四位）→ int；已是阿拉伯数字则直接解析；解析失败返回 -1。
    仅服务法条编号匹配，不支持「万」及以上。"""
    s = (s or "").strip()
    if not s:
        return -1
    if all(ch.isdigit() for ch in s):
        return int(s)
    total = 0
    num = 0
    ok = False
    for ch in s:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
            ok = True
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            total += (num or 1) * unit
            num = 0
            ok = True
        else:
            return -1
    return total + num if ok else -1


BUILTIN: list[dict] = [
    {
        "id": "b-csl-50", "source": "builtin", "category": "刑事 · 证据规则",
        "law": "中华人民共和国刑事诉讼法", "article_no": 50,
        "title": "《中华人民共和国刑事诉讼法》第50条（证据定义）",
        "keywords": ["证据", "查证属实", "定案", "物证", "书证"],
        "text": "可以用于证明案件事实的材料，都是证据。证据包括：物证；书证；证人证言；被害人陈述；犯罪嫌疑人、被告人供述和辩解；鉴定意见；勘验、检查、辨认、侦查实验等笔录；视听资料、电子数据。证据必须经过查证属实，才能作为定案的根据。",
    },
    {
        "id": "b-csl-55", "source": "builtin", "category": "刑事 · 证明标准",
        "law": "中华人民共和国刑事诉讼法", "article_no": 55,
        "title": "《中华人民共和国刑事诉讼法》第55条（重证据、证明标准）",
        "keywords": ["证明标准", "排除合理怀疑", "口供", "证据确实充分", "孤证"],
        "text": "对一切案件的判处都要重证据，重调查研究，不轻信口供。只有被告人供述，没有其他证据的，不能认定被告人有罪；没有被告人供述，证据确实、充分的，可以认定被告人有罪。证据确实、充分的条件：定罪量刑的事实都有证据证明；证据经法定程序查证属实；综合全案证据，对所认定事实已排除合理怀疑。",
    },
    {
        "id": "b-csl-56", "source": "builtin", "category": "刑事 · 非法证据排除",
        "law": "中华人民共和国刑事诉讼法", "article_no": 56,
        "title": "《中华人民共和国刑事诉讼法》第56条（非法证据排除）",
        "keywords": ["非法证据", "排除", "刑讯逼供", "违法取证", "取证程序"],
        "text": "采用刑讯逼供等非法方法收集的犯罪嫌疑人、被告人供述和采用暴力、威胁等非法方法收集的证人证言、被害人陈述，应当予以排除。收集物证、书证不符合法定程序，可能严重影响司法公正的，应当予以补正或者作出合理解释；不能补正或者作出合理解释的，对该证据应当予以排除。",
    },
    {
        "id": "b-cl-232", "source": "builtin", "category": "刑事 · 罪名",
        "law": "中华人民共和国刑法", "article_no": 232, "charge": "故意杀人罪",
        "penalty_range": {"min_years": 0, "max_years": None, "kinds": ["管制", "拘役", "有期徒刑", "无期徒刑", "死刑"]},
        "title": "《中华人民共和国刑法》第232条（故意杀人罪）",
        "keywords": ["故意杀人", "命案", "他杀", "死亡", "剥夺他人生命"],
        "text": "故意杀人的，处死刑、无期徒刑或者十年以上有期徒刑；情节较轻的，处三年以上十年以下有期徒刑。",
    },
    {
        "id": "b-cl-233", "source": "builtin", "category": "刑事 · 罪名",
        "law": "中华人民共和国刑法", "article_no": 233, "charge": "过失致人死亡罪",
        "penalty_range": {"min_years": 0, "max_years": 7, "kinds": ["有期徒刑"]},
        "title": "《中华人民共和国刑法》第233条（过失致人死亡罪）",
        "keywords": ["过失致人死亡", "过失", "疏忽大意", "过于自信"],
        "text": "过失致人死亡的，处三年以上七年以下有期徒刑；情节较轻的，处三年以下有期徒刑。本法另有规定的，依照规定。",
    },
    {
        "id": "b-ev-3n", "source": "builtin", "category": "证据 · 审查要旨",
        "title": "证据「三性」审查要旨（质证框架）",
        "keywords": ["三性", "真实性", "合法性", "关联性", "质证", "审查"],
        "text": "单个证据须从三性审查：①真实性（证据本身客观真实存在，非伪造变造，注意原始载体与保管链）；②合法性（主体、程序、手段符合法律规定，注意非法证据排除）；③关联性（与待证事实有实质联系）。全案证据还须相互印证、形成闭环，方能达到证明标准。",
    },
    {
        "id": "b-ev-chain", "source": "builtin", "category": "证据 · 审查要旨",
        "title": "物证保管链审查要点（卷宗审查实务）",
        "keywords": ["保管链", "保管", "污染", "调换", "封存", "送检"],
        "text": "物证审查应核验：提取时间、地点、人员及见证人；封存、标识是否完整；保管、移交各环节记录是否连续无断点；送检样本与现场提取物是否同一。保管链存在断点的物证，其真实性、同一性存疑，须补正或合理解释，否则证明力显著降低。",
    },
    {
        "id": "b-ev-elec", "source": "builtin", "category": "证据 · 审查要旨",
        "title": "电子数据/监控录像审查要点",
        "keywords": ["电子数据", "监控", "录像", "剪辑", "完整性", "原始载体"],
        "text": "电子数据审查重点：是否随原始载体移送；完整性校验（哈希值）是否通过；提取、生成、存储环节记录是否完备；存在剪辑、删除、缺失的，缺失部分所涉事实不能认定，其余部分亦应审慎采信并结合其他证据印证。",
    },
    {
        "id": "b-mcl-577", "source": "builtin", "category": "民事 · 合同",
        "law": "中华人民共和国民法典", "article_no": 577,
        "title": "《中华人民共和国民法典》第577条（违约责任）",
        "keywords": ["违约", "合同", "继续履行", "违约责任"],
        "text": "当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。",
    },
    {
        "id": "b-mcl-590", "source": "builtin", "category": "民事 · 合同",
        "law": "中华人民共和国民法典", "article_no": 590,
        "title": "《中华人民共和国民法典》第590条（不可抗力）",
        "keywords": ["不可抗力", "免责", "不能预见", "不能避免"],
        "text": "当事人一方因不可抗力不能履行合同的，根据不可抗力的影响，部分或者全部免除责任，但法律另有规定的除外。因不可抗力不能履行合同的，应当及时通知对方，以减轻可能给对方造成的损失，并应当在合理期限内提供证明。",
    },
    # ---------------- 类案参考库（裁判要旨） ----------------
    {
        "id": "b-prec-1", "source": "builtin", "category": "类案参考",
        "title": "类案要旨 · 间接证据链认定故意杀人（刑事）",
        "keywords": ["故意杀人", "间接证据", "监控", "DNA", "无目击", "命案"],
        "text": "无直接目击证据的命案，在案物证与被害人伤情吻合、DNA/指纹等生物Trace指向明确、被告人无法对关键窗口作出合理排除、且有动机证据印证的，可以认定「事实清楚、证据确实充分」。但监控等客观证据存在缺失时段的，该时段内发生的事实应从严把握，不得以推断替代证明。",
    },
    {
        "id": "b-prec-2", "source": "builtin", "category": "类案参考",
        "title": "类案要旨 · 监控剪辑/数据缺失对指控的影响（刑事）",
        "keywords": ["监控", "剪辑", "缺失", "删除", "电子数据", "完整性"],
        "text": "关键监控存在人为剪辑或数据缺失的，法院通常要求侦查机关说明原因并提交原始载体；无法提交且不能作出合理解释的，该证据的证明力显著降低，依赖该证据形成的关键事实（如出入现场时间）不予认定，进而可能动摇整个指控体系。",
    },
    {
        "id": "b-prec-3", "source": "builtin", "category": "类案参考",
        "title": "类案要旨 · 合同纠纷中的不可抗力抗辩（民事）",
        "keywords": ["违约", "不可抗力", "合同", "迟延履行", "免责"],
        "text": "主张不可抗力免责须同时满足：事件不能预见、不能避免且不能克服；义务人已及时通知对方以减损；并在合理期限内提供证明。迟延履行期间发生的「不可抗力」不免责。法院还会审查违约是否系多因一果，按原因力比例分配责任。",
    },
]


# --------------------- 结构化法条查询（B 阶段引用核验） ---------------------

_LAW_ALIASES = {
    "刑事诉讼法": "中华人民共和国刑事诉讼法",
    "刑诉法": "中华人民共和国刑事诉讼法",
    "中华人民共和国刑事诉讼法": "中华人民共和国刑事诉讼法",
    "刑法": "中华人民共和国刑法",
    "中华人民共和国刑法": "中华人民共和国刑法",
    "民法典": "中华人民共和国民法典",
    "中华人民共和国民法典": "中华人民共和国民法典",
}


def canon_law(title: str) -> str | None:
    """把《…法》各种写法归一到标准法名；不认识返回 None。"""
    t = (title or "").strip().strip("《》").replace(" ", "")
    if not t:
        return None
    if t in _LAW_ALIASES:
        return _LAW_ALIASES[t]
    for alias, canon in _LAW_ALIASES.items():
        if alias and alias in t:
            return canon
    return None


def parse_article_no(article: str) -> int:
    """从「第55条 / 五十五 / 55」提取条号；解析失败返回 -1。"""
    import re
    a = (article or "").strip()
    if not a:
        return -1
    m = re.search(r"(\d+)", a)
    if m:
        return int(m.group(1))
    m = re.search(r"[零一二三四五六七八九十百千壹贰叁肆伍陆柒捌玖拾佰仟两]+", a)
    if m:
        s = m.group(0).replace("两", "二")
        return cn_to_int(s)
    return -1


def find_statute(title: str, article: str) -> dict | None:
    """按（法名, 条号）精确查内置法条库；命中返回条目，未命中返回 None。"""
    canon = canon_law(title)
    if not canon:
        return None
    no = parse_article_no(article)
    if no < 0:
        return None
    for e in BUILTIN:
        if e.get("law") == canon and e.get("article_no") == no:
            return e
    return None


def law_known(title: str) -> bool:
    """法名是否为库内已知法律（条文收录与否不保证）。"""
    return canon_law(title) is not None


def article_numbers_of_law(canon: str) -> list[int]:
    return sorted(
        e["article_no"] for e in BUILTIN
        if e.get("law") == canon and isinstance(e.get("article_no"), int)
    )


def find_statute_by_charge(charge: str) -> dict | None:
    """按罪名（如「故意杀人罪」）找罪名条文条目。"""
    c = (charge or "").strip()
    if not c:
        return None
    for e in BUILTIN:
        if e.get("charge") and (e["charge"] == c or c in e["charge"] or e["charge"] in c):
            return e
    return None


def _load_custom() -> list[dict]:
    try:
        with open(_kb_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [e for e in data if isinstance(e, dict) and e.get("title")]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return []


def _save_custom(entries: list[dict]) -> None:
    atomic_write_json(_kb_path(), entries)


def list_knowledge() -> list[dict]:
    """内置 + 自定义全部条目（自定义在前）。"""
    with _KB_LOCK:
        custom = _load_custom()
    return custom + BUILTIN


def search_knowledge(keyword: str, limit: int = 6) -> list[dict]:
    """关键词检索：支持多关键词（空格/逗号分隔），按相关度排序。
    评分权重：关键词精确命中 > 标题命中 > 正文命中；多关键词命中累加。"""
    kw = (keyword or "").strip().lower()
    if not kw:
        return []
    # 拆分多关键词：空格、逗号、顿号分隔
    import re as _re
    terms = [t for t in _re.split(r"[\s,，、;；]+", kw) if t and len(t) >= 1]
    if not terms:
        terms = [kw]
    scored = []
    for e in list_knowledge():
        hay_kw = " ".join(e.get("keywords", [])).lower()
        hay_title = e.get("title", "").lower()
        hay_text = e.get("text", "").lower()
        score = 0
        hit_terms = 0
        for t in terms:
            if t in hay_kw:
                score += 3  # 关键词字段命中（最高权重）
                hit_terms += 1
            if t in hay_title:
                score += 2  # 标题命中
                hit_terms += 1
            if t in hay_text:
                score += 1  # 正文命中
                hit_terms += 1
        if score:
            # 多关键词全部命中额外加分
            if hit_terms >= len(terms) * 2:
                score += 2
            scored.append((score, e))
    scored.sort(key=lambda x: -x[0])
    return [e for _, e in scored[:limit]]


def add_knowledge(title: str, text: str, keywords: list[str] | None = None) -> dict:
    entry = {
        "id": "k-" + uuid.uuid4().hex[:10],
        "source": "custom",
        "category": "自定义",
        "title": title.strip(),
        "text": text.strip(),
        "keywords": [k.strip() for k in (keywords or []) if k.strip()],
    }
    with _KB_LOCK:
        entries = _load_custom()
        entries.insert(0, entry)
        _save_custom(entries)
    return entry


def delete_knowledge(entry_id: str) -> bool:
    with _KB_LOCK:
        entries = _load_custom()
        remain = [e for e in entries if e.get("id") != entry_id]
        if len(remain) == len(entries):
            return False  # 不存在，或试图删除内置条目
        _save_custom(remain)
    return True
