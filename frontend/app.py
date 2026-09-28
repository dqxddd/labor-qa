"""劳动权益咨询问答台 - 前端。

界面走方案 B（法务工作台）：左边是导航 + 模型参数 + 法规资料库，
中间是主要工作区，右边常驻一栏「依据详情」—— 在问答页点一下依据卡片，
右侧就换成对应的原文片段。

问答有两个入口：左栏「流式输出」开着走 /api/chat/stream（边收边画），
关掉就走 /api/chat/sync（等整段生成完再显示）。两个接口收的参数一样。
样式都在 theme.py 里。
"""

import json
import os

import requests
import streamlit as st

import theme

# 后端地址。默认连本机 8000，要用别的端口时启动前设一下环境变量就行：
#   LABOR_QA_API=http://127.0.0.1:8001 streamlit run frontend/app.py
API = os.getenv("LABOR_QA_API", "http://127.0.0.1:8000")
PAGES = ["智能问答", "知识库管理", "检索调试", "项目进度"]

# 上传放行的格式，要和后端 loader.SUPPORTED_TYPES 对上
UPLOAD_TYPES = ["md", "txt", "pdf", "docx"]

# documents.status 的取值在 backend/services/ingest.py 里写死：ready / failed / pending
STATUS_TEXT = {
    "ready": ("正常", "ok"),
    "failed": ("失败", "stop"),
    "pending": ("处理中", "warn"),
}

# 一次页面渲染里的临时缓存。Streamlit 每点一下就重跑整个脚本，
# 用这个记着，同一轮里 /health 只问后端一次（rerun 时这个字典会重新变空）
_once = {}


# ==================== 后端调用 ====================

def api_get(path, **kwargs):
    return requests.get(API + path, timeout=60, **kwargs)


def api_post(path, **kwargs):
    return requests.post(API + path, timeout=180, **kwargs)


def api_delete(path):
    return requests.delete(API + path, timeout=120)


def backend_alive():
    try:
        return api_get("/health").status_code == 200
    except requests.RequestException:
        return False


def health():
    if "health" not in _once:
        try:
            _once["health"] = api_get("/health").json()
        except Exception:
            _once["health"] = {}
    return _once["health"]


def api_count():
    """已完成接口数 —— 数后端 OpenAPI 里的路径，不写死。

    09-21 进度页上写的是"10 个"，09-22 给会话加了重命名 / 删除（新增路径
    /api/sessions/{id}）之后就变成 11 个了，写死的数字会悄悄过期。
    /openapi.json 是 FastAPI 自己生成的，数出来永远跟代码一致。
    """
    if "api_count" not in _once:
        try:
            paths = api_get("/openapi.json").json().get("paths") or {}
            _once["api_count"] = len(paths)
        except Exception:
            _once["api_count"] = 0
    return _once["api_count"]


def documents():
    """资料列表。上传 / 删除之后会主动清掉缓存，平时用它少打几次接口。

    后端是按上传时间倒序给的，界面里统一按编号从小到大排，看着顺一些。
    """
    if "doc_list" not in st.session_state:
        try:
            items = api_get("/api/documents").json()["items"]
            st.session_state["doc_list"] = sorted(items, key=lambda d: d["id"])
        except Exception:
            st.session_state["doc_list"] = []
    return st.session_state["doc_list"]


def chunks_of(doc_id):
    """某份资料的片段，也缓存一份"""
    key = "chunks_%d" % doc_id
    if key not in st.session_state:
        try:
            st.session_state[key] = api_get("/api/documents/%d/chunks" % doc_id).json()
        except Exception:
            st.session_state[key] = {"total": 0, "items": []}
    return st.session_state[key]


def forget_cache():
    for key in list(st.session_state.keys()):
        if key == "doc_list" or str(key).startswith("chunks_"):
            del st.session_state[key]


def find_chunk(chunk_id, file_name):
    """按引用记录里的 chunk_id 找到片段全文。

    引用表里只存了 100 字的摘要，这里先按文件名认出是哪份资料，
    再把它的片段列表拉下来匹配 chunk_id，拿到完整内容和段序号。
    """
    doc = next((d for d in documents() if d["file_name"] == file_name), None)
    if doc is None:
        return None, None
    detail = chunks_of(doc["id"])
    for c in detail.get("items", []):
        if c["id"] == chunk_id:
            return c, detail
    return None, detail


# ==================== 对话记忆（历史会话） ====================
#
# 问答本身一直在落库（一次连续对话 = 一条 chat_sessions，每轮存一问一答，
# 回答引用的片段存进 citations），所以"记住"这件事后端早就做完了。
# 这一段补的是**读**：把旧会话列出来、点回去、接着追问。
#
# 区别记一下，别再混：
#   多轮追问（qa.py 的 load_history）= 同一个会话里最近 N 轮带进 prompt；
#   对话记忆（这里）              = 换个新对话之后，还能从左栏捞回上一次那条。

# 点回一条旧会话时读回最近多少轮。不读全部是因为长会话要一次拉几十轮、
# 还要按轮配引用和工具记录，点一下等太久不划算；库里一条没少，只是这一屏少摊几轮。
SESSION_KEEP_TURNS = 10


def sessions(force=False):
    """左栏「历史会话」的数据。

    缓存在 session_state 里 —— 侧栏每轮渲染都要用，而 Streamlit 每点一下
    就重跑整个脚本。删除 / 重命名 / 新问出一轮之后要清掉它再拉。
    """
    if force or "sess_list" not in st.session_state:
        try:
            st.session_state["sess_list"] = api_get("/api/sessions").json()["items"]
        except Exception:
            st.session_state["sess_list"] = []
    return st.session_state["sess_list"]


def forget_sessions():
    st.session_state.pop("sess_list", None)


def trim(text, limit):
    """列表里一行放不下太长的标题，超出截断加省略号"""
    text = (text or "").strip() or "（没标题）"
    return text if len(text) <= limit else text[:limit] + "…"


def open_session(sid):
    """左栏点了某条旧会话。

    这是个 on_click 回调。回调在脚本正式重跑**之前**执行，所以在这里改
    st.session_state["nav"] 是合法的（那个 radio 还没被创建）；
    要是等脚本跑到一半再去改一个已经建好的控件 key，Streamlit 会直接报错。

    真正的读取放到问答页里做：回调里发 HTTP 请求会把界面卡在那儿，
    而"点了没反应"比"点了转一下圈"更让人摸不着头脑。
    """
    st.session_state["nav"] = "智能问答"
    st.session_state["sess_open"] = sid
    # 万一上一轮还挂着没发出去的请求，一并清掉 ——
    # 切会话的时候不该顺手把上一个问题的回答发出来
    st.session_state.pop("pending", None)
    st.session_state.pop("pending_stream", None)


def _as_turn(item, sid):
    """后端的会话记录 -> 会话区能直接画的一轮。

    字段要跟 remember_answer 存进去的那份对得上，render_turn /
    render_reply_panel 才认。历史里没有的东西（当时用的什么参数、走的哪条
    检索）一律留空 —— 界面自己会少画那一段，不假装有。
    """
    return {
        "session_id": sid,
        "question": item.get("question") or "",
        "answer": item.get("answer") or "",
        "refused": item.get("refused") or 0,
        "llm_used": None,        # 历史不判断"模型当时通没通"，见 render_turn
        "citations": item.get("citations") or [],
        "tool_calls": item.get("tool_calls") or [],
        "params": {},
        "param_notes": [],
        "history_turns": 0,
        "style": None,
        "style_name": None,
        "engine": None,
        "engine_name": None,
        "stream_used": False,
        "from_history": True,
    }


def load_session(sid):
    """把一条旧会话读回会话区，返回有没有读成功"""
    try:
        resp = api_get("/api/sessions/%d/messages" % sid,
                       params={"turns": SESSION_KEEP_TURNS})
        data = resp.json()
    except Exception:
        flash("err", "读会话记录失败，确认后端还在跑")
        return False

    if resp.status_code != 200:
        flash("err", "读会话记录失败：%s" % data.get("detail", resp.status_code))
        return False

    turns = [_as_turn(t, sid) for t in (data.get("turns") or [])]
    st.session_state["session_id"] = sid
    st.session_state["thread"] = turns
    st.session_state["cite_sel"] = (max(len(turns) - 1, 0), 0)
    # 记着"这是从旧会话读回来的"。页头那句副标题和右栏的参数说明都看它，
    # 不然历史轮里空的参数区会被当成功能坏了。
    st.session_state["loaded_from"] = {
        "title": (data.get("session") or {}).get("title") or "",
        "turns": len(turns),
    }
    return True


def do_rename(sid, title):
    """改会话标题。标题本来是自动取第一句问题的前 20 字，问得不清楚就一团乱"""
    title = (title or "").strip()
    if not title:
        flash("warn", "标题不能为空")
    else:
        try:
            resp = requests.patch(API + "/api/sessions/%d" % sid,
                                  json={"title": title}, timeout=30)
            if resp.status_code == 200:
                flash("ok", "已改名为「%s」" % title)
            else:
                flash("err", "改名失败：%s" % resp.text[:150])
        except requests.RequestException as e:
            flash("err", "改名失败：%s" % e)
    st.session_state.pop("sess_act", None)
    forget_sessions()
    st.rerun()


def do_delete(sid):
    """删掉一条会话（连同它的消息、引用、工具记录，后端一起清）"""
    try:
        resp = api_delete("/api/sessions/%d" % sid)
        if resp.status_code == 200:
            flash("ok", "已删除这条会话")
        else:
            flash("err", "删除失败：%s" % resp.text[:150])
    except requests.RequestException as e:
        flash("err", "删除失败：%s" % e)

    st.session_state.pop("sess_act", None)
    # 删掉的正好是当前在看的那条 -> 会话区一起清空。
    # 不清的话界面上还留着一份已经不存在的会话，再提问会莫名开出一条新会话。
    if st.session_state.get("session_id") == sid:
        st.session_state["session_id"] = None
        st.session_state.pop("thread", None)
        st.session_state.pop("cite_sel", None)
        st.session_state.pop("loaded_from", None)
    forget_sessions()
    st.rerun()


def render_session_panel():
    """左栏「历史会话」——"对话记忆"的入口。

    列最近动过的 50 条（后端给的顺序就是最近动过的排最前），
    点一条就把那条会话整个读回中间的会话区，接着问就是原会话的追问。
    重命名 / 删除只作用于**当前选中的那条**：左栏就这么宽，
    每行再挂两个图标按钮会把标题挤没。
    """
    st.markdown('<div class="qb-rail-title" style="margin-top:18px;">历史会话</div>',
                unsafe_allow_html=True)

    items = sessions()
    if not items:
        st.markdown('<div class="qb-rail-note">还没有历史会话。问过之后这里会按'
                    '最近问过的顺序列出来，点一下就能切回去。</div>',
                    unsafe_allow_html=True)
        return

    cur = st.session_state.get("session_id")
    titles = {s["id"]: (s.get("title") or "") for s in items}

    # 限高自己滚：侧栏下面还有模型参数和资料库，不能被几十条会话顶下去
    #
    # 标签里只留 7 个字是按可用宽度倒推的：左栏 258px 宽，这行按钮的正文
    # 只有 128px，11.5px 字号下一个汉字 11.5px、「 · N轮」约占 30px，
    # 7 个字加省略号正好 122px。给多了会被省略号把轮数吃掉（实测过），
    # 那等于白写。完整标题挂在鼠标悬停的提示里。
    with st.container(height=186, key="rail_sess"):
        for s in items:
            st.button("%s · %d轮" % (trim(s.get("title"), 7), s.get("turns", 0)),
                      key="sess_%d" % s["id"], width="stretch",
                      type="primary" if s["id"] == cur else "secondary",
                      on_click=open_session, args=(s["id"],),
                      help=s.get("title") or "")

    act = st.session_state.get("sess_act")

    if act == "rename":
        st.text_input("新标题", value=titles.get(cur, ""), key="sess_new_title",
                      label_visibility="collapsed", placeholder="给这条会话起个名字")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("保存", key="btn_rn_ok", type="primary", width="stretch"):
                do_rename(cur, st.session_state.get("sess_new_title"))
        with c2:
            if st.button("取消", key="btn_rn_no", width="stretch"):
                st.session_state.pop("sess_act", None)
                st.rerun()
        return

    if act == "delete":
        st.markdown('<div class="qb-rail-note warn">确定删掉「<b>%s</b>」？<br>'
                    '它的问答记录和依据引用会一起删掉，删了找不回来。</div>'
                    % theme.esc(trim(titles.get(cur), 12)), unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("确认删除", key="btn_del_ok", width="stretch"):
                do_delete(cur)
        with c2:
            if st.button("取消", key="btn_del_no", width="stretch"):
                st.session_state.pop("sess_act", None)
                st.rerun()
        return

    if not cur:
        st.markdown('<div class="qb-rail-note">点上面任意一条可以切回去；'
                    '改名和删除要先选中一条。</div>', unsafe_allow_html=True)
        return

    st.markdown('<div class="qb-rail-note">当前：<b>%s</b></div>'
                % theme.esc(trim(titles.get(cur), 15)), unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("重命名", key="btn_rn", width="stretch"):
            st.session_state["sess_act"] = "rename"
            st.rerun()
    with c2:
        if st.button("删除", key="btn_del", width="stretch"):
            st.session_state["sess_act"] = "delete"
            st.rerun()


# ==================== 模型参数面板 ====================

def param_spec():
    """参数面板的定义（范围、默认值、说明），由后端 /health 报上来。

    前端一个数字都不写死 —— 想改范围只动后端 config.py 里的 PARAM_SPEC。
    """
    return health().get("param_spec") or {}


def param_locks():
    """当前模型锁死的参数。锁了的滑块会置灰：
    kimi-k3 只认 temperature=1、top_p=0.95，传别的值接口直接 400。"""
    return health().get("param_locks") or {}


def current_params():
    """取左栏滑块现在的值，组成请求里的参数。键名跟后端接口字段一一对应"""
    return {
        "temperature": st.session_state.get("p_temperature"),
        "top_p": st.session_state.get("p_top_p"),
        "max_tokens": st.session_state.get("p_max_tokens"),
        "history_turns": st.session_state.get("p_history_turns"),
        "style": current_style(),
    }


# 后端 /health 里没有 styles 字段时的兜底（比如后端还是旧进程）。
# 有兜底就不会出现「切换器整个消失」那种静默故障。
FALLBACK_STYLES = [("plain", "劳动者通俗版"), ("strict", "严谨条款版")]


def style_options():
    """应答风格的候选，由后端 /health 报上来 —— 加风格只动 prompts.STYLES

    后端没上报（比如后端还是旧进程）时用兜底名字，**切换器照样画出来**，
    不搞静默消失；但这时按钮是不生效的，界面上会另给一句提示说明。
    """
    items = health().get("styles") or []
    if not items:
        return [{"key": k, "name": n} for k, n in FALLBACK_STYLES]
    return items


def styles_reported():
    """后端认不认 style 参数 —— 用它来决定要不要给提示"""
    return bool(health().get("styles"))


def style_labels():
    """{key: 中文名}，画切换器和打标签都用它"""
    return {it["key"]: it["name"] for it in style_options()}


def current_style():
    """当前选中的风格 key"""
    keys = list(style_labels())
    return st.session_state.get("p_style") or keys[0]


def _slider_args(item, value):
    """按定义里的数字类型决定用整数滑块还是小数滑块。
    max-tokens 是整数，不这样分开的话会显示成 1024.0，很难看。"""
    lo, hi, step = item["min"], item["max"], item["step"]
    if isinstance(lo, float) or isinstance(step, float):
        return float(lo), float(hi), float(value), float(step)
    return int(lo), int(hi), int(value), int(step)


def render_param_panel():
    """左栏「模型参数」。改完不用重启，下一次提问就用新值"""
    st.markdown('<div class="qb-rail-title" style="margin-top:18px;">模型参数</div>',
                unsafe_allow_html=True)

    spec = param_spec()
    if not spec:
        # 后端没上报参数定义，画不了滑块。
        # 最常见的原因：后端还是改动之前启动的旧进程，它的 /health 里没有
        # param_spec 字段。这时面板会整个变空 —— 不明原因的人只会觉得"没做"。
        # 所以这里必须显眼地说出来并给出重启命令，不能默默 return。
        st.markdown(
            '<div class="qb-rail-note warn">'
            '后端没有上报参数定义，参数面板打不开。<br><br>'
            '多半是<b>后端还在跑改动前的旧进程</b>：到启动后端的那个终端按 '
            '<code>Ctrl+C</code> 停掉，再用原命令重启'
            '（<code>uvicorn backend.main:app</code>），刷新本页就有滑块了。'
            '</div>',
            unsafe_allow_html=True)
        return

    locks = param_locks()
    model = health().get("llm_model") or "—"

    with st.container(key="rail_param"):
        for name in ("history_turns", "temperature", "top_p", "max_tokens"):
            item = spec.get(name)
            if not item:
                continue
            locked = locks.get(name)
            value = item["default"] if locked is None else locked
            lo, hi, value, step = _slider_args(item, value)
            st.slider(item["label"], lo, hi, value, step,
                      key="p_" + name, help=item.get("help", ""),
                      disabled=locked is not None)

        st.toggle("流式输出", key="p_stream", value=True,
                  help="开：回答一个字一个字往外冒；关：等整段生成完一次性显示。")

        if locks:
            st.markdown(
                '<div class="qb-rail-note">当前模型 <b>%s</b> 把 %s 锁成了固定值，'
                '对应滑块不可调 —— 换模型（改 .env 里的 LLM_MODEL）会自动放开。</div>'
                % (theme.esc(model), "、".join(theme.esc(k) for k in locks)),
                unsafe_allow_html=True)


# ==================== 小工具 ====================

def flash(kind, msg):
    """提示先存着，rerun 之后还能显示一次"""
    st.session_state["flash"] = (kind, msg)


def show_flash():
    item = st.session_state.pop("flash", None)
    if not item:
        return
    kind, msg = item
    if kind == "ok":
        st.success(msg)
    elif kind == "warn":
        st.warning(msg)
    else:
        st.error(msg)


def status_badge(status):
    text, kind = STATUS_TEXT.get(status, (status or "未知", "warn"))
    return theme.badge(text, kind)


def short_time(text):
    """2026-09-18 20:41:33 显示成 09-18 20:41，表格里放得下"""
    return text[5:16] if text else "—"


def head_with_action(title, sub, btn_label, btn_key, on_click=None):
    """页头右边挂一个按钮（目前只有问答页的「换个新会话」用）"""
    hcol, bcol = st.columns([3.1, 1])
    with hcol:
        st.markdown(theme.page_head(title, sub), unsafe_allow_html=True)
    with bcol:
        st.markdown('<div style="height:20px;"></div>', unsafe_allow_html=True)
        return st.button(btn_label, key=btn_key, width="stretch", on_click=on_click)


# ==================== 提问 ====================

def remember_answer(data):
    """把这一轮的结果追加到对话串尾部，rerun 之后照它重画整个问答区。

    以前这里存的是"最后一轮"（last_answer，只有一个），所以一问新问题
    旧的就被顶掉了；现在改成往列表里追加，历史全都留着。
    """
    st.session_state["session_id"] = data["session_id"]
    if "thread" not in st.session_state:
        st.session_state["thread"] = []
    st.session_state["thread"].append(data)
    # 右栏跟着跳到刚问完的这轮，免得还停在上一轮的引用上
    st.session_state["cite_sel"] = (len(st.session_state["thread"]) - 1, 0)
    st.session_state["clear_draft"] = True
    # 这一轮之后左栏那条会话的轮数变了（也可能是刚新建的），列表得重拉；
    # 同时"历史记录"那个标记也该摘掉 —— 上面已经有刚问出来的一轮了
    forget_sessions()
    st.session_state.pop("loaded_from", None)


def sync_ask(payload):
    """非流式：等后端整段生成完再显示。模型慢的时候要干等一会儿"""
    with st.spinner("检索资料、生成回答中…"):
        resp = api_post("/api/chat/sync", json=payload)
    if resp.status_code != 200:
        flash("err", "接口出错：%s" % resp.text[:200])
        return

    data = resp.json()
    data["stream_used"] = False
    remember_answer(data)


def stream_ask(payload):
    """流式：边收边画。

    后端推的是 SSE，一行一个 data: {...}：
      meta   —— 开场，带会话号和引用列表，先把「助手」这个头画出来
      tool   —— 业务工具算完了，把「传了什么、算出什么」先摆出来
      delta  —— 增量文本，一段段往正文里加
      done   —— 收尾，带落库后的完整结果

    收完把结果存起来，外面再 rerun 一次，用最终结果按正常样式重画一遍。
    """
    live_head = st.empty()
    live_body = st.empty()
    live_tool = st.empty()
    live_foot = st.empty()
    live_head.markdown('<div class="qb-note info">正在检索资料…</div>', unsafe_allow_html=True)
    # 生成期间这一轮还没走到下面画输入框的代码，所以输入框会暂时不在。
    # 这里明说一句，免得看着像界面坏了。
    live_foot.markdown('<div class="qb-tip">回答正在生成，输入框暂时收起来了，'
                       '写完了会回来。</div>', unsafe_allow_html=True)

    buffer = ""
    result = None
    error = None

    try:
        resp = requests.post(API + "/api/chat/stream", json=payload,
                             stream=True, timeout=300)
        with resp:
            if resp.status_code != 200:
                error = "接口出错（%d）：%s" % (resp.status_code, resp.text[:180])
            else:
                for line in resp.iter_lines():
                    if isinstance(line, bytes):          # requests 默认给的是字节
                        line = line.decode("utf-8", "ignore")
                    if not line.startswith("data:"):
                        continue                          # 空行、心跳行都跳过
                    try:
                        event = json.loads(line[5:].strip())
                    except ValueError:
                        continue

                    kind = event.get("type")
                    if kind == "meta":
                        n = len(event.get("citations") or [])
                        live_head.markdown(
                            '<div class="qb-who"><span class="mark">助</span>%s%s</div>'
                            % (theme.esc("助手 · 检索到 %d 条依据" % n if n else "助手"),
                               style_chip(event)),
                            unsafe_allow_html=True)
                    elif kind == "tool":
                        # 工具那段是后端同步跑完才推的，先显示出来，
                        # 免得后面生成的那两三秒看起来像卡住了
                        live_tool.markdown(
                            tool_note({"tool_calls": event.get("tool_calls")}),
                            unsafe_allow_html=True)
                        live_foot.markdown('<div class="qb-tip">算完了，正在按资料组织回答…'
                                           '</div>', unsafe_allow_html=True)
                    elif kind == "delta":
                        buffer += event.get("text", "")
                        live_body.markdown(buffer)
                    elif kind == "done":
                        result = event.get("result")
                    elif kind == "error":
                        error = event.get("message")
    except requests.RequestException as e:
        error = "请求失败：%s" % e

    if error:
        flash("err", error)
        return
    if not result:
        flash("err", "流里没拿到完整结果，把「流式输出」关掉再试一次")
        return

    result["stream_used"] = True
    remember_answer(result)


# ==================== 页面：智能问答 ====================

# 会话区的高度（像素）。对话装在这个固定高度的框里自己滚，提问框跟在框下面 ——
# 这样对话再长也不会把提问框顶到屏幕外面（之前的毛病）：
# 想追问随时能打字，不用先往下滚。
# theme.py 里还有一条 CSS 用 100vh 把它改成随窗口高度自适应。
CONV_HEIGHT = 430


def page_chat():
    mid, side = st.columns([2.9, 1], gap="large")

    with mid:
        # 上一轮提问成功后要清空输入框，这步得赶在下面 text_area 建出来之前做
        if st.session_state.pop("clear_draft", False):
            st.session_state["q_input"] = ""

        def new_session():
            """开一个新会话：对话串和右栏选中的引用一起清掉。

            只是把当前这条"放下"，不是删掉 —— 它还在左栏的「历史会话」里，
            点一下就能回来。这也就是"换个新对话还能返回上次"那条需求。
            """
            st.session_state["session_id"] = None
            st.session_state.pop("thread", None)
            st.session_state.pop("cite_sel", None)
            st.session_state.pop("clear_draft", None)
            st.session_state.pop("pending", None)
            st.session_state.pop("pending_stream", None)
            st.session_state.pop("loaded_from", None)

        # 正在看历史会话时，副标题直接说明白，免得以为这是刚问出来的。
        # 页头高度不变（同一行文字），不会把提问框挤下去。
        _from = st.session_state.get("loaded_from")
        _sub = "回答会标出引用了哪份资料的哪一段，右侧可以对照原文核对。"
        if _from:
            _sub = ("正在看历史会话「%s」的记录（最近 %d 轮）。接着问就是继续这个会话。"
                    % (trim(_from["title"], 14), _from["turns"]))

        head_with_action("智能问答", _sub, "换个新会话", "btn_new", on_click=new_session)
        show_flash()

        if "thread" not in st.session_state:
            st.session_state["thread"] = []
        thread = st.session_state["thread"]

        # 对话区：高度固定 -> 内部滚动，autoscroll -> 新内容自动滚到底。
        # autoscroll 必须开：否则每轮新回答都落在可视区外面，看着像没反应。
        with st.container(height=CONV_HEIGHT, key="card_conv", autoscroll=True):
            # 挂起的请求先取出来：取完就知道这轮有没有在生成，
            # 免得第一轮正在生成时那句「在下面问一句试试」还挂在上面
            pending = st.session_state.pop("pending", None)
            if not thread and not pending:
                st.markdown('<div class="qb-note info">在下面问一句试试。回答里引用了哪些片段，'
                            '右侧那一栏会列出来，可以逐条对照原文。</div>', unsafe_allow_html=True)

            # 把已经问过的轮次全部画出来。
            # 这一段必须排在「跑挂起请求」前面 —— 新回答在生成的那几秒里，
            # 之前的对话仍然留在页面上，不会像以前那样一问新的旧的就没了。
            cur_turn, cur_pick = current_cite(thread)
            for idx, past in enumerate(thread):
                if idx:
                    st.markdown('<div class="qb-turn-gap"></div>', unsafe_allow_html=True)
                render_turn(idx, past, cur_pick if idx == cur_turn else -1)

            # 上一次点「提问」挂起来的请求：放到这里跑。
            # 放在会话框里面，流式内容才会跟着一起滚、始终在可视区里。
            if pending:
                use_stream = st.session_state.pop("pending_stream", True)
                if thread:
                    st.markdown('<div class="qb-turn-gap"></div>', unsafe_allow_html=True)
                st.markdown('<div class="qb-me"><div class="who">我</div>%s</div>'
                            % theme.lines(pending["question"]), unsafe_allow_html=True)
                if use_stream:
                    stream_ask(pending)
                else:
                    sync_ask(pending)
                st.rerun()

        with st.container(key="card_composer"):
            # 应答风格切换器。两种风格共用同一套检索/引用/拒答逻辑，只换说法。
            labels = style_labels()
            keys = list(labels)
            st.segmented_control(
                "应答风格", options=keys,
                default=st.session_state.get("p_style") or keys[0],
                format_func=lambda k: labels[k],
                key="p_style", label_visibility="collapsed")

            # 后端没上报风格清单时（多半是后端没重启），按钮画得出来但不生效。
            # 不说的话表现是"切换了但回答一模一样、也没有风格标签"，很容易被当成没做。
            if not styles_reported():
                st.markdown('<div class="qb-tip">⚠ 后端没有上报风格清单（多半是后端还是'
                            '改动前的旧进程），这两个按钮暂时不生效，重启后端即可。</div>',
                            unsafe_allow_html=True)

            question = st.text_area("问题", height=76, key="q_input",
                                    label_visibility="collapsed",
                                    placeholder="比如：试用期最长能有多久？")
            row = st.columns([2.2, 1], vertical_alignment="center")
            with row[0]:
                st.markdown('<div class="qb-tip">同一会话会带上历史，支持指代追问</div>',
                            unsafe_allow_html=True)
            with row[1]:
                ask = st.button("提问", key="btn_ask", type="primary", width="stretch")

        if ask:
            if not question.strip():
                flash("warn", "先把问题写上")
            else:
                payload = current_params()
                payload["question"] = question
                payload["session_id"] = st.session_state.get("session_id")
                # 请求先挂起来，rerun 一次再真正发 —— 位置和画法都由上面那段决定
                st.session_state["pending"] = payload
                st.session_state["pending_stream"] = st.session_state.get("p_stream", True)
            st.rerun()

    with side:
        render_reply_panel(thread)


def style_chip(result):
    """回答卡片上的风格小标签。老数据没有 style 字段就返回空串，什么都不画"""
    name = result.get("style_name")
    if not name:
        return ""
    cls = "qb-chip strict" if result.get("style") == "strict" else "qb-chip"
    return '<span class="%s">%s</span>' % (cls, theme.esc(name))


def current_cite(thread):
    """右栏正在看的是哪一轮的第几条引用。

    默认看最新一轮的第一条；用户点过依据卡片之后就按他点的来。
    """
    if not thread:
        return (-1, -1)
    sel = st.session_state.get("cite_sel")
    if not sel or sel[0] >= len(thread):
        return (len(thread) - 1, 0)
    return sel


def retrieval_live():
    """重新拉一次 /health 里的检索状态。

    为什么不用 health()：那个是脚本一开始抓好的、整个 rerun 复用，
    而"这一轮到底有没有降级"要等提问跑完才知道 —— 用旧的那份会晚一轮才反映。
    只在真的降级时才走这里，平时一次多的请求都不发。
    """
    try:
        return api_get("/health").json().get("retrieval") or {}
    except Exception:
        return {}


def fallback_note(result):
    """这一轮的依据是用哪条检索路拿到的。降级了就明说，不让用户以为一切正常。

    只有"本该走向量、这次却退了关键词"才提示。
    要是整个系统本来就只配了关键词检索，每轮都弹一句纯属噪音。
    """
    if (result or {}).get("engine") != "keyword":
        return ""
    info = retrieval_live()
    if not info.get("degraded"):
        return ""
    return ('<div class="qb-note warn"><b>本轮走了兜底检索：</b>向量检索这次没成功，'
            '这一轮的依据是用关键词检索（比用词，不比语义）拿到的，命中范围会比平时窄。'
            '原因：%s</div>' % theme.esc(info.get("reason") or "未知"))


def tool_note(result):
    """这一轮有没有调业务工具。调了就把「传了什么、算出什么」如实摆出来。

    为什么值得单独占一块地方：资料片段只能告诉你"时效是一年"，
    那个具体的截止日是系统另外算的 —— 出处不一样，得让用户看得见来源，
    不然他会以为这个日期是从哪份文件里抄来的。

    ok=False 也照样显示（标成"没能算"），因为那正是模型该向用户追问的情形，
    把原因摊开比藏起来有用。
    """
    calls = (result or {}).get("tool_calls") or []
    if not calls:
        return ""

    blocks = []
    for call in calls:
        data = call.get("result") or {}
        args = call.get("arguments") or {}
        name = theme.esc(call.get("tool_name") or "—")
        arg_text = ", ".join("%s=%s" % (k, v) for k, v in args.items()
                             if v not in (None, "")) or "（没填）"

        if data.get("ok"):
            head = ('<div class="qb-tool-head">业务工具 '
                    '<span class="qb-tool-name">%s</span>'
                    '<span class="qb-tool-tag">计算成功</span>%s</div>'
                    % (name, theme.esc(data.get("topic_name") or "")))
            rows = [("入参", arg_text, False),
                    ("结果", data.get("summary") or "—", True)]
            if data.get("notes"):
                rows.append(("提醒", "；".join(data["notes"]), True))
            rows.append(("依据", data.get("basis") or "—", True))
        else:
            head = ('<div class="qb-tool-head">业务工具 '
                    '<span class="qb-tool-name">%s</span>'
                    '<span class="qb-tool-tag fail">没能算</span></div>' % name)
            rows = [("入参", arg_text, False),
                    ("原因", data.get("error") or "—", True)]

        body = "".join(
            '<div class="qb-tool-row"><span class="k">%s</span>'
            '<span class="v%s">%s</span></div>'
            % (key, " text" if as_text else "", theme.esc(value))
            for key, value, as_text in rows)
        blocks.append('<div class="qb-tool">%s%s</div>' % (head, body))
    return "".join(blocks)


def tool_summary(result):
    """右栏那一行：这一轮到底调没调工具"""
    calls = (result or {}).get("tool_calls") or []
    if not calls:
        return "未调用"
    names = []
    for call in calls:
        name = call.get("tool_name") or "—"
        names.append(name if (call.get("result") or {}).get("ok") else "%s（没能算）" % name)
    return " + ".join(names)


def render_turn(idx, result, picked):
    """画一轮问答：上面是「我」的问题，下面是助手的回答卡。

    idx 是这一轮在对话串里的位置，用来给控件生成唯一 key ——
    页面上同时存在多轮时，key 撞了 Streamlit 会直接报错。
    picked 是这一轮里当前被选中的引用下标，-1 表示这一轮没在右栏展示。
    """
    st.markdown('<div class="qb-me"><div class="who">我</div>%s</div>'
                % theme.lines(result["question"]), unsafe_allow_html=True)

    with st.container(key="card_reply_%d" % idx):
        n = len(result["citations"])
        who = "助手 · 检索到 %d 条依据" % n if n else "助手"
        # 从旧会话读回来的轮次挂个「历史」标：这些回答里没有风格标签、
        # 右栏的参数区也是空的，不标一下容易被当成"功能坏了"
        hist = ('<span class="qb-chip hist">历史记录</span>'
                if result.get("from_history") else "")
        st.markdown('<div class="qb-who"><span class="mark">助</span>%s%s%s</div>'
                    % (theme.esc(who), style_chip(result), hist), unsafe_allow_html=True)
        st.markdown(result["answer"])

        if result["refused"]:
            st.markdown('<div class="qb-note warn">资料库里没有能支撑这个问题的规定，'
                        '所以不给答案。换个问法，或者先把相关法规传上来。</div>',
                        unsafe_allow_html=True)
        elif result.get("llm_used") is False:
            # 只有**这一次**真的没接上模型才提示（llm_used 是布尔值）。
            # 历史轮次这里放的是 None，表示"当时的情况没存下来"，
            # 那就什么都不说 —— 照旧库里的记录弹一句警告是编造。
            st.markdown('<div class="qb-note warn">大模型这次没接通，上面是把检索到的依据'
                        '直接拼出来的。检查一下 .env 里的 LLM_API_KEY 和 LLM_BASE_URL。</div>',
                        unsafe_allow_html=True)

        notes = result.get("param_notes") or []
        if notes:
            st.markdown('<div class="qb-note warn"><b>参数已自动校正：</b>%s</div>'
                        % theme.esc("；".join(notes)), unsafe_allow_html=True)

        fb = fallback_note(result)
        if fb:
            st.markdown(fb, unsafe_allow_html=True)

        # 算期限的过程排在回答正文之后、依据来源之前 ——
        # 它解释的是"这个日期哪来的"，正好接在正文和出处中间
        tools_html = tool_note(result)
        if tools_html:
            st.markdown(tools_html, unsafe_allow_html=True)

        if n:
            st.markdown('<div class="qb-refs-label">依据来源（点一下，右侧看原文）</div>',
                        unsafe_allow_html=True)
            for i, c in enumerate(result["citations"]):
                if st.button("[%d] %s · 相关度 %.3f"
                             % (c["cite_index"], c["file_name"], c["score"]),
                             key="cite_%d_%d" % (idx, i), width="stretch",
                             type="primary" if i == picked else "secondary"):
                    st.session_state["cite_sel"] = (idx, i)
                    st.rerun()


def params_section(result):
    """右栏底部：这一轮「实际用出去」的参数。

    注意这不是滑块上显示的值 —— 模型锁死的参数会被后端校正，
    这里显示的是校正之后真正发给模型的那几个数。

    历史轮次没有这一段（当时没落库），这时明说一句，别留一片空白 ——
    空白会被当成"这块没做"，说明白了才是如实交代。
    """
    p = result.get("params") or {}
    if not p:
        if result.get("from_history"):
            return theme.section("模型参数（实际使用）",
                                 '<div class="qb-note info">这一轮是历史记录。当时用的模型'
                                 '参数没有落库，所以这栏是空的；问答正文、依据来源和'
                                 '相关度都是照当时存的显示。</div>')
        return ""
    return theme.section("模型参数（实际使用）", "".join([
        theme.kv("应答风格", theme.esc(result.get("style_name") or "—")),
        theme.kv("检索引擎", theme.esc(result.get("engine_name") or "—")),
        theme.kv("模型", theme.esc(p.get("model", "—"))),
        theme.kv("temperature", p.get("temperature", "—")),
        theme.kv("top-p", p.get("top_p", "—")),
        theme.kv("max-tokens", p.get("max_tokens", "—")),
        theme.kv("历史轮数", "%s 轮" % result.get("history_turns", "—")),
        theme.kv("业务工具", theme.esc(tool_summary(result))),
        theme.kv("输出方式", "流式" if result.get("stream_used") else "一次性返回"),
    ]))


def render_reply_panel(thread):
    """右栏：当前选中那条引用的原文片段。

    多轮对话时，右栏只显示一轮 —— 默认是最新那轮，点了别的轮的
    依据卡片之后就跟着切过去。
    """
    if not thread:
        st.markdown(theme.panel(
            "依据详情", "等待提问",
            '<div class="qb-note info">先提一个问题。回答引用了哪些片段，'
            '这里会逐条列出来，可以点左边依据卡片切换。</div>'), unsafe_allow_html=True)
        return

    turn, pick = current_cite(thread)
    result = thread[turn]
    cites = result["citations"]
    if pick >= len(cites):
        pick = 0

    if not cites:
        body = '<div class="qb-note warn">这次回答没有引用任何资料片段。</div>'
        body += theme.section("本次会话", "".join([
            theme.kv("会话编号", "#%s" % result["session_id"]),
            theme.kv("引用条数", "0 条"),
            theme.kv("第几轮", "第 %d 轮 / 共 %d 轮" % (turn + 1, len(thread))),
        ]))
        body += params_section(result)
        st.markdown(theme.panel("依据详情", "无引用", body), unsafe_allow_html=True)
        return

    c = cites[pick]
    chunk, detail = find_chunk(c["chunk_id"], c["file_name"])

    content = chunk["content"] if chunk else c["snippet"]
    chars = chunk["token_count"] if chunk else len(c["snippet"])
    seq = chunk["chunk_index"] if chunk else "—"
    total = detail["total"] if detail else "—"

    body = theme.section("原文片段", '<div class="qb-quote">%s</div>' % theme.lines(content))
    body += theme.section("片段信息", "".join([
        theme.kv("来源资料", theme.esc(c["file_name"])),
        theme.kv("片段序号", "第 %s 段 / 共 %s 段" % (seq, total)),
        theme.kv("字符数", "%s 字" % chars),
        theme.kv("相关度", "%.3f" % c["score"]),
    ]))
    body += theme.section("本次会话", "".join([
        theme.kv("会话编号", "#%s" % result["session_id"]),
        theme.kv("第几轮", "第 %d 轮 / 共 %d 轮" % (turn + 1, len(thread))),
        theme.kv("引用条数", "%d 条" % len(cites)),
        theme.kv("大模型", "已接入" if result["llm_used"] else "未接入"),
    ]))
    body += params_section(result)
    st.markdown(theme.panel("依据详情", "引用 [%d]" % c["cite_index"], body), unsafe_allow_html=True)


# ==================== 页面：知识库管理 ====================

def page_knowledge():
    docs = documents()
    mid, side = st.columns([2.9, 1], gap="large")

    with mid:
        st.markdown(theme.page_head(
            "知识库资料",
            "上传的法规资料会被切成 500 字左右的知识片段，存进数据库并建好检索索引。"),
            unsafe_allow_html=True)
        show_flash()

        with st.container(key="card_upload"):
            st.markdown('<div class="qb-insp-label">上传法规资料</div>', unsafe_allow_html=True)
            uploaded = st.file_uploader("上传法规资料", type=UPLOAD_TYPES,
                                        label_visibility="collapsed")
            st.markdown('<div class="qb-note info">支持 <b>md / txt / PDF / Word</b>。</div>',
                        unsafe_allow_html=True)
            row = st.columns(2)
            with row[0]:
                do_upload = st.button("上传并入库", key="btn_upload", type="primary",
                                      width="stretch")
            with row[1]:
                do_import = st.button("导入示例资料", key="btn_import", width="stretch")

        if do_import:
            with st.spinner("正在导入…"):
                data = api_post("/api/documents/import-samples").json()
            forget_cache()
            flash("ok", "导入 %d 份资料" % data.get("count", 0))
            st.rerun()

        if do_upload:
            if uploaded is None:
                flash("warn", "先选一个文件再点上传")
            else:
                with st.spinner("解析、切分、建索引…"):
                    resp = api_post("/api/documents",
                                    files={"file": (uploaded.name, uploaded.getvalue())})
                data = resp.json()
                forget_cache()
                if data.get("ok"):
                    flash("ok", data.get("msg"))
                else:
                    flash("err", "入库失败：%s" % data.get("msg"))
            st.rerun()

        st.markdown('<div class="qb-insp-label" style="margin-top:22px;">资料清单</div>',
                    unsafe_allow_html=True)
        if not docs:
            st.markdown('<div class="qb-note info">还没有资料。上面传一份，或者点'
                        '「导入示例资料」把 data/knowledge 里的法规导进来。</div>',
                        unsafe_allow_html=True)
        else:
            head = ('<tr><th style="width:44px;">编号</th><th>文件名</th>'
                    '<th style="width:70px;">类型</th><th style="width:76px;">状态</th>'
                    '<th class="r" style="width:74px;">片段数</th>'
                    '<th style="width:112px;">上传时间</th></tr>')
            rows = []
            for d in docs:
                rows.append(
                    "<tr><td class='mono'>%d</td><td>%s</td><td class='mono'>%s</td>"
                    "<td>%s</td><td class='r mono'>%d</td><td class='mono'>%s</td></tr>"
                    % (d["id"], theme.esc(d["file_name"]), theme.esc(d["file_type"]),
                       status_badge(d["status"]), d["chunk_count"], short_time(d["upload_time"])))
            st.markdown('<table class="qb-tbl"><thead>%s</thead><tbody>%s</tbody></table>'
                        % (head, "".join(rows)), unsafe_allow_html=True)

            options = {}
            for d in docs:
                options["%s（%d 个片段）" % (d["file_name"], d["chunk_count"])] = d["id"]

            with st.container(key="card_op"):
                st.markdown('<div class="qb-insp-label">资料操作</div>', unsafe_allow_html=True)
                picked = st.selectbox("选一份资料", list(options.keys()),
                                      label_visibility="collapsed")
                op = st.columns([1, 1])
                with op[0]:
                    if st.button("查看片段", key="btn_chunks", width="stretch"):
                        st.session_state["preview_doc"] = options[picked]
                        st.rerun()
                with op[1]:
                    if st.button("删除这份资料", key="btn_doc_del", width="stretch"):
                        api_delete("/api/documents/%d" % options[picked])
                        forget_cache()
                        st.session_state.pop("preview_doc", None)
                        flash("warn", "已删除「%s」" % picked)
                        st.rerun()

    with side:
        render_chunk_panel()


def render_chunk_panel():
    doc_id = st.session_state.get("preview_doc")
    if not doc_id:
        st.markdown(theme.panel(
            "片段预览", "未选择",
            '<div class="qb-note info">在左边选一份资料、点「查看片段」，'
            '这里会把它切出来的片段按顺序列出来。</div>'), unsafe_allow_html=True)
        return

    detail = chunks_of(doc_id)
    doc = detail.get("doc") or {}
    if not doc:
        st.markdown(theme.panel("片段预览", "—",
                                '<div class="qb-note warn">这份资料已经不在了，'
                                '可能刚才被删掉了。</div>'), unsafe_allow_html=True)
        return

    blocks = []
    for c in detail.get("items", []):
        blocks.append(theme.section(
            "第 %d 段 · %d 字" % (c["chunk_index"], c["token_count"]),
            '<div class="qb-quote">%s</div>' % theme.lines(c["content"])))
    if not blocks:
        blocks.append('<div class="qb-note warn">这份资料没有片段，可能解析失败了。</div>')
    blocks.append('<div class="qb-note info">切分参数：单段 <b>500 字</b>，相邻片段重叠 '
                  '<b>80 字</b>。重叠是为了不让一句话被硬切成两半。</div>')

    st.markdown(theme.panel("片段预览", doc["file_name"], "".join(blocks)), unsafe_allow_html=True)


# ==================== 页面：检索调试 ====================

def page_retrieve():
    mid, side = st.columns([2.9, 1], gap="large")

    with mid:
        st.markdown(theme.page_head(
            "检索调试",
            "这里只看检索命中了什么、分数多高，不调大模型 —— 调阈值的时候用这一页。"),
            unsafe_allow_html=True)
        show_flash()

        with st.container(key="card_form"):
            qcol, kcol, bcol = st.columns([2.4, 1.5, 0.9], vertical_alignment="bottom")
            with qcol:
                query = st.text_input("查询词", key="retr_q", placeholder="比如：加班费怎么算")
            with kcol:
                top_k = st.slider("取前几条", 1, 10, 5, key="retr_k")
            with bcol:
                go = st.button("检索", key="btn_search", type="primary", width="stretch")

        if go:
            if not query.strip():
                flash("warn", "先写个查询词")
            else:
                with st.spinner("检索中…"):
                    resp = api_post("/api/chat/retrieve", json={"query": query, "top_k": top_k})
                if resp.status_code != 200:
                    flash("err", "接口出错：%s" % resp.text[:200])
                else:
                    st.session_state["retr_result"] = resp.json()
            st.rerun()

        data = st.session_state.get("retr_result")
        if data:
            body = []
            for item in data["items"]:
                passed = item["score"] >= data["threshold"]
                body.append(
                    '<div class="qb-hit"><div class="qb-hit-head">'
                    '<span class="qb-hit-id">片段 <b>%d</b> · 资料 <b>%d</b> · 第 <b>%d</b> 段</span>'
                    '<span class="%s">%.3f %s</span></div>'
                    '<div class="qb-bar%s"><i style="width:%d%%"></i></div>'
                    '<div class="qb-hit-txt">%s</div></div>'
                    % (item["chunk_id"], item["doc_id"], item["chunk_index"],
                       "qb-pass" if passed else "qb-fail", item["score"],
                       "过线" if passed else "不过线",
                       "" if passed else " low", min(int(item["score"] * 100), 100),
                       theme.lines(item["content"])))
            if not body:
                body.append('<div class="qb-note warn">一条都没命中。换个说法试试，'
                            '或者先去知识库确认资料已经入库。</div>')

            with st.container(key="card_results"):
                st.markdown('<div class="qb-card-title">命中 %d 条'
                            '<span class="qb-tip">当前阈值 %.2f · 低于它的会被判成'
                            '「资料里没有」</span></div>' % (data["total"], data["threshold"]),
                            unsafe_allow_html=True)
                st.markdown("".join(body), unsafe_allow_html=True)

        _r = health().get("retrieval") or {}
        st.markdown('<div class="qb-note info" style="margin-top:16px;"><b>现在的检索方式：</b>'
                    '以 <b>%s</b> 为主 —— 把提问和片段都转成向量比「意思像不像」，'
                    '换个说法问（比如「被开除能赔钱吗」）也能命中。'
                    '向量接口不可用时会自动退回关键词检索（字符 bigram + TF-IDF，比的是用词），'
                    '那种情况下命中范围会明显变窄，页面上会另行提示。</div>'
                    % theme.esc(_r.get("engine_name") or "向量检索"), unsafe_allow_html=True)

    with side:
        render_retrieve_panel()


def render_retrieve_panel():
    """右栏：这一次检索到底按什么规则打的分。

    这里显示的必须是**当前真正生效**的引擎和阈值，不能写死 ——
    向量降级成关键词之后，阈值会跟着从 0.55 变成 0.35，
    要是这里还写着向量那套，用户调阈值时就会被带偏。
    """
    last = st.session_state.get("retr_result")
    r = health().get("retrieval") or {}
    # 「这次检索真正走了哪条路」优先看检索结果本身（后端随响应带回来的），
    # 还没检索过才去看 /health。
    engine = (last or {}).get("engine") or r.get("engine")
    engine_name = (last or {}).get("engine_name") or r.get("engine_name") or "—"
    # 阈值同理：后端按当时的引擎算好一起带回来的
    if last and last.get("threshold") is not None:
        threshold = "%.2f" % last["threshold"]
    elif r.get("threshold") is not None:
        threshold = "%.2f" % r["threshold"]
    else:
        threshold = "—"

    rows = [
        theme.kv("检索引擎", theme.esc(engine_name)),
        theme.kv("相似度阈值", threshold),
        theme.kv("默认返回条数", "5"),
        theme.kv("切片大小", "500 字"),
        theme.kv("片段重叠", "80 字"),
    ]
    if r.get("vector_ready"):
        rows.append(theme.kv("向量库", "%s 条 · %s 维"
                             % (r.get("vector_chunks", "—"), r.get("vector_dims", "—"))))
    rows.append(theme.kv("向量模型", theme.esc(r.get("embed_model") or "未配置")))
    rows.append(theme.kv("关键词索引", "%s 条" % r.get("keyword_chunks", "—")))
    body = theme.section("当前配置", "".join(rows))

    if r.get("degraded"):
        body += theme.section("正在降级",
                              '<div class="qb-note warn"><b>%s</b><br>%s</div>'
                              % (theme.esc("这一轮没走向量检索"),
                                 theme.esc(r.get("reason") or "向量检索不可用")))

    if engine == "vector":
        how = ('把提问和每个片段都用 %s 转成向量，算两者夹角的余弦相似度，'
               '分数越高说明意思越接近 —— 所以换个说法也能搜到。'
               % theme.esc(r.get("embed_model") or "向量模型"))
        thr = ('高于 <b>%s</b> 才认为资料里有相关内容。向量分是余弦相似度：'
               '相关的一般 0.6 以上、不相关的 0.3~0.45，所以阈值定在 0.55 附近。'
               '这个值写在后端 <b>core/config.py</b> 的 VECTOR_SCORE_THRESHOLD。'
               % threshold)
    else:
        how = ('把提问和每个片段都拆成字符二元组，用 TF-IDF 加权后算相似度，'
               '分数越高说明用词越接近 —— 这是向量检索不可用时的兜底方案，'
               '换个说法问可能就搜不到了。')
        thr = ('高于 <b>%s</b> 才认为资料里有相关内容。关键词分是查询词的覆盖率：'
               '相关的一般只有 0.2~0.4，所以阈值定在 0.35 附近。'
               '这个值写在后端 <b>core/config.py</b> 的 SCORE_THRESHOLD。'
               % threshold)
    body += theme.section("分数怎么来的", '<div class="qb-note info">%s</div>' % how)
    body += theme.section("阈值怎么定", '<div class="qb-note info">%s</div>' % thr)
    st.markdown(theme.panel("检索参数", "config.py", body), unsafe_allow_html=True)


# ==================== 页面：项目进度 ====================

# 已经实现的功能，按实现日期分组，新的排在前面。
# 日期是照开发日志和备份包的时间点写的，不是估的；报告、答辩照这个念就行。
DONE_BY_DATE = [
    ("09-22", [
        "向量检索：Chroma 向量库 + bge-m3 向量模型（余弦相似度），阈值拒答；"
        "向量接口不可用时自动降级回关键词检索，并在页面上如实说明原因",
        "PDF / Word 资料解析：PDF 走 pypdf、Word 走 python-docx，表格里的文字一起抠出来；"
        "扫描件 PDF、老版 .doc、不支持的后缀都有明确提示，不会静默失败",
        "业务工具 arbitration_limit：仲裁时效 / 追索报酬 / 工伤认定三类期限算成具体截止日，"
        "由规则预判触发，执行记录写进 tool_calls 表",
        "对话记忆：左栏「历史会话」列最近动过的 50 条，点一条把整段问答（含依据来源）"
        "读回来接着追问；支持重命名和删除",
        "应答风格切换：劳动者通俗版 / 严谨条款版两种口吻，依据和引用完全相同",
        "问答页纵向重排：会话区限高滚动、提问框钉在下方，对话再长也不会把提问框顶出去",
    ]),
    ("09-21", [
        "前端按「方案 B · 法务工作台」改版：左栏导航 + 三栏布局 + 卡片式问答",
        "模型参数面板：历史轮数 / temperature / top-p / max-tokens 运行时可调，"
        "模型锁死的参数自动置灰",
        "多轮追问 + SSE 流式输出：同会话最近 N 轮带进上下文，回答边收边画",
        "知识库扩充 6 篇法规资料（工时休假、女职工、病假、仲裁流程、解除终止、特殊用工）",
        "大模型问答真正接通（修好 .env 里 key 与接口地址不匹配的问题）",
    ]),
    ("09-18", [
        "全链路跑通：上传 → 解析 → 切分（500 字 / 重叠 80 字）→ 写库 → 建索引 → 检索 → 生成 → 落库",
        "数据库层与 8 张数据表（文档、片段、会话、消息、引用、工具调用、评测用例、评测结果）",
        "接口：资料管理 5 个、问答 3 个、会话 2 个",
        "前端四个页面：知识库管理、智能问答、检索调试、项目进度",
        "内置 4 份示例法规资料（劳动合同与试用期、工资加班、社保工伤、离职与仲裁时效），共 11 个片段",
        "关键词检索打分（字符 bigram + TF-IDF）：至少命中 2 个词才计分，命不中就走拒答",
    ]),
    ("09-17", [
        "项目骨架与配置中心：FastAPI + SQLAlchemy + SQLite 分层目录，"
        ".env 里放分块、检索、模型三组配置",
    ]),
]

TODO_ITEMS = [
    "向量模型离线化：现在 bge-m3 走在线接口，建索引要联网、有冷启动成本",
    "评测模块：15 条测试用例 + 准确率拒答率统计（eval_cases 表已建好）",
    "参数配置随会话保存到数据库，方便事后复盘当时用了什么参数",
]


def page_progress():
    mid, side = st.columns([2.9, 1], gap="large")
    total = sum(len(items) for _, items in DONE_BY_DATE)

    with mid:
        st.markdown(theme.page_head(
            "项目进度",
            "已经实现的功能按实现日期排在这里（共 %d 项），后面还要补的列在下面。" % total),
            unsafe_allow_html=True)

        with st.container(key="card_done"):
            html = '<div class="qb-card-title">已经实现的功能</div>'
            for day, items in DONE_BY_DATE:
                html += '<div class="qb-date">%s</div>' % theme.esc(day)
                html += "".join(theme.todo(x, True) for x in items)
            st.markdown(html, unsafe_allow_html=True)

        with st.container(key="card_todo"):
            st.markdown('<div class="qb-card-title">还没做的</div>'
                        + "".join(theme.todo(x, False) for x in TODO_ITEMS),
                        unsafe_allow_html=True)

    with side:
        render_progress_panel()


def render_progress_panel():
    docs = documents()
    chunks = sum(d["chunk_count"] for d in docs) or health().get("index_chunks", 0)
    metrics = '<div class="qb-metrics-2">%s</div>' % "".join([
        theme.metric("数据表", "8"),
        theme.metric("已完成接口", str(api_count() or "—")),
        theme.metric("知识片段", str(chunks)),
        theme.metric("资料份数", str(len(docs))),
    ])
    body = '<div class="qb-sec">%s</div>' % metrics
    body += theme.section("技术栈", "".join([
        theme.kv("后端", "FastAPI + SQLAlchemy"),
        theme.kv("前端", "Streamlit"),
        theme.kv("数据库", "SQLite"),
        theme.kv("文档解析", "pypdf + python-docx"),
        theme.kv("大模型", theme.esc(health().get("llm_model") or "未接入")),
    ]))
    body += theme.section("说明", '<div class="qb-note info">资料份数、知识片段、接口数都是'
                          '实时读后端的（<b>/api/documents</b> 与 <b>/openapi.json</b>），'
                          '不是写死的；数据表 8 张是照系统设计文档第五章定的，'
                          '那部分是固定项。</div>')
    st.markdown(theme.panel("项目概况", "实时", body), unsafe_allow_html=True)


# ==================== 页面组装 ====================

st.set_page_config(page_title="劳动权益咨询问答台", page_icon="⚖️", layout="wide")
theme.inject()

if not backend_alive():
    st.error("连不上后端 %s。先在项目根目录启动：uvicorn backend.main:app --reload" % API)
    st.stop()


# 左栏刚点了一条旧会话（on_click 回调留下的标记）：先把记录读回来，再画侧栏。
#
# 顺序不能反。反了的话——侧栏先渲染，那时 session_id 还是旧的——这一轮
# 列表上"当前会话"的高亮不会出现，要等下一次 rerun 才亮，
# 表现出来就是"点了看着没反应，过一会儿才亮"。
# 读数据也不能塞进 on_click 回调里，那样点下去界面会卡住不动。
_opening = st.session_state.pop("sess_open", None)
if _opening:
    load_session(_opening)


with st.sidebar:
    st.markdown('<div class="qb-brand"><div class="mark">劳</div>'
                '<div class="name">劳动权益咨询问答台</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="qb-rail-title">工作台</div>', unsafe_allow_html=True)

    page = st.radio("工作台", PAGES, key="nav", label_visibility="collapsed")

    # 「对话记忆」的入口摆在导航正下方 —— 换新会话之后第一眼就能看到上一条在哪
    render_session_panel()

    render_param_panel()

    st.markdown('<div class="qb-rail-title" style="margin-top:18px;">法规资料库</div>',
                unsafe_allow_html=True)
    _docs = documents()
    if _docs:
        st.markdown("".join(theme.doc_row(d["file_name"], "%d 段" % d["chunk_count"])
                            for d in _docs), unsafe_allow_html=True)
    else:
        st.markdown(theme.doc_row("还没有资料", "—"), unsafe_allow_html=True)

    _h = health()
    _ready = _h.get("index_ready")
    st.markdown('<div class="qb-railfoot%s"><span class="dot"></span>后端已连接 · 检索索引%s</div>'
                % ("" if _ready else " stop", "就绪" if _ready else "未就绪"),
                unsafe_allow_html=True)


_h = health()
_docs = documents()
_pill = ('<span class="qb-pill"><span class="dot"></span>索引就绪</span>' if _h.get("index_ready")
         else '<span class="qb-pill stop"><span class="dot"></span>索引未就绪</span>')
st.markdown(theme.topbar(page, '<span>法规库 %d 篇 · %d 个片段</span>%s'
                         % (len(_docs), _h.get("index_chunks", 0), _pill)),
            unsafe_allow_html=True)

if page == "智能问答":
    page_chat()
elif page == "知识库管理":
    page_knowledge()
elif page == "检索调试":
    page_retrieve()
else:
    page_progress()
