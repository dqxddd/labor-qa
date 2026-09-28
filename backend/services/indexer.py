"""检索总入口：优先走向量检索，出问题自动退回关键词检索。

两条路的分工：

  vector  —— Chroma + bge-m3 向量（vector_index），比"意思像不像"。
             换种说法提问也能命中了，这是 9.22 加它的原因。
  keyword —— 字符 bigram + TF-IDF（keyword_index），比"用词像不像"。
             纯本地、不依赖网络，现在的身份是兜底。

为什么必须留 keyword：向量那条路要联网调接口，没网 / key 失效 / 额度用完
都会挂。问答页不能因为检索挂了就整个瘫掉，所以失败时自动降级，
并且把降级原因记下来由 /health 报出去 —— 前端会显示出来，不假装一切正常。

⚠️ 两条路的分数口径不一样，阈值不能共用一个数：
  vector  —— 余弦相似度，相关的一般 0.5 以上
  keyword —— 查询词覆盖率，相关的通常也就 0.2~0.4
所以 search() 连引擎名一起返回，调用方照它挑阈值（用 score_threshold()）。
当初这里差点写成共用一个 0.35 —— 那样向量这条路会把所有问题都判成"资料里有"，
拒答直接失效。
"""

from backend.core.config import SCORE_THRESHOLD, VECTOR_SCORE_THRESHOLD
from backend.core.db import SessionLocal
from backend.models.document import Chunk
from backend.services import embedding, keyword_index, vector_index

MODE_VECTOR = "vector"
MODE_KEYWORD = "keyword"

MODE_NAMES = {
    MODE_VECTOR: "向量检索",
    MODE_KEYWORD: "关键词检索",
}

# 最近一次降级的原因，空串表示没在降级。给 /health 和前端看
_last_error = ""


def engine_label(engine):
    """引擎名 -> 给人看的名字"""
    return MODE_NAMES.get(engine, engine)


def vector_available():
    """向量这条路现在能不能走：配置齐了 + 库里真有向量"""
    ok, _ = embedding.enabled()
    return ok and vector_index.count() > 0


def current_engine():
    """不跑检索、只看状态，判断"现在实际上在用哪条路"。

    这是实时判断（Chroma 的条数是本地读，很快），不缓存 ——
    缓存会带来一个恶心的情况：启动时接口不通降级了，后来网络恢复了，
    /health 还一直显示"关键词检索"，看着像坏了。

    注意顺序：**先看上一次有没有降级**。因为向量那条路每次检索都会重试
    （网络恢复了就该自己恢复），所以"配置上允许"不等于"现在真在用"。
    上一次调用失败过就如实说在用关键词，等哪次真调通了再改回来。
    """
    if _last_error:
        return MODE_KEYWORD
    return MODE_VECTOR if vector_available() else MODE_KEYWORD


def _status():
    """现在为什么走这条路。空串表示没降级、向量检索正常。

    不能只看 _last_error —— 那个只在"重建索引 / 检索失败"时才写。
    举个真实踩到的例子：启动时 .env 里就没配 key，索引本来就好好的、
    根本不需要重建，于是 _last_error 一直是空的，/health 却报
    degraded=false，看上去一切正常，其实一直在用关键词检索 ——
    这就是"假装一切正常"，违背这个功能的设计原则。所以这里实时算。
    """
    ok, why = embedding.enabled()
    if not ok:
        return "向量检索没启用：%s" % why
    if vector_index.count() == 0:
        return "向量库是空的，先用关键词检索顶着"
    return _last_error


def score_threshold(engine=None):
    """按引擎挑阈值。

    两条路的分数口径不一样，共用一个数必然有一边是错的：
    向量分 0.35 会放进一堆不相关的片段（拒答失效），
    关键词分 0.5 会把该命中的都筛掉（什么都答不出来）。
    """
    engine = engine or current_engine()
    return VECTOR_SCORE_THRESHOLD if engine == MODE_VECTOR else SCORE_THRESHOLD


def _read_chunks():
    """把库里所有片段读成 [(片段id, 内容, 资料id, 第几段)]"""
    db = SessionLocal()
    try:
        return [(c.id, c.content, c.doc_id, c.chunk_index) for c in db.query(Chunk).all()]
    finally:
        db.close()


def _load_hits(scored):
    """把 [(片段id, 分数)] 还原成 [(片段对象, 分数)]，顺序照旧"""
    if not scored:
        return []
    db = SessionLocal()
    try:
        ids = [cid for cid, _ in scored]
        by_id = {c.id: c for c in db.query(Chunk).filter(Chunk.id.in_(ids)).all()}
    finally:
        db.close()
    return [(by_id[cid], s) for cid, s in scored if cid in by_id]


def build_index():
    """全量重建，返回片段数。上传 / 删除资料后调它。

    两条索引都建。关键词那条纯本地、几乎不花时间，但必须随时是热的 ——
    兜底的东西不能等出事了才去建。
    """
    global _last_error

    chunks = _read_chunks()
    count = keyword_index.build_index([(c[0], c[1]) for c in chunks])

    ok, why = embedding.enabled()
    if not ok:
        _last_error = "向量检索没启用：%s" % why
        print("[检索] %s，先用关键词检索" % _last_error)
        return count

    try:
        n, fresh, _dims = vector_index.rebuild(chunks)
    except Exception as e:
        _last_error = "建向量索引失败，已退回关键词检索：%s" % e
        print("[检索] %s" % _last_error)
        return count

    _last_error = ""
    print("[检索] 向量索引重建完成：%d 个片段（其中新算向量 %d 条，其余走缓存）"
          % (n, fresh))
    return n


def ensure_index():
    """启动时用：库里已经有片段、但索引没建好或跟库里的条数对不上，就补建一次。

    "对不上"是常见情况：换过向量模型、手动删过 data/vectorstore、
    数据库被清过，都会对不上。自己补上，别让用户去点"重建索引"。
    """
    db = SessionLocal()
    try:
        count = db.query(Chunk).count()
    finally:
        db.close()

    if count == 0:
        return False

    if keyword_index.info()["chunk_count"] == count:
        ok, _ = embedding.enabled()
        if not ok or vector_index.count() == count:
            return False

    build_index()
    return True


def search(query, top_k=None):
    """检索。返回 (命中列表, 引擎名)。

    命中列表是 [(片段对象, 分数)]，按分数从高到低，**没有套阈值** ——
    阈值由调用方用 score_threshold(引擎名) 挑，因为口径随引擎变。

    先试向量。这条路不可用、或这一次调用失败，就退回关键词检索。
    """
    global _last_error

    query = (query or "").strip()
    if not query:
        return [], current_engine()

    if vector_available():
        try:
            scored = vector_index.rank(query, top_k)
            _last_error = ""
            return _load_hits(scored), MODE_VECTOR
        except Exception as e:
            # 这里不吞异常直接退回 —— 用户宁可拿到"用词匹配"的结果，
            # 也好过看到一个"检索失败"的空页面。原因照样记下来报出去。
            _last_error = "这次向量检索没成功，已退回关键词检索：%s" % e
            print("[检索] %s" % _last_error)

    return _load_hits(keyword_index.rank(query, top_k)), MODE_KEYWORD


def index_info():
    """给 /health 和前端调试页看的信息"""
    kw = keyword_index.info()
    engine = current_engine()
    emb = embedding.info()
    vcount = vector_index.count()      # 读一次就够，下面好几处要用
    reason = _status()
    return {
        # 下面三个是老字段，前端还在用，别改名字
        "ready": kw["ready"] or vcount > 0,
        "chunk_count": max(kw["chunk_count"], vcount),
        "term_count": kw["term_count"],
        # 下面是加向量检索时新增的
        "engine": engine,
        "engine_name": engine_label(engine),
        "vector_ready": vcount > 0,
        "vector_chunks": vcount,
        "vector_dims": vector_index.dims(),
        "vector_space": vector_index.space(),
        "keyword_chunks": kw["chunk_count"],
        "embed_provider": emb["provider"],
        "embed_model": emb["model"] if emb["enabled"] else "",
        "embed_reason": emb["reason"],
        "threshold": score_threshold(engine),
        "degraded": bool(reason),
        "reason": reason,
    }
