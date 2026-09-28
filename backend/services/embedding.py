"""向量模型（embedding）调用：把一段文字变成一个能算相似度的向量。

走的是 OpenAI 兼容的 /embeddings 接口，所以换供应商只改 .env 里那三项
（EMBED_PROVIDER / EMBED_MODEL / EMBED_BASE_URL），代码不用动。

9.22 记一下取舍：任务书原本写的是本地跑 bge-small-zh，那套要装
torch + sentence-transformers，光 torch 就 2G 多，装完还得下模型权重。
权衡之后改成调硅基流动的 BAAI/bge-m3（免费、1024 维、中文效果更好）：
不装 torch、不占磁盘，代价是建索引时要联网 ——
所以 indexer 那边留了关键词检索做兜底，接口挂了也能照常用。
"""

import httpx

from backend.core.config import (
    EMBED_API_KEY,
    EMBED_BASE_URL,
    EMBED_MODEL,
    EMBED_PROVIDER,
)

# 一次请求最多塞几条。接口本身扛得住更多，但分批发好排查：
# 出问题能定位到是哪一批，也不会因为一条超长把整批拖死。
BATCH_SIZE = 32

TIMEOUT = 60


class EmbedError(Exception):
    pass


def enabled():
    """向量模型这条路现在能不能走。返回 (能不能走, 不能走的原因)。

    原因要写清楚而且要能直接给用户看 —— 建索引失败时前端会把它显示出来，
    比只写一句"失败了"好排查得多。
    """
    if EMBED_PROVIDER != "api":
        return False, ("EMBED_PROVIDER=%s，本地向量模型这条路还没接"
                       "（任务书原方案要装 torch，2G 多；现在走 api）" % EMBED_PROVIDER)
    if not EMBED_API_KEY:
        return False, "没配 EMBED_API_KEY"
    if not EMBED_BASE_URL:
        return False, "没配 EMBED_BASE_URL"
    if not EMBED_MODEL:
        return False, "没配 EMBED_MODEL"
    return True, ""


def _url():
    return EMBED_BASE_URL.rstrip("/") + "/embeddings"


def _headers():
    return {
        "Authorization": "Bearer %s" % EMBED_API_KEY,
        "Content-Type": "application/json",
    }


def _post(texts):
    """发一批出去，拿回一批向量"""
    try:
        resp = httpx.post(
            _url(),
            headers=_headers(),
            json={"model": EMBED_MODEL, "input": texts, "encoding_format": "float"},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise EmbedError("请求向量模型失败：%s" % e)

    if resp.status_code != 200:
        raise EmbedError("向量模型返回 %s：%s" % (resp.status_code, resp.text[:200]))

    try:
        data = resp.json()["data"]
    except (KeyError, ValueError):
        raise EmbedError("向量模型返回的结构看不懂：%s" % resp.text[:200])

    # 接口不保证 data 的顺序跟 input 一致，靠 index 字段摆回去 ——
    # 这里错一位，后面所有片段和向量就全对错位了，检索结果会莫名其妙。
    data = sorted(data, key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in data]


def embed_texts(texts):
    """一批文本 -> 一批向量。按 BATCH_SIZE 分批发，空列表直接返回空、不发请求"""
    texts = [t or "" for t in texts]
    if not texts:
        return []

    vectors = []
    for i in range(0, len(texts), BATCH_SIZE):
        vectors += _post(texts[i:i + BATCH_SIZE])

    if len(vectors) != len(texts):
        raise EmbedError("向量条数对不上：发了 %d 条，回来 %d 条"
                         % (len(texts), len(vectors)))
    return vectors


def embed_query(text):
    """只算一句话的向量，检索时用它"""
    vectors = embed_texts([text])
    if not vectors:
        raise EmbedError("向量模型没返回结果")
    return vectors[0]


def info():
    """给 /health 和前端展示用的配置摘要"""
    return {
        "provider": EMBED_PROVIDER,
        "model": EMBED_MODEL,
        "base_url": EMBED_BASE_URL,
        "enabled": enabled()[0],
        "reason": enabled()[1],
    }
