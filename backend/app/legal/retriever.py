# -*- coding: utf-8 -*-
"""知识库语义检索：Chroma 向量库 + 本地中文嵌入模型（默认 bge-small-zh，可关）。

- EMBEDDING_MODEL=off 时完全关闭，退回纯关键词检索（旧行为），零额外依赖；
- 索引按列表内容哈希自动重建（内置法条 + 自定义知识库 + 类案条目），规模小，无需增量维护；
- 检索 = 关键词精确命中优先 + 向量语义补足，两者合并且去重。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, List

from app.config import settings
from app.legal.knowledge import list_knowledge

log = logging.getLogger("verdictai.retriever")

_MODEL: Any = None  # None=未加载, False=不可用, SentenceTransformer=可用
_COL: Any = None    # 惰性 Chroma collection
_RERANK: Any = None  # M3.1 可选精排（bge-reranker CrossEncoder），缺失自动降级


def _embedder():
    """惰性加载 sentence-transformers 嵌入模型；关闭或失败时返回 None。"""
    global _MODEL
    if _MODEL is not None:
        return _MODEL or None
    name = (settings.embedding_model or "").strip().lower()
    if name in ("off", "none", ""):
        _MODEL = False
        return None
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(name, device=settings.embedding_device or "cpu")
        model.encode(["预热"])  # 预热加载，避免首次检索卡顿
        _MODEL = model
    except Exception as ex:  # noqa: BLE001
        log.warning("嵌入模型不可用（EMBEDDING_MODEL=%s），语义检索关闭: %s", name, ex)
        _MODEL = False
    return _MODEL or None


def _collection():
    """惰性获取 Chroma collection（PersistentClient，数据落 data/vectorstore）。"""
    global _COL
    if _COL is not None:
        return _COL
    try:
        import chromadb

        client = chromadb.PersistentClient(
            path=os.path.join(settings.data_dir, "vectorstore")
        )
        col = client.get_or_create_collection(
            name="verdictai_knowledge", metadata={"hnsw:space": "cosine"}
        )
        _COL = col
    except Exception as ex:  # noqa: BLE001
        log.warning("Chroma 不可用，语义检索关闭: %s", ex)
        _COL = False
    return _COL or None


def _index_key() -> str:
    """条目内容指纹：变化时触发索引重建。"""
    entries = list_knowledge()
    payload = json.dumps(
        [(e.get("id"), e.get("title"), e.get("text"), e.get("keywords") or [])
         for e in entries],
        ensure_ascii=False,
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:16]


def _state_path() -> str:
    return os.path.join(settings.data_dir, "vectorstore", "index_key.txt")


def rebuild_if_needed() -> None:
    """本地模型可用时，把全部知识条目写入向量索引（内容变了才重建）。"""
    model = _embedder()
    col = _collection()
    if model is None or col is None:
        return
    try:
        os.makedirs(os.path.dirname(_state_path()), exist_ok=True)
        key = _index_key()
        prev = ""
        try:
            with open(_state_path(), encoding="utf-8") as f:
                prev = f.read().strip()
        except OSError:
            prev = ""
        if prev == key:
            return
        entries = list_knowledge()
        if not entries:
            return
        col.delete(where={"source": {"$in": ["builtin", "custom"]}})
        col.add(
            ids=[f"{e.get('source')}-{e.get('id')}" for e in entries],
            documents=[
                (e.get("title", "") + "\n" + (e.get("text", "") or ""))[:2000]
                for e in entries
            ],
            metadatas=[
                {
                    "source": e.get("source", "custom"),
                    "category": e.get("category", ""),
                    "title": e.get("title", ""),
                }
                for e in entries
            ],
            embeddings=model.encode(
                [((e.get("title", "") + " " + (e.get("text", "") or "")))[:2000]
                 for e in entries],
                normalize_embeddings=True,
            ).tolist(),
        )
        with open(_state_path(), "w", encoding="utf-8") as f:
            f.write(key)
        log.info("知识库向量索引已重建（%d 条）", len(entries))
    except Exception as ex:  # noqa: BLE001
        log.warning("知识库索引重建失败: %s", ex)


def semantic_scores(query: str, limit: int = 6) -> Dict[str, float]:
    """返回 {entry_id: score}，按语义相关度排序（余弦相似度）。"""
    model = _embedder()
    col = _collection()
    if model is None or col is None:
        return {}
    rebuild_if_needed()
    try:
        q = model.encode([query], normalize_embeddings=True)[0].tolist()
        res = col.query(query_embeddings=[q], n_results=max(limit * 2, 10))
    except Exception as ex:  # noqa: BLE001
        log.warning("语义检索失败: %s", ex)
        return {}
    pairs: Dict[str, float] = {}
    ids = (res.get("ids") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    for i, rid in enumerate(ids):
        entry_id = rid.split("-", 1)[-1] if "-" in rid else rid
        # cosine distance → similarity
        pairs[entry_id] = max(0.0, 1.0 - float(dists[i])) if i < len(dists) else 0.5
    return pairs


def case_similarities(case_id: str, limit: int = 3) -> List[dict]:
    """相似案例推荐（M1.5）：embedding 近邻优先，语义不可用时退关键词/案由重叠。
    返回 [{id,title,score,cause}]，score∈[0,1]。确定性不做硬失败，只在有料时返回。"""
    from app.data.store import list_cases, load_case

    target = load_case(case_id)
    if not target:
        return []
    others = [c for c in list_cases() if (c.get("id") or "") != case_id]
    if not others:
        return []

    target_text = (str(target.get("title") or "") + " " + str(target.get("summary") or ""))
    target_cause = (target.get("brief") or {}).get("cause") or ""
    model = _embedder()
    if model is not None:
        try:
            docs = [
                str(c.get("title") or "") + " " + str(c.get("summary") or "")
                for c in others
            ]
            import numpy as np

            vs = model.encode(
                [target_text[:2000], *(d[:2000] for d in docs)],
                normalize_embeddings=True,
            )
            sims = [float(np.dot(vs[0], v)) for v in vs[1:]]
            ranked = sorted(zip(sims, others), key=lambda x: -x[0])
            return [
                {
                    "id": c.get("id"),
                    "title": c.get("title"),
                    "score": round(max(0.0, min(1.0, s)), 3),
                    "cause": (c.get("brief") or {}).get("cause", ""),
                }
                for s, c in ranked[:limit]
                if s > 0.1
            ]
        except Exception as ex:  # noqa: BLE001
            log.warning("案例向量相似失败，退关键词: %s", ex)

    # 关键词兜底：标题公共字符 + 案由一致加权
    import re

    target_tokens = set(re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", target_text or ""))
    scored = []
    for c in others:
        c_cause = (c.get("brief") or {}).get("cause") or ""
        c_tokens = set(
            re.findall(
                r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", str(c.get("title") or "")
            )
        )
        inter = len(target_tokens & c_tokens)
        cause_bonus = 1.0 if (target_cause and c_cause == target_cause) else 0.0
        s = inter + cause_bonus
        if s > 0:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return [
        {
            "id": c.get("id"),
            "title": c.get("title"),
            "score": round(min(1.0, s / 3.0), 3),
            "cause": (c.get("brief") or {}).get("cause", ""),
        }
        for s, c in scored[:limit]
    ]


def _reranker():
    """M3.1 可选精排：bge-reranker 交叉编码器。未安装/未缓存/网络不可达时返回
    None（调用方直接跳过精排，绝不阻塞检索）."""
    global _RERANK
    if _RERANK is not None:
        return _RERANK or None
    if str(settings.embedding_model or "").lower() in ("off", "none", ""):
        _RERANK = False
        return None
    try:
        from sentence_transformers import CrossEncoder

        # 默认 bge-reranker-base（本地离线模型，与嵌入同源同族）
        _RERANK = CrossEncoder("BAAI/bge-reranker-base", device=settings.embedding_device or "cpu")
    except Exception as ex:  # noqa: BLE001
        log.info("Reranker 不可用（跳过精排，仅用混合检索）: %s", ex)
        _RERANK = False
    return _RERANK or None


def rerank(query: str, entries: List[dict], limit: int | None = None) -> List[dict]:
    """M3.1 精排：对 candidates 按 query 交叉编码打分重排；reranker 不可用
    时原序返回（降级），绝不失败、绝不阻塞。"""
    if not entries:
        return entries
    rk = _reranker()
    if rk is None:
        return entries
    try:
        docs = [
            f"{e.get('title', '')} {((e.get('text') or '')[:500])}" for e in entries
        ]
        scores = rk.predict([(query, d) for d in docs])
        ranked = sorted(zip(scores, entries), key=lambda x: -float(x[0]))
        n = limit if limit is not None else len(entries)
        return [{**e, "rerank": round(float(s), 3)} for s, e in ranked[:n]]
    except Exception as ex:  # noqa: BLE001
        log.info("精排失败，退回混合检索顺序: %s", ex)
        return entries


def hybrid_search(query: str, limit: int = 6) -> List[dict]:
    """混合检索：关键词命中（精确）优先，语义结果补齐，去重后返回条目列表
    （带 score / semantic 标记）。语义不可用时降级纯关键词。"""
    from app.legal.knowledge import search_knowledge

    kw = search_knowledge(query, limit=max(limit, 6))
    sem = semantic_scores(query, limit=max(limit, 6))
    merged: List[dict] = []
    seen: set = set()
    for e in kw:
        merged.append({**e, "score": 2.0 + (sem.get(e["id"], 0.0) or 0.0) * 0.5,
                       "semantic": e["id"] in sem})
        seen.add(e["id"])
    # 语义补足未在关键词中的高相关条目
    sem_ordered = sorted(sem.items(), key=lambda kv: -kv[1])
    for entry_id, score in sem_ordered:
        if len(merged) >= limit:
            break
        if entry_id in seen:
            continue
        for e in list_knowledge():
            if e.get("id") == entry_id:
                merged.append({**e, "score": score, "semantic": True})
                seen.add(entry_id)
                break
    # M3.1：精排可用时对混合候选重排（缺失自动降级为当前顺序）
    if any(e.get("semantic") for e in merged):
        merged = rerank(query, merged, limit=limit)
    return merged[:limit]