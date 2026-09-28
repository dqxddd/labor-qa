"""FastAPI 入口。

9.18 路由拆成 3 个模块注册（资料 / 问答 / 会话）。
评测路由还没开始写；业务工具不单独开路由 —— 它是问答链路里的一步
（见 services/tools.py 和 qa._tool_round），跟着 /api/chat 一起走。
启动时做两件事：建表、检查检索索引在不在。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api import chat, documents, sessions
from backend.core.config import APP_ENV, APP_NAME, LLM_MODEL, PARAM_SPEC, TOOL_ENABLED
from backend.core.db import Base, engine
from backend.models.chat import ChatSession, Citation, Message, ToolCall   # noqa: F401
from backend.models.document import Chunk, Document                        # noqa: F401
from backend.models.evaluation import EvalCase, EvalResult                 # noqa: F401
from backend.services import indexer, llm, prompts, tools


@asynccontextmanager
async def lifespan(app):
    # 建表前必须把上面那些模型 import 进来，Base 里才登记得到
    Base.metadata.create_all(bind=engine)
    if indexer.ensure_index():
        print("[启动] 检索索引文件不在，已按库里的片段自动补建")
    yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)

app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(sessions.router)


@app.get("/health")
def health_check():
    # 顺手把库和索引的状态也报出来，联调的时候好排查
    info = indexer.index_info()
    locks = llm.model_locks()
    return {
        "status": "ok",
        "app": APP_NAME,
        "env": APP_ENV,
        "index_ready": info["ready"],
        "index_chunks": info["chunk_count"],
        # 前端左栏「模型参数」面板照下面这份定义画滑块，范围/默认值都不在前端写死。
        # param_locks 里有的参数说明当前模型把它锁死了，前端会置灰并说明原因。
        "llm_model": LLM_MODEL,
        "param_spec": PARAM_SPEC,
        "param_locks": locks,
        # 应答风格清单，前端拿它画切换器 —— 加风格只动 prompts.STYLES
        "styles": prompts.style_options(),
        # 检索现在走哪条路：向量（Chroma + bge-m3）/ 关键词（兜底）。
        # 降级时 reason 里写着为什么，前端照实显示 —— 不假装一切正常。
        "retrieval": info,
        # 业务工具：算哪几类期限。前端照这份清单显示，不写死。
        # enabled=False 时整条链路完全不碰工具，方便和"关掉工具"的效果做对照。
        "tool": dict(tools.info(), enabled=TOOL_ENABLED),
    }
