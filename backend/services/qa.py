"""问答编排：检索 -> 看分数够不够 -> 拒答或者生成 -> 落库。

本轮在原基础上加了四件事：

1. 运行时参数：temperature / top_p / max_tokens 由前端滑块传进来，
   先过一遍 llm.resolve_params() 做参数自适应（模型锁死的值会被校正）；
2. 多轮追问：把同一会话里最近 N 轮问答带进上下文，N 由前端的滑块决定，
   0 表示不带历史、每次都是单轮问答；
3. 指代兜底：当前问题一条都没过线、又开着历史时，把上一轮的问句拼进来再搜一次，
   用来对付「那试用期呢」这种省略主语的追问；
4. 流式：ask_stream() 逐段把回答吐出去，ask() 是同步版，
   两者共用同一套编排（_context / _save），不会出现两份逻辑对不上的情况。

9.22 又加了一件：应答风格。style 跟其他参数一样从请求里传进来，
   只换系统提示词那一段。检索、引用、拒答、历史、流式全都不受影响 ——
   两种风格共用的硬规则写在 prompts.STYLE_COMMON 里。

9.22 傍晚再加一件：检索换成了向量检索（Chroma + bge-m3），
   _retrieve() 会从 indexer.search 拿到"这次用的哪个引擎"，
   并按引擎现取阈值 —— 两条路的分数口径不一样，不能共用一个数。
   用的是哪个引擎会一路带到前端和落库结果里。

9.22 晚再加一件：业务工具。链路从"检索 -> 生成"变成
   "检索 -> 看要不要算期限 -> 算 -> 把结果回填 -> 生成"。
   两个设计要点：

   * 工具排**在拒答判断之后** —— 检索一条都没过线就直接拒答，
     工具根本轮不到执行。库外问题（怎么申请专利）不会因为有个计算器
     就硬答，拒答底线原样保留。
   * 工具轮是"非流式"的：得先把结构化入参拿到手才能执行，
     这跟边生成边推送是两回事。所以流式问答里工具那段单独走完整请求，
     之后再用流式生成正文，前端会先收到一个 tool 事件。
"""

import json
from datetime import date, datetime

from backend.core.config import HISTORY_TURNS, TOOL_ENABLED, TOP_K
from backend.core.db import SessionLocal
from backend.models.chat import ChatSession, Citation, Message, ToolCall
from backend.models.document import Document
from backend.services import indexer, llm, prompts, tools

# 检索分数低于阈值时的固定回答，别让模型自由发挥
REFUSE_TEXT = ("资料库里没有找到能支撑这个问题的规定，我不凭印象回答。\n\n"
               "可以试试：换一种问法、或者先上传相关的法规资料。"
               "着急的话建议打当地劳动保障热线 12333 问一下。")

# 历史里的助手回答只留开头这么多字 —— 带 8 轮上下文时别把 prompt 撑得太大
HISTORY_ANSWER_KEEP = 300

# 追问的指代词。只有当前问题里出现这些词、而且自己一条都没搜到时，
# 才把上一轮的问句拼进来重搜。
#
# 这里必须加这个条件 —— 一开始是无条件拼的，结果测试发现：
# 同一会话里先问「加班费怎么算」再问「怎么申请专利」（库外问题），
# 因为它自己搜不到，就借了上一轮的"加班费"去搜，搜到两条不相关的片段
# 就硬答了出来，把"没依据就拒答"这条底线弄丢了。
FOLLOW_UP_WORDS = ("那", "这个", "那个", "它", "上述", "上面", "刚才", "前面",
                   "同样", "类似", "这种情况", "我这种", "还有", "另外")


def load_history(db, session_id, turns):
    """取同一会话里最近的 N 轮问答，拼成模型能直接用的消息列表。

    一轮 = 一问一答，所以往回捞 turns*2 条消息，再按时间正序排回来。
    """
    if not turns or not session_id:
        return []

    rows = (db.query(Message)
              .filter(Message.session_id == session_id)
              .order_by(Message.id.desc())
              .limit(int(turns) * 2)
              .all())

    history = []
    for m in reversed(rows):
        text = m.content or ""
        if m.role == "assistant" and len(text) > HISTORY_ANSWER_KEEP:
            text = text[:HISTORY_ANSWER_KEEP] + "……"
        history.append({"role": m.role, "content": text})
    return history


def _retrieve(question, history, turns):
    """检索。返回 (命中列表, 实际拿去搜的那句话, 用的哪个引擎)。

    先用当前问题搜。一条都不过线、又开着历史的时候，判断一下是不是省略主语的追问
    （问题里带「那」「这个」这类指代词）：是的话把上一轮问句拼进来再搜一次，
    不是的话就当库外问题，照常走拒答。

    阈值必须按引擎现取（indexer.score_threshold）—— 向量和关键词的分数
    不是一个口径，写死一个数必然有一边是错的。
    """
    hits, engine = indexer.search(question)
    threshold = indexer.score_threshold(engine)
    hits = [(c, s) for c, s in hits if s >= threshold][:TOP_K]
    if hits or not turns:
        return hits, question, engine

    if not any(w in question for w in FOLLOW_UP_WORDS):
        return hits, question, engine

    asked = [h["content"] for h in history if h["role"] == "user"]
    if not asked:
        return hits, question, engine

    merged = "%s %s" % (asked[-1], question)
    hits, engine = indexer.search(merged)
    threshold = indexer.score_threshold(engine)
    hits = [(c, s) for c, s in hits if s >= threshold][:TOP_K]
    return hits, merged, engine


def _context(question, session_id, options):
    """把这次问答要用的东西都准备好：会话、历史、检索结果、实际参数。

    返回的 ctx 里带着数据库连接，调用方用完必须 db.close()。
    """
    question = (question or "").strip()
    if not question:
        raise ValueError("问题不能为空")

    options = options or {}
    params, notes = llm.resolve_params(options)

    turns = options.get("history_turns")
    turns = HISTORY_TURNS if turns is None else max(int(turns), 0)

    style = prompts.resolve_style(options.get("style"))

    db = SessionLocal()
    try:
        session = None
        if session_id:
            session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session is None:
            session = ChatSession(title=question[:20])
            db.add(session)
            db.commit()

        # 历史必须在存本次提问之前读，否则会把当前这个问题也捞进去
        history = load_history(db, session.id, turns)

        db.add(Message(session_id=session.id, role="user", content=question))
        db.commit()

        hits, used_query, engine = _retrieve(question, history, turns)

        # 片段来自哪份资料，回答里的来源要显示文件名
        doc_names = {}
        if hits:
            doc_ids = list({c.doc_id for c, _ in hits})
            for d in db.query(Document).filter(Document.id.in_(doc_ids)).all():
                doc_names[d.id] = d.file_name

        contexts = [(i, doc_names.get(c.doc_id, "未知资料"), c.content)
                    for i, (c, s) in enumerate(hits, start=1)]

        messages = None
        if hits:
            messages = [{"role": "system", "content": prompts.system_prompt(style)}]
            messages += history          # 多轮：历史问答排在系统提示后面
            messages.append({
                "role": "user",
                "content": prompts.build_user_prompt(question, contexts,
                                                     with_history=bool(history)),
            })

        return {
            "db": db,
            "session": session,
            "question": question,
            "history": history,
            "hits": hits,
            "contexts": contexts,
            "doc_names": doc_names,
            "messages": messages,
            "refused": 0 if hits else 1,
            "params": params,
            "notes": notes,
            "turns": turns,
            "used_query": used_query,
            "engine": engine,
            "engine_name": indexer.engine_label(engine),
            "style": style,
            "style_name": prompts.style_name(style),
            "tool_calls": [],        # 有没有算期限，等 _tool_round 跑完才知道
        }
    except Exception:
        db.close()
        raise


def _citations(ctx):
    """把命中片段整理成引用列表（前端右栏和落库都用它）"""
    return [{
        "cite_index": i,
        "chunk_id": c.id,
        "score": s,
        "file_name": ctx["doc_names"].get(c.doc_id, "未知资料"),
        "snippet": c.content[:100],
    } for i, (c, s) in enumerate(ctx["hits"], start=1)]


def _save(db, ctx, answer, llm_used):
    """把这一轮落库（助手消息 + 引用记录 + 工具调用记录），返回给前端的结果"""
    ai_msg = Message(session_id=ctx["session"].id, role="assistant",
                     content=answer, refused=ctx["refused"])
    db.add(ai_msg)
    ctx["session"].updated_at = datetime.now()   # 这个字段只给了 default，改动时要自己更新
    db.commit()

    citations = _citations(ctx)
    for item in citations:
        db.add(Citation(message_id=ai_msg.id, chunk_id=item["chunk_id"],
                        cite_index=item["cite_index"], score=item["score"],
                        snippet=item["snippet"]))
    db.commit()

    # 工具调用留痕：调了哪个工具、传了什么、算出什么。这张表 9.18 就建好占位了，
    # 一直空着 —— 现在终于有东西可写。事后复盘"当时算的是哪一天"全靠它。
    tool_calls = ctx.get("tool_calls") or []
    for item in tool_calls:
        db.add(ToolCall(message_id=ai_msg.id, tool_name=item["tool_name"],
                        arguments=json.dumps(item["arguments"], ensure_ascii=False),
                        result=json.dumps(item["result"], ensure_ascii=False),
                        status=item["status"]))
    if tool_calls:
        db.commit()

    return {
        "session_id": ctx["session"].id,
        "message_id": ai_msg.id,
        "question": ctx["question"],
        "answer": answer,
        "refused": ctx["refused"],
        "llm_used": llm_used,
        "citations": citations,
        "params": ctx["params"],
        "param_notes": ctx["notes"],
        "history_turns": ctx["turns"],
        "engine": ctx["engine"],
        "engine_name": ctx["engine_name"],
        "style": ctx["style"],
        "style_name": ctx["style_name"],
        "tool_calls": tool_calls,
    }


def _fallback_text(error, contexts):
    """大模型没接通时的降级回答：把检索到的依据原样拼出来，前端还能用"""
    text = "（大模型未接入：%s）\n\n先给你找到的依据：\n" % error
    for i, name, content in contexts:
        text += "\n[%d] %s：%s" % (i, name, content[:150])
    return text


# ==================== 业务工具（9.22 晚加） ====================

def _parse_args(raw):
    """模型给的入参是 JSON 字符串，解不出来就当归空字典。

    这里是故意不报错的：让工具自己去说"拿不到起算日"，
    比在这儿抛异常、把整轮问答带崩强得多。
    """
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _tool_round(ctx):
    """工具轮：问模型该不该算、参数填什么 -> 真的执行 -> 把结果回填进消息。

    返回记录列表（前端展示和写 tool_calls 表都用它）。不用调、或者中间任何一步
    失败，一律返回空列表 —— 工具是加分项，它自己出问题不该把正常问答带崩。

    这里对模型是"强制要求"给入参（tool_choice="required"）：实测
    DeepSeek-V3.1 在 auto 下不肯调工具，会把该算的问题变成一句反问
    （详见 scripts/probe_toolcall2.py）。"该不该调"的判断已经在上面
    用 tools.match 的规则做完了，所以这里强制是安全的。
    """
    if not TOOL_ENABLED:
        return []
    topics = tools.match(ctx["question"])
    if not topics:
        return []

    messages = list(ctx["messages"])
    # 模型不知道今天几号，碰到"去年 3 月"这种相对说法会换算错，先把日期给它。
    # 规则层已经判出类别的，一并告诉它，省得它自己猜错（见 prompts.tool_time_hint）。
    hint = date.today().isoformat()
    if len(topics) == 1:
        topic_hint = (topics[0], tools.TOPIC_NAMES[topics[0]])
    else:
        topic_hint = (None, None)
    messages[-1] = {
        "role": "user",
        "content": messages[-1]["content"] + "\n\n"
                   + prompts.tool_time_hint(hint, *topic_hint),
    }

    try:
        msg = llm.chat_message(messages, ctx["params"],
                               tools=tools.spec(), tool_choice="required")
    except llm.LLMError:
        return []

    raw = msg.get("tool_calls") or []
    if not raw:
        # 强制了还是不给 tool_calls，说明模型或网关不认这套协议。
        # 不当报错处理，按"这轮没算期限"继续走，问答照常进行。
        return []

    messages.append({"role": "assistant", "content": msg.get("content") or "",
                     "tool_calls": raw})

    records = []
    for one in raw:
        fn = one.get("function") or {}
        name = fn.get("name") or ""
        args = _parse_args(fn.get("arguments"))
        if name == tools.TOOL_NAME:
            result = tools.compute(args.get("topic"), args.get("start_date"),
                                   args.get("still_employed"))
        else:
            result = {"ok": False, "error": "模型调了没登记的工具 %s" % name}

        messages.append({"role": "tool",
                         "tool_call_id": one.get("id") or name,
                         "content": json.dumps(result, ensure_ascii=False)})
        records.append({
            "tool_name": name,
            "topic": args.get("topic"),
            "arguments": args,
            "result": result,
            "status": "success" if result.get("ok") else "failed",
        })

    # 工具算出的截止日不在"资料片段"里。不点明它可以照用，
    # 模型会当成越界信息忽略掉 —— 那就白算一场了。
    messages.append({"role": "user", "content": prompts.TOOL_RESULT_HINT})

    ctx["messages"] = messages
    return records


def ask(question, session_id=None, options=None):
    """同步问答：等模型整段生成完，一次性返回"""
    ctx = _context(question, session_id, options)
    db = ctx["db"]
    try:
        if ctx["refused"]:
            return _save(db, ctx, REFUSE_TEXT, llm_used=False)

        # 检索有依据之后才轮到算期限。库外问题上面已经拒答走掉了，到不了这里。
        ctx["tool_calls"] = _tool_round(ctx)

        llm_used = True
        try:
            answer = llm.chat(ctx["messages"], ctx["params"])
        except llm.LLMError as e:
            answer = _fallback_text(e, ctx["contexts"])
            llm_used = False

        return _save(db, ctx, answer, llm_used)
    finally:
        db.close()


def ask_stream(question, session_id=None, options=None):
    """流式问答。依次吐出三类事件，前端按 type 分支处理：

      {"type": "meta",  ...}        开场：会话号、引用列表、实际用的参数
      {"type": "delta", "text": "…"} 增量文本，一段一段来
      {"type": "done",  "result": {…}} 收尾：落库后的完整结果
    """
    ctx = _context(question, session_id, options)
    db = ctx["db"]
    try:
        yield {
            "type": "meta",
            "session_id": ctx["session"].id,
            "question": ctx["question"],
            "refused": ctx["refused"],
            "citations": _citations(ctx),
            "params": ctx["params"],
            "param_notes": ctx["notes"],
            "history_turns": ctx["turns"],
            "engine": ctx["engine"],
            "engine_name": ctx["engine_name"],
            "style": ctx["style"],
            "style_name": ctx["style_name"],
        }

        if ctx["refused"]:
            yield {"type": "delta", "text": REFUSE_TEXT}
            yield {"type": "done", "result": _save(db, ctx, REFUSE_TEXT, llm_used=False)}
            return

        # 工具那段是同步跑完的（要先拿到入参才能算），所以单独推一个事件，
        # 免得用户在这两三秒里以为页面卡住了
        ctx["tool_calls"] = _tool_round(ctx)
        if ctx["tool_calls"]:
            yield {"type": "tool", "tool_calls": ctx["tool_calls"]}

        buffer = ""
        llm_used = True
        try:
            for piece in llm.stream(ctx["messages"], ctx["params"]):
                buffer += piece
                yield {"type": "delta", "text": piece}
        except llm.LLMError as e:
            # 已经在往外吐了，就接着把依据补上，别让用户拿到半截话
            extra = _fallback_text(e, ctx["contexts"])
            extra = ("\n\n" + extra) if buffer else extra
            buffer += extra
            yield {"type": "delta", "text": extra}
            llm_used = False

        yield {"type": "done", "result": _save(db, ctx, buffer, llm_used)}
    finally:
        db.close()
