"""会话记录接口：查历史会话、读回某条会话的全部问答、重命名、删除。

这个模块对应界面上的「对话记忆」：

* 左栏「历史会话」列表读的是 GET /api/sessions；
* 点回某条旧会话，读的是 GET /api/sessions/{id}/messages ——
  它不只返回消息原文，还把**引用记录和工具调用**一并还原，
  不然历史里的回答卡片点不出「依据来源」，看着就像缺了一块；
* 重命名 / 删除是 9.22 晚补的，之前列表只能看不能用。

数据是问答时顺手落库的（见 services/qa.py 的 _save）：一次连续对话算一个
会话，每轮存一问一答，回答里引用了哪段存进 citations 表。
所以"记忆"这件事后端一直在做，这里只是把它读出来。
"""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func

from backend.core.db import SessionLocal
from backend.models.chat import ChatSession, Citation, Message, ToolCall
from backend.models.document import Chunk, Document

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# 一次最多读回几轮。前端点一下旧会话时传 turns 覆盖它。
DEFAULT_TURNS = 10


class RenameRequest(BaseModel):
    title: str


def _json_or_empty(raw):
    """tool_calls 表里 arguments / result 存的是 JSON 字符串，读回来要转成对象"""
    try:
        return json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}


@router.get("")
def list_sessions():
    """历史会话列表，最近动过的排最前面。

    每条的 turns 是"问过几轮"（助手消息条数），左栏那一列拿它显示「N 轮」。
    排序用 updated_at 而不是 id：接着往下追问的老会话应该浮到最上面，
    这样"返回上次对话"第一眼就能看到。
    """
    db = SessionLocal()
    try:
        rows = (db.query(ChatSession)
                  .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
                  .limit(50).all())

        counts = dict(db.query(Message.session_id, func.count(Message.id))
                        .filter(Message.role == "assistant")
                        .group_by(Message.session_id).all())

        items = []
        for s in rows:
            data = s.to_dict()
            data["turns"] = counts.get(s.id, 0)
            items.append(data)
        return {"total": len(items), "items": items}
    finally:
        db.close()


@router.get("/{session_id}/messages")
def list_messages(session_id: int, turns: int = DEFAULT_TURNS):
    """读回一条会话的问答记录。

    返回两块内容：

    * items —— 原始消息，保持以前的样子，别的脚本还在用；
    * turns —— 按"一问一答"配对好的轮次，每条带着引用和工具调用记录，
      前端会话区照它就能把整段历史原样重画出来。

    turns 参数只保留**最近 N 轮**（默认 10，传 0 表示全都要）。
    往回找的方式是先定位问句的位置，再从那一句开始截 ——
    这样不会把一问一答从中间切开。
    """
    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")

        rows = (db.query(Message).filter(Message.session_id == session_id)
                .order_by(Message.id).all())
        total = len(rows)

        starts = [i for i, m in enumerate(rows) if m.role == "user"]
        if turns and turns > 0 and len(starts) > turns:
            rows = rows[starts[-turns]:]

        # 引用记录：按助手消息 id 归拢，顺手把片段属于哪份资料查出来 ——
        # 前端右栏要点开原文，没有文件名就找不着片段
        msg_ids = [m.id for m in rows if m.role == "assistant"]
        cites = {}
        if msg_ids:
            found = (db.query(Citation, Chunk, Document)
                       .join(Chunk, Citation.chunk_id == Chunk.id)
                       .join(Document, Chunk.doc_id == Document.id)
                       .filter(Citation.message_id.in_(msg_ids))
                       .order_by(Citation.cite_index).all())
            for c, chunk, doc in found:
                cites.setdefault(c.message_id, []).append({
                    "cite_index": c.cite_index,
                    "chunk_id": c.chunk_id,
                    "score": round(c.score, 3),
                    "file_name": doc.file_name,
                    "snippet": c.snippet,
                })

        tools = {}
        if msg_ids:
            for t in (db.query(ToolCall).filter(ToolCall.message_id.in_(msg_ids))
                        .order_by(ToolCall.id).all()):
                tools.setdefault(t.message_id, []).append({
                    "tool_name": t.tool_name,
                    "arguments": _json_or_empty(t.arguments),
                    "result": _json_or_empty(t.result),
                    "status": t.status,
                })

        built = []
        for m in rows:
            if m.role == "user":
                built.append({
                    "question": m.content or "",
                    "answer": "",
                    "refused": 0,
                    "citations": [],
                    "tool_calls": [],
                    "created_at": m.to_dict()["created_at"],
                })
            elif m.role == "assistant" and built:
                # 只认最后一轮 —— 数据本来就该是一问一答交替，真出现连着的
                # 两条助手消息，多出来的也不会被丢掉，是并进当前轮里
                built[-1].update({
                    "answer": m.content or "",
                    "refused": m.refused,
                    "citations": cites.get(m.id, []),
                    "tool_calls": tools.get(m.id, []),
                })

        return {
            "session": session.to_dict(),
            "total": total,
            "returned_turns": len(built),
            "items": [m.to_dict() for m in rows],
            "turns": built,
        }
    finally:
        db.close()


@router.patch("/{session_id}")
def rename_session(session_id: int, req: RenameRequest):
    """改会话标题。

    标题本来是自动取第一句问题的前 20 个字（见 qa._context），
    问得不清楚的话列表里就全是一堆看不懂的短句，所以留个手动改的口子。
    """
    title = (req.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")

    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        session.title = title[:60]
        db.commit()
        return {"ok": True, "session": session.to_dict()}
    finally:
        db.close()


@router.delete("/{session_id}")
def delete_session(session_id: int):
    """删掉一条会话，连同它的消息、引用记录、工具调用记录。

    三张表没有配级联删除，所以按"先子后父"的顺序手动删 ——
    citations / tool_calls 挂着 message_id，messages 挂着 session_id。
    顺序反过来的话，SQLite 一旦开了外键约束就会报错。
    """
    db = SessionLocal()
    try:
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")

        msg_ids = [r[0] for r in db.query(Message.id)
                   .filter(Message.session_id == session_id).all()]
        if msg_ids:
            db.query(ToolCall).filter(ToolCall.message_id.in_(msg_ids)) \
                .delete(synchronize_session=False)
            db.query(Citation).filter(Citation.message_id.in_(msg_ids)) \
                .delete(synchronize_session=False)
            db.query(Message).filter(Message.session_id == session_id) \
                .delete(synchronize_session=False)
        db.delete(session)
        db.commit()
        return {"ok": True, "deleted_messages": len(msg_ids)}
    finally:
        db.close()
