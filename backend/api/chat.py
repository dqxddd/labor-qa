"""问答接口。

两个入口：
  /api/chat/sync   —— 同步问答，等整段生成完一次性返回，前端走 spinner
  /api/chat/stream —— SSE 流式问答，一段一段推，前端边收边画
  /api/chat/retrieve —— 只跑检索不生成，调阈值的时候用

前端「模型参数」面板的值随请求一起传进来（都可选，不传就用 .env 里的默认值），
真正发出去之前会过一遍 llm.resolve_params() 做参数自适应。
"""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.services import indexer, qa


class AskRequest(BaseModel):
    question: str
    session_id: int | None = None
    # 下面四个来自左栏「模型参数」面板，不给就用后端默认值
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    history_turns: int | None = None
    # 应答风格，来自提问框上方的切换器；不认识的值由 prompts.resolve_style 兜回默认
    style: str | None = None


class RetrieveRequest(BaseModel):
    query: str
    top_k: int = 5


router = APIRouter(prefix="/api/chat", tags=["chat"])


def _options(req):
    """挑出请求里显式给了的参数；没给的键不出现，后端就会用默认值"""
    given = {
        "temperature": req.temperature,
        "top_p": req.top_p,
        "max_tokens": req.max_tokens,
        "history_turns": req.history_turns,
        "style": req.style,
    }
    return {k: v for k, v in given.items() if v is not None}


@router.post("/sync")
def ask_sync(req: AskRequest):
    """同步问答：检索 + 生成 + 落库，一次返回"""
    try:
        return qa.ask(req.question, req.session_id, _options(req))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/retrieve")
def retrieve(req: RetrieveRequest):
    """只跑检索不生成，调阈值的时候用这个看分数。

    返回值里带上这次用的引擎 —— 阈值是随引擎变的（向量是余弦相似度、
    关键词是覆盖率，不是一个口径），前端要照它挑"过线 / 不过线"的分界值，
    所以阈值也一起报回去，不写死在页面上。
    """
    hits, engine = indexer.search(req.query, top_k=req.top_k)
    threshold = indexer.score_threshold(engine)
    return {
        "query": req.query,
        "engine": engine,
        "engine_name": indexer.engine_label(engine),
        "threshold": threshold,
        "total": len(hits),
        "items": [
            {
                "chunk_id": c.id,
                "doc_id": c.doc_id,
                "chunk_index": c.chunk_index,
                "score": s,
                "content": c.content[:200],
            }
            for c, s in hits
        ],
    }


@router.post("/stream")
def ask_stream(req: AskRequest):
    """SSE 流式问答。每行一个 `data: {...}`，前端按 type 字段分支处理。

    这里没有改用 async —— 生成回答的过程本身是"调外部接口 + 写库"，
    用同步 def 交给 FastAPI 的线程池跑，StreamingResponse 照样能把内容推出去。
    """
    def events():
        try:
            for event in qa.ask_stream(req.question, req.session_id, _options(req)):
                # ensure_ascii=False：中文直接出，不转 \u 码，抓包看着才舒服
                yield "data: %s\n\n" % json.dumps(event, ensure_ascii=False)
        except ValueError as e:
            yield "data: %s\n\n" % json.dumps({"type": "error", "message": str(e)},
                                              ensure_ascii=False)
        except Exception as e:                      # 兜底：别让流断了前端却不知道为什么
            yield "data: %s\n\n" % json.dumps(
                {"type": "error", "message": "服务端出错：%s" % e}, ensure_ascii=False)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",     # 万一前面挂了 nginx，别让它把流缓冲掉
        },
    )
