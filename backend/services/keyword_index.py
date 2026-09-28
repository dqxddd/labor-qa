"""关键词检索：字符 bigram + TF-IDF。

这就是中期自己写的那套简易检索，9.22 加向量检索时**原样搬过来**，
一行逻辑都没改 —— 它现在的身份是"兜底"：向量那条路要联网调接口，
没网 / key 失效 / 额度用完都会挂，这时候得有个不依赖网络的东西顶着。

索引落在 data/vectorstore/simple_index.json，
chunks.vector_id 里存 "vec-{doc_id}-{片段序号}"，和 json 里的 key 一一对应。

局限照旧、也照实写进报告：它比的是"用词像不像"，不是"意思像不像"。
换种说法提问（「被开除能赔钱吗」vs「违法解除劳动合同的赔偿」）可能命不中 ——
这正是加向量检索要解决的问题。
"""

import json
import math
import os

from collections import Counter

from backend.core.config import VECTOR_DIR

INDEX_PATH = os.path.join(VECTOR_DIR, "simple_index.json")

# 9.18 踩坑：只命中一个词就放行的话，"怎么申请专利"会撞上"申请仲裁"里的"申请"，
# 结果该拒答的没拒答。改成至少命中 2 个词才算相关，测试的 8 个问题里能分开了。
MIN_MATCH_TERMS = 2

# 提问里的虚词先去掉，不然"怎么""什么"这些会把分数搅乱，
# 去掉之后"怎么申请专利"只剩"申请"能对上，命中数不够就不放行了
STOP_CHARS = set("怎么什么如何请问吗呢吧啊我你他的是否")


def _grams(text):
    """相邻两字的组合。中文不用分词也能凑合，英文数字也会被切进来，先这样"""
    t = "".join(text.split())
    if not t:
        return []
    if len(t) == 1:
        return [t]
    return [t[i:i + 2] for i in range(len(t) - 1)]


def _term_freq(text):
    return Counter(_grams(text))


def _clean_query(text):
    """去掉提问里的虚词，去完太短就还原，免得"怎么办"这种被削成一个字"""
    cleaned = "".join(ch for ch in text if ch not in STOP_CHARS)
    cleaned = "".join(cleaned.split())
    return cleaned if len(cleaned) >= 2 else text


def build_index(chunks):
    """全量重建，返回索引里的片段数。

    chunks 由调用方从数据库读好传进来（[(片段id, 内容)]），
    这样建两条索引只需要查一次库。
    """
    chunk_tf = {}
    for chunk_id, content in chunks:
        chunk_tf[str(chunk_id)] = dict(_term_freq(content))

    # idf：一个词在越少的片段里出现，越说明它重要
    df = Counter()
    for tf in chunk_tf.values():
        for g in tf:
            df[g] += 1
    total = max(len(chunk_tf), 1)
    idf = {g: math.log((total + 1) / (n + 1)) + 1 for g, n in df.items()}

    payload = {"version": 1, "chunk_count": len(chunk_tf), "idf": idf, "chunks": chunk_tf}
    os.makedirs(VECTOR_DIR, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return len(chunk_tf)


def load_index():
    if not os.path.exists(INDEX_PATH):
        return None
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _match_score(query_tf, chunk_tf, idf, need):
    """查询里的词在这个片段里覆盖了多少（按 idf 加权），返回 0~1。

    语料里根本没出现过的词权重给 1（相当于"没有证据"，不能当加分也不能当扣分），
    idf 高的稀有词权重大，这样"工伤""辞退"这类词才压得过"公司""工资"。
    """
    total = 0.0
    hit = 0.0
    matched = 0
    for g in query_tf:
        weight = idf.get(g, 1.0)
        total += weight
        if g in chunk_tf:
            hit += weight
            matched += 1
    if total <= 0 or matched < need:
        return 0.0
    return hit / total


def rank(query, top_k=None):
    """返回 [(片段id, 分数)]，按分数从高到低。

    只负责打分和排序，**不套阈值** —— 阈值由调用方按当前引擎挑
    （关键词和向量的分数口径不一样，见 indexer.score_threshold）。
    片段内容也由调用方去数据库取，这里不碰库。
    """
    index = load_index()
    if index is None:
        return []

    query_tf = _term_freq(_clean_query(query))
    if not query_tf:
        return []

    idf = index.get("idf", {})
    need = min(MIN_MATCH_TERMS, len(query_tf))
    scored = []
    for chunk_id, chunk_tf in index.get("chunks", {}).items():
        s = _match_score(query_tf, chunk_tf, idf, need)
        if s > 0:
            scored.append((int(chunk_id), s))

    scored.sort(key=lambda x: x[1], reverse=True)
    if top_k:
        scored = scored[:top_k]
    return scored


def info():
    """给前端调试页看的信息"""
    index = load_index()
    if index is None:
        return {"ready": False, "chunk_count": 0, "term_count": 0}
    return {
        "ready": True,
        "chunk_count": index.get("chunk_count", 0),
        "term_count": len(index.get("idf", {})),
    }
