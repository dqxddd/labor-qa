"""向量库：把片段的向量存进 Chroma，提问时按"意思像不像"查。

Chroma 的 id 就用 chunks 表的主键（存成字符串），
metadata 里带上 doc_id / 片段序号 / 内容指纹 —— 删资料、比对缓存都要用。

三件容易踩的事，都在这个文件里处理了：

1. 距离不是相似度。Chroma 返回的是距离（越小越像），前端要的是相似度
   （越大越像），得换算。换算公式跟建库时用的 space 有关，所以这里
   先把向量归一化成单位长度，再按 collection 里实际记着的 space 换算 ——
   万一 space 没设成 cosine、走的是默认 l2，也能算出一样的排序，不会悄悄跑偏。
2. 重复调接口。每次上传都整库重算向量太浪费（免费的额度也是额度），
   所以按内容 md5 缓存，只有新内容真去调接口。缓存跟着片段走：
   这次没出现的片段，它的缓存也一并清掉，不让文件一直长胖。
3. 空库不能查。Chroma 的 n_results 必须大于 0，库里一条都没有时直接查会抛错。
"""

import hashlib
import json
import math
import os

from backend.core.config import VECTOR_DIR
from backend.services import embedding

CHROMA_DIR = os.path.join(VECTOR_DIR, "chroma")
CACHE_PATH = os.path.join(VECTOR_DIR, "embed_cache.json")
COLLECTION = "labor_knowledge"

# 一次往库里塞多少条。Chroma 对单次写入有上限，分批最稳
UPSERT_BATCH = 128

DW = 6   # 缓存里的向量保留几位小数。1024 维每维都写全精度，文件大得没必要

_client = None
_collection = None


class VectorError(Exception):
    pass


def _get_client():
    global _client
    if _client is None:
        try:
            import chromadb
        except ImportError:
            raise VectorError("没装 chromadb，先在 venv 里 pip install chromadb")
        os.makedirs(CHROMA_DIR, exist_ok=True)
        _client = chromadb.PersistentClient(path=CHROMA_DIR)
    return _client


def _get_collection():
    global _collection
    if _collection is None:
        client = _get_client()
        # 余弦距离：只看方向、不看长短，正是"意思像不像"要的东西。
        # 1.5 用 configuration 传，老版本只认 metadata，两种都试一下。
        try:
            _collection = client.get_or_create_collection(
                name=COLLECTION, configuration={"hnsw": {"space": "cosine"}})
        except (TypeError, ValueError):
            _collection = client.get_or_create_collection(
                name=COLLECTION, metadata={"hnsw:space": "cosine"})
    return _collection


def space():
    """这个 collection 实际用的是哪种距离。

    新版本记在 configuration 里、老版本记在 metadata 里，
    两处都看一眼；都读不到就按 cosine 算（建库时就是这么要的）。
    """
    col = _get_collection()
    conf = getattr(col, "configuration", None)
    if isinstance(conf, dict):
        hnsw = conf.get("hnsw")
        if isinstance(hnsw, dict) and hnsw.get("space"):
            return hnsw["space"]
    meta = col.metadata or {}
    return meta.get("hnsw:space") or meta.get("space") or "cosine"


def _unit(vec):
    """归一化成单位长度。

    归一化之后"l2 距离"和"余弦距离"是单调对应的，所以就算建库时
    space 没生效、走的是默认的 l2，排序结果也跟余弦一致。
    """
    n = math.sqrt(sum(x * x for x in vec))
    if n == 0:
        return vec
    return [x / n for x in vec]


def _similarity(distance):
    """距离换算成 0~1 的相似度，越大越像"""
    if space() == "cosine":
        sim = 1.0 - distance
    else:
        # 单位向量：l2距离² = 2 - 2*cos，反推出来就是余弦
        sim = 1.0 - distance * distance / 2.0
    return max(0.0, min(1.0, sim))


def _key(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _load_cache():
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        # 缓存坏了不算大事，当没有、重算一遍就行，不能因为这个把建索引搞崩
        return {}


def _save_cache(cache):
    os.makedirs(VECTOR_DIR, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f)


def reset():
    """把整个 collection 删掉。全量重建之前先清空，不留旧片段"""
    global _collection
    client = _get_client()
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass              # 本来就不存在，下次取 collection 时会自己建
    _collection = None


def rebuild(chunks):
    """全量重建向量库。

    chunks 是 [(片段id, 内容, 资料id, 第几段)]，由调用方从数据库读好传进来
    （这样建两条索引只用查一次库）。
    返回 (入库条数, 真正调了接口的条数, 向量维度)。
    """
    if not chunks:
        reset()
        _save_cache({})
        return 0, 0, 0

    ids = [str(c[0]) for c in chunks]
    texts = [c[1] for c in chunks]
    keys = [_key(t) for t in texts]
    metas = [{"doc_id": int(c[2]), "chunk_index": int(c[3]), "hash": k}
             for c, k in zip(chunks, keys)]

    cache = _load_cache()

    # 缓存里没有的才真要算向量 —— 这一步省下来的就是接口调用次数
    todo = [i for i, k in enumerate(keys) if k not in cache]
    if todo:
        fresh = embedding.embed_texts([texts[i] for i in todo])
        for i, vec in zip(todo, fresh):
            cache[keys[i]] = [round(x, DW) for x in vec]

    vectors = [_unit(cache[k]) for k in keys]

    reset()
    col = _get_collection()
    for i in range(0, len(ids), UPSERT_BATCH):
        col.upsert(
            ids=ids[i:i + UPSERT_BATCH],
            embeddings=vectors[i:i + UPSERT_BATCH],
            documents=texts[i:i + UPSERT_BATCH],
            metadatas=metas[i:i + UPSERT_BATCH],
        )

    # 只留这次用到的缓存，删掉的资料别在文件里越积越多
    keep = set(keys)
    _save_cache({k: v for k, v in cache.items() if k in keep})

    return len(ids), len(todo), len(vectors[0])


def rank(query, top_k):
    """返回 [(片段id, 相似度)]，按相似度从高到低。只排序，不套阈值"""
    col = _get_collection()
    total = col.count()
    if total == 0:
        return []

    vec = _unit(embedding.embed_query(query))
    res = col.query(
        query_embeddings=[vec],
        n_results=min(top_k or 5, total),
        include=["distances"],
    )

    ids = (res.get("ids") or [[]])[0]
    distances = (res.get("distances") or [[]])[0]
    hits = [(int(cid), _similarity(float(d))) for cid, d in zip(ids, distances)]
    hits.sort(key=lambda x: x[1], reverse=True)
    return hits


def count():
    """库里现在有多少条向量。读不到就当 0 —— 启动自检会按这个数决定要不要重建"""
    try:
        return _get_collection().count()
    except Exception:
        return 0


def dims():
    """向量维度。缓存里随便取一条量一下就行，不用真的调接口"""
    cache = _load_cache()
    for vec in cache.values():
        return len(vec)
    return 0


def info():
    """给 /health 和前端展示用"""
    return {
        "dir": CHROMA_DIR,
        "collection": COLLECTION,
        "space": space() if count() else "cosine",
        "chunk_count": count(),
        "dims": dims(),
        "cache_size": len(_load_cache()),
    }
