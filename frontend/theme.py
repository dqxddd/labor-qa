"""界面样式与公共小组件。

配色和间距都是照设计稿（方案 B · 法务工作台）来的：
品牌蓝 #1F5AD9，卡片白底 + 1px 浅灰描边 #E6E9EF，圆角 13px。
页面结构在 app.py 里，这里只负责"长什么样"和一些反复用到的 HTML 片段。

改颜色的话直接改下面的 CSS 就行，不用动 app.py。
"""

import html as _html


CSS = """
<style>
/* ================= 全站基调 ================= */
.stApp { --primary-color: #1F5AD9; background: #FFFFFF; }
:root { --primary-color: #1F5AD9; }

html, body, .stApp {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
               "Microsoft YaHei", "Hiragino Sans GB", sans-serif;
  font-size: 13.5px;
  color: #161A21;
}
#MainMenu, footer { display: none !important; }
[data-testid="stHeader"] { background: transparent; height: 0; }
[data-testid="stSidebarCollapsedControl"] { position: fixed; top: 10px; left: 10px; z-index: 999; }

/* 主区域留白，顶栏靠负 margin 拉成通栏 */
[data-testid="stMainBlockContainer"] { padding: 0 1.8rem 3rem !important; max-width: 100% !important; }

/* ================= 顶栏 ================= */
.qb-topbar {
  height: 54px; display: flex; align-items: center; justify-content: space-between;
  margin: 0 -1.8rem 16px; padding: 0 1.8rem;
  border-bottom: 1px solid #E6E9EF;
}
.qb-topbar .crumb { font-size: 14.5px; font-weight: 500; color: #161A21; }
.qb-topbar .meta { display: flex; align-items: center; gap: 18px; font-size: 12.5px; color: #59616F; }
.qb-pill {
  display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px;
  border-radius: 999px; background: #E9F7EF; color: #17804A; font-size: 12px;
}
.qb-pill.stop { background: #FCEDEB; color: #C0392B; }
.qb-pill .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

/* ================= 左侧栏 ================= */
[data-testid="stSidebar"] {
  background: #F8F9FB; border-right: 1px solid #E6E9EF;
  width: 258px !important; min-width: 258px !important;
}
[data-testid="stSidebarUserContent"] { padding: 14px 12px 20px !important; }
[data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] { gap: 0.3rem; }

.qb-brand { display: flex; align-items: center; gap: 11px; padding: 2px 8px 16px; }
.qb-brand .mark {
  width: 28px; height: 28px; border-radius: 8px; background: #1F5AD9; color: #fff;
  font-size: 14px; display: flex; align-items: center; justify-content: center;
}
.qb-brand .name { font-size: 13.5px; font-weight: 500; color: #161A21; white-space: nowrap; }

.qb-rail-title {
  font-size: 11.5px; color: #8B93A1; letter-spacing: .6px;
  padding: 0 10px; margin: 8px 0 6px;
}

/* 导航：把 Streamlit 的 radio 做成侧栏菜单。
   1.63 的 radio 用 react-aria 重写过，选中态是 data-selected 属性，
   圆点在 label > div > div > div 第一个子元素里，所以选择器按这个结构写 */
[data-testid="stSidebar"] [data-testid="stRadioGroup"] { gap: 3px; }
[data-testid="stSidebar"] [data-testid="stRadioOption"] {
  padding: 8px 11px; border-radius: 9px; margin: 0;
  transition: background .12s, box-shadow .12s;
}
[data-testid="stSidebar"] [data-testid="stRadioOption"]:hover { background: #EEF1F6; }
[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div > div:first-child {
  display: none !important;
}
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] {
  background: #fff; box-shadow: 0 1px 2px rgba(20, 30, 50, .07);
}
[data-testid="stSidebar"] [data-testid="stRadioOption"] p {
  font-size: 13.5px !important; color: #59616F !important; margin: 0 !important;
}
[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p {
  color: #1F5AD9 !important; font-weight: 500 !important;
}

/* 法规资料库列表 */
.qb-doc { display: flex; align-items: center; gap: 9px; padding: 7px 11px; border-radius: 6px;
  font-size: 12.5px; color: #59616F; }
.qb-doc .grain { width: 3px; height: 13px; border-radius: 2px; background: #D3D9E3; flex-shrink: 0; }
.qb-doc .t { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.qb-doc .c { font-size: 11.5px; color: #8B93A1; }

/* ================= 左栏「历史会话」（对话记忆） =================
   每一条是一个 Streamlit 按钮，这里把它压成"列表项"的样子：
   透明底、左对齐、标题过长省略。跟上面工作台菜单用同一套选中观感
   （选中 = 浅蓝底 + 蓝字），因为两者都是"点一下切过去"。
   容器 key 是 rail_sess，所以作用范围只在那一块里面，不会误伤别处的按钮。 */
[class*="st-key-rail_sess"] { padding: 3px; }
[class*="st-key-rail_sess"] [data-testid="stButton"] { margin: 0; width: 100%; }
[class*="st-key-rail_sess"] button {
  justify-content: flex-start !important; text-align: left !important;
  width: 100%; padding: 6px 9px !important; border: 0 !important;
  background: transparent !important; border-radius: 8px !important;
  /* 必须裁：按钮宽 146px、正文只有 128px，标题一长，里面的 <p> 会往外溢。
     裁在按钮上，省略号才会落在该落的地方 */
  overflow: hidden !important;
}
/* 只有"直接子层"能写宽度：它的百分比基数是按钮正文（128px），
   再往里的层不能写（见下面那条注释） */
[class*="st-key-rail_sess"] button > * { width: 100% !important; overflow: hidden; }
/* 光在 button 上写 text-align 不够：Streamlit 的按钮标签包了三层
   （button > div > span > div > p），每一层自己都带着 justify-content: center，
   它默认要把标签居中。盒子"跟着文字走"的时候，盒子里的左对齐是看不出来的 ——
   实测：标题 8 字那行文字起点在 31px、5 字那行在 53px，看着就是居中。
   所以两件事要一起做：
     ① 每一层都改成靠左 —— justify-content: flex-start
     ② 每一层都允许被压缩 —— min-width: 0
   ② 千万别写成 width: 100%：里层是 flex 子项、flex-basis 是 auto，
   百分比会按"弹性基础尺寸"（文字固有宽度 153px）算，<p> 反而被撑到 153px
   溢出按钮（比 button 正文 128px 还宽），末端直接被裁掉。
   给了 min-width: 0，里层就会乖乖缩到 128px，然后 <p> 自己出省略号。 */
[class*="st-key-rail_sess"] button,
[class*="st-key-rail_sess"] button * {
  justify-content: flex-start !important;
  text-align: left !important;
  min-width: 0 !important;
}
[class*="st-key-rail_sess"] button:hover { background: #EEF1F6 !important; }
[class*="st-key-rail_sess"] button p {
  /* 11.5px 是按可用宽度倒推出来的：按钮宽 146px、左右内边距各 9px，
     正文只有 128px；标题 7 个字 + 「 · N轮」最宽 122px，正好留 6px 余量。
     宽度这里写死的 128px（不是 100%）：里层是 flex 子项，百分比会按
     "弹性基础尺寸"（文字固有宽度）解析，写完反而比按钮还宽、末端被裁掉。
     钉死之后 <p> 永远是 128px，标题再长也会规规矩矩出省略号。 */
  width: 128px !important; max-width: 128px !important;
  font-size: 11.5px !important; color: #59616F !important;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
[class*="st-key-rail_sess"] [data-testid="stBaseButton-primary"] { background: #EDF3FE !important; }
[class*="st-key-rail_sess"] [data-testid="stBaseButton-primary"] p {
  color: #1F5AD9 !important; font-weight: 500 !important;
}

/* 「确认删除」用红色，跟普通主按钮（蓝）区分开 —— 这是不可逆的操作 */
[class*="st-key-btn_del_ok"] button {
  background: #C0392B !important; border-color: #C0392B !important;
}
[class*="st-key-btn_del_ok"] button:hover { background: #A32D2D !important; }
[class*="st-key-btn_del_ok"] button p { color: #fff !important; }

/* ================= 左栏「模型参数」 =================
   258px 宽里要塞 4 个滑块 + 1 个开关，所以把标签和刻度都压小一号。
   这里不挑具体的 testid，直接用容器 class 兜住里面所有 label，
   控件结构升级了也不会失效。 */
[class*="st-key-rail_param"] { padding: 0 3px; }
[class*="st-key-rail_param"] label p {
  font-size: 11.5px !important; color: #59616F !important; margin-bottom: 2px !important;
}
[class*="st-key-rail_param"] [data-testid="stTickBarMin"],
[class*="st-key-rail_param"] [data-testid="stTickBarMax"] {
  font-size: 10px !important; color: #A8B0BC !important;
}
[class*="st-key-rail_param"] [data-testid="stSlider"] { padding-bottom: 0 !important; }
[class*="st-key-rail_param"] [data-testid="stToggle"] label { gap: 6px; }
[data-testid="stSidebar"] [data-testid="stTooltipIcon"] { transform: scale(.85); }

.qb-rail-note {
  font-size: 11px; line-height: 1.6; color: #8B93A1;
  background: #F2F4F8; border-radius: 8px; padding: 8px 10px; margin: 8px 3px 0;
}
.qb-rail-note b { color: #59616F; font-weight: 500; }

/* 参数面板拿不到参数定义时的告警样式。
   最常见的原因是后端还是改动前启动的旧进程，/health 里没有 param_spec 字段。
   这种情况必须显眼地说出来，否则面板会静默变空，看着就像功能没做。 */
.qb-rail-note.warn {
  color: #8A4B12; background: #FDF3E4; border: 1px solid #F0DCC0;
}
.qb-rail-note.warn code {
  background: #F5E6CE; border-radius: 4px; padding: 1px 4px;
  font-size: 10.5px; color: #7A4410;
  /* 只在空格处断行，别把 uvicorn 命令从中间劈开 */
  word-break: break-word; overflow-wrap: break-word;
}

.qb-railfoot {
  margin-top: 14px; padding: 11px 8px 0; border-top: 1px solid #E6E9EF;
  font-size: 11.5px; color: #8B93A1; display: flex; align-items: center; gap: 7px;
}
.qb-railfoot .dot { width: 6px; height: 6px; border-radius: 50%; background: #17804A; }
.qb-railfoot.stop .dot { background: #C0392B; }

/* ================= 页头 ================= */
.qb-head { padding: 18px 0 15px; border-bottom: 1px solid #E6E9EF; margin-bottom: 18px; }
.qb-h1 { font-size: 17px; font-weight: 500; color: #161A21; letter-spacing: .2px; }
.qb-sub { font-size: 12.5px; color: #59616F; margin-top: 3px; line-height: 1.55; }

/* ================= 卡片容器 =================
   app.py 里 st.container(key="card_xxx") 会生成 class="st-key-card_xxx"，
   下面这条就把它们统一做成设计稿里的白卡片 */
[class*="st-key-card_"] {
  border: 1px solid #E6E9EF; border-radius: 13px; background: #fff;
  padding: 15px 17px;
}
.qb-card-title {
  font-size: 13px; font-weight: 500; margin-bottom: 10px;
  display: flex; align-items: center; justify-content: space-between;
}

/* ================= 对话 ================= */
.qb-me {
  width: fit-content; max-width: 82%; margin-left: auto; margin-bottom: 14px;
  background: #1F5AD9; color: #fff;
  border-radius: 13px 13px 4px 13px; padding: 10px 15px;
  font-size: 13.5px; line-height: 1.6;
}
.qb-me .who { font-size: 11px; opacity: .78; margin-bottom: 3px; letter-spacing: .3px; }
.qb-who {
  font-size: 11.5px; color: #8B93A1; margin-bottom: 8px;
  display: flex; align-items: center; gap: 7px;
}
.qb-who .mark {
  width: 16px; height: 16px; border-radius: 5px; background: #EDF3FE; color: #1F5AD9;
  font-size: 10px; font-weight: 500;
  display: flex; align-items: center; justify-content: center;
}
.qb-refs-label {
  font-size: 11.5px; color: #8B93A1; margin: 14px 0 8px;
  padding-top: 12px; border-top: 1px dashed #E6E9EF;
}
.qb-tip { font-size: 11.5px; color: #8B93A1; }

/* 应答风格小标签，跟在「助手 · 检索到 N 条依据」后面。
   两种风格给两种颜色，扫一眼就知道这轮用的哪种 */
.qb-chip {
  font-size: 11px; padding: 2px 8px; border-radius: 999px;
  background: #EDF3FE; color: #1F5AD9; letter-spacing: .2px;
}
.qb-chip.strict { background: #EEF0F4; color: #59616F; }
/* 从旧会话读回来的轮次挂的「历史记录」标。颜色比风格标签更淡 ——
   它标的是"这条不是刚问的"，不是又一个属性 */
.qb-chip.hist { background: #F2F4F8; color: #8B93A1; }

/* 业务工具调用记录，挂在回答卡片里。
   跟 .qb-note 刻意区分开：那个是"说明文字"，这个是"系统做了一次计算"，
   所以用带边框的块 + 等宽字体标工具名，让它看起来像一条执行记录。 */
.qb-tool {
  margin-top: 13px; padding: 12px 14px; border-radius: 10px;
  background: #F7F9FC; border: 1px solid #DCE3EE;
}
.qb-tool-head {
  display: flex; align-items: center; flex-wrap: wrap; gap: 8px;
  font-size: 11.5px; color: #3C4A5F; margin-bottom: 9px;
}
.qb-tool-name {
  font-family: ui-monospace, "Cascadia Mono", Consolas, monospace;
  font-size: 11.5px; color: #1F5AD9; background: #EDF3FE;
  padding: 2px 7px; border-radius: 5px;
}
.qb-tool-tag {
  font-size: 11px; padding: 2px 8px; border-radius: 999px;
  background: #E8F3EC; color: #2C6B45;
}
.qb-tool-tag.fail { background: #FDF3E2; color: #B26A00; }
.qb-tool-row {
  display: flex; gap: 10px; font-size: 12.5px; line-height: 1.65; padding: 2px 0;
}
.qb-tool-row .k { flex: 0 0 44px; color: #8B93A1; }
.qb-tool-row .v {
  flex: 1; color: #2B3445;
  font-family: ui-monospace, "Cascadia Mono", Consolas, monospace;
  word-break: break-all;
}
.qb-tool-row .v.text { font-family: inherit; }

/* ================= 会话区（限高滚动） =================
   乙方案：对话装在这个固定高度的框里自己滚，提问框钉在它下面，
   所以对话再长也不会把提问框顶出屏幕。
   st.container(height=..., autoscroll=True) 负责滚动和"新内容自动到底"，
   这里只管观感：内边距收紧一点、滚动条做细。 */
/* 高度跟着窗口走：窗口高就多给对话留点地方，窗口矮就收一收，
   保证提问框永远在可视区里 —— 这才是乙方案的意义。
   470px 是页头 + 提问框 + 上下留白的固定开销（430 是 app.py 里的兜底默认值）。

   踩过的坑，别再改回去：
   1. 高度不在会话框自己身上，而在它外面那层 div（Streamlit 的块容器），
      会话框是被父层拉伸的 —— 所以得用 :has() 从父层下手；
   2. 光设 height 没用！那一层是弹性布局的子项，实际尺寸来自 flex-basis
      （flex: 0 0 430px），height 属性被忽略。必须改 flex-basis。
   3. min-height / max-height 是能盖住 flex-basis 的，所以上下限靠它俩。
   :has() 需要 Chrome/Edge 105+、Safari 15.4+、Firefox 121+，
   更老的浏览器会退回 app.py 里那个 430px，不至于坏掉。 */
div:has(> [class*="st-key-card_conv"]) {
  flex-basis: calc(100vh - 470px) !important;
  height: auto !important;
  min-height: 200px !important;
  max-height: 700px !important;
}
[class*="st-key-card_conv"] { padding: 13px 16px !important; }
[class*="st-key-card_conv"] *::-webkit-scrollbar { width: 8px; height: 8px; }
[class*="st-key-card_conv"] *::-webkit-scrollbar-thumb { background: #D8DDE6; border-radius: 4px; }
[class*="st-key-card_conv"] *::-webkit-scrollbar-thumb:hover { background: #C2C9D4; }
[class*="st-key-card_conv"] *::-webkit-scrollbar-track { background: transparent; }

/* ================= 提问框上方的应答风格切换器 =================
   key="p_style"，Streamlit 会生成 class="st-key-p_style"。
   选中态在不同的控件上属性名不一样（pills 用 testid 后缀 Active，
   radio 用 data-selected），所以三个都写上，换控件也不用改这里。 */
[class*="st-key-p_style"] { margin-bottom: 6px; }
[class*="st-key-p_style"] [role="radiogroup"],
[class*="st-key-p_style"] [data-testid="stButtonGroup"] { gap: 7px; }
[class*="st-key-p_style"] button {
  border-radius: 999px !important; padding: 4px 13px !important;
  border: 1px solid #D3D9E3 !important; background: #fff !important;
}
[class*="st-key-p_style"] button p { font-size: 12px !important; color: #59616F !important; }
[class*="st-key-p_style"] button[data-testid*="Active"],
[class*="st-key-p_style"] button[data-selected="true"],
[class*="st-key-p_style"] button[aria-checked="true"] {
  background: #1F5AD9 !important; border-color: #1F5AD9 !important;
}
[class*="st-key-p_style"] button[data-testid*="Active"] p,
[class*="st-key-p_style"] button[data-selected="true"] p,
[class*="st-key-p_style"] button[aria-checked="true"] p {
  color: #fff !important; font-weight: 500 !important;
}
[class*="st-key-p_style"] button:hover { border-color: #BFC7D4 !important; }

/* 两轮问答之间的一条淡分隔线，多轮堆在一起时用来看清边界 */
.qb-turn-gap { height: 1px; background: #F0F2F6; margin: 26px 0 20px; }

/* 引用卡片按钮：左对齐、更像列表项。
   注意 key 里的下划线在 class 名里是原样保留的（cite_0_1 -> st-key-cite_0_1），
   所以这里写 "st-key-cite" 而不是 "st-key-cite-"，带不带轮次前缀都能匹配上 */
[class*="st-key-cite"] button {
  justify-content: flex-start !important; text-align: left !important;
  padding: 9px 12px !important;
}
[class*="st-key-cite"] button p { font-size: 12.5px !important; color: #161A21 !important; }

/* ================= 右栏面板 ================= */
.qb-panel {
  background: #FBFCFD; border: 1px solid #E6E9EF; border-radius: 13px; padding: 16px 18px;
}
.qb-panel-title {
  font-size: 13px; font-weight: 500; display: flex; align-items: center;
  justify-content: space-between; padding-bottom: 13px;
  border-bottom: 1px solid #E6E9EF; margin-bottom: 16px;
}
.qb-panel-title .tag { font-size: 11.5px; color: #8B93A1; font-weight: 400; }
.qb-sec + .qb-sec { margin-top: 20px; padding-top: 18px; border-top: 1px solid #E6E9EF; }
.qb-insp-label { font-size: 11.5px; color: #8B93A1; letter-spacing: .3px; margin-bottom: 8px; }
.qb-quote {
  border-left: 2px solid #1F5AD9; padding: 2px 0 2px 12px;
  font-size: 13px; line-height: 1.8; color: #161A21;
}
.qb-kv { display: flex; justify-content: space-between; font-size: 12.5px; padding: 5px 0; }
.qb-kv .k { color: #59616F; }
.qb-kv .v { color: #161A21; }
.qb-note { border-radius: 9px; padding: 11px 13px; font-size: 12.5px; line-height: 1.65; }
.qb-note.info { background: #EDF3FE; color: #17439E; }
.qb-note.warn { background: #FDF3E2; color: #B26A00; }
.qb-note b { font-weight: 500; }

.qb-metric { background: #F4F6F9; border-radius: 9px; padding: 12px 13px; }
.qb-metric .l { font-size: 11.5px; color: #59616F; margin-bottom: 4px; }
.qb-metric .n { font-size: 21px; font-weight: 500; line-height: 1.25; }
.qb-metrics-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }

/* ================= 表格 ================= */
.qb-tbl { width: 100%; border-collapse: collapse; }
.qb-tbl th {
  text-align: left; font-size: 11.5px; font-weight: 500; color: #8B93A1;
  letter-spacing: .3px; padding: 0 12px 9px;
  border-bottom: 1px solid #E6E9EF; white-space: nowrap;
}
.qb-tbl td { padding: 11px 12px; font-size: 13px; border-bottom: 1px solid #E6E9EF; vertical-align: middle; }
.qb-tbl tr:last-child td { border-bottom: 0; }
.qb-tbl tbody tr:hover { background: #F6F9FF; }
.qb-tbl .r { text-align: right; }
.qb-tbl .mono { font-variant-numeric: tabular-nums; }

.qb-badge {
  display: inline-flex; align-items: center; gap: 5px; padding: 2px 9px;
  border-radius: 999px; font-size: 11.5px; line-height: 1.7;
}
.qb-badge.ok { background: #E9F7EF; color: #17804A; }
.qb-badge.warn { background: #FDF3E2; color: #B26A00; }
.qb-badge.stop { background: #FCEDEB; color: #C0392B; }

/* ================= 检索命中 ================= */
.qb-hit { padding: 13px 0; border-bottom: 1px solid #E6E9EF; }
.qb-hit:last-child { border-bottom: 0; }
.qb-hit-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 7px; }
.qb-hit-id { font-size: 12.5px; color: #59616F; }
.qb-hit-id b { color: #161A21; font-weight: 500; }
.qb-bar { height: 4px; border-radius: 3px; background: #EDF0F5; overflow: hidden; margin-bottom: 8px; }
.qb-bar > i { display: block; height: 100%; border-radius: 3px; background: #1F5AD9; }
.qb-bar.low > i { background: #B9C1CE; }
.qb-hit-txt { font-size: 12.5px; color: #59616F; line-height: 1.65; }
.qb-pass { color: #17804A; font-weight: 500; font-size: 13px; }
.qb-fail { color: #8B93A1; font-size: 13px; }

/* ================= 进度清单 ================= */
/* 日期小标题：左边日期、右边拖一条细线，像时间轴的分节 */
.qb-date { display: flex; align-items: center; gap: 9px; margin: 13px 0 1px;
  font-size: 12px; color: #8B93A1; letter-spacing: .3px; }
.qb-date::after { content: ""; flex: 1; height: 1px; background: #EDF0F5; }
.qb-todo { display: flex; gap: 10px; padding: 7px 0; font-size: 13px; line-height: 1.65; }
.qb-todo .mk {
  width: 15px; height: 15px; flex-shrink: 0; margin-top: 4px; border-radius: 4px;
  display: flex; align-items: center; justify-content: center; font-size: 10px;
}
.qb-todo.done { color: #161A21; }
.qb-todo.done .mk { background: #E9F7EF; color: #17804A; }
.qb-todo.todo-item { color: #59616F; }
.qb-todo.todo-item .mk { background: #F4F6F9; color: #8B93A1; border: 1px solid #D3D9E3; }

/* ================= 控件 ================= */
[data-testid="stBaseButton-secondary"] {
  background: #fff !important; border: 1px solid #D3D9E3 !important;
  border-radius: 9px !important; padding: 7px 14px !important;
  transition: background .12s, border-color .12s;
}
[data-testid="stBaseButton-secondary"]:hover { background: #F4F6F9 !important; border-color: #BFC7D4 !important; }
[data-testid="stBaseButton-secondary"] p { font-size: 13px !important; color: #161A21 !important; }

[data-testid="stBaseButton-primary"] {
  background: #1F5AD9 !important; border: 1px solid #1F5AD9 !important;
  border-radius: 9px !important; padding: 7px 14px !important;
  transition: background .12s, border-color .12s;
}
[data-testid="stBaseButton-primary"]:hover { background: #17439E !important; border-color: #17439E !important; }
[data-testid="stBaseButton-primary"] p { font-size: 13px !important; color: #fff !important; font-weight: 500 !important; }

[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {
  border-radius: 9px !important; font-size: 13.5px !important; color: #161A21 !important;
}
[data-testid="stTextArea"] textarea { line-height: 1.6 !important; }
[data-testid="stSelectbox"] [data-baseweb="select"] > div { border-radius: 9px !important; font-size: 13px !important; }

[data-testid="stFileUploaderDropzone"],
[data-testid="stFileUploader"] section {
  border: 1.5px dashed #C9D1DD !important; border-radius: 13px !important;
  background: #F4F6F9 !important; padding: 16px !important;
}
[data-testid="stFileUploaderDropzone"] small,
[data-testid="stFileUploader"] small { font-size: 12px !important; color: #8B93A1 !important; }

[data-testid="stCaptionContainer"] p { font-size: 12px !important; color: #8B93A1 !important; }
[data-testid="stAlertContainer"] { border-radius: 9px; }

/* 窄屏（笔记本分屏等）右栏容易挤，这里让它自动往下折 */
@media (max-width: 1180px) {
  [data-testid="stSidebar"] { width: 220px !important; min-width: 220px !important; }
  [data-testid="stMainBlockContainer"] { padding: 0 1rem 3rem !important; }
  .qb-topbar { margin: 0 -1rem 14px; padding: 0 1rem; }
}
</style>
"""


def inject():
    """把样式注入页面（每个页面开头调用一次就够了，重复调用也没影响）"""
    import streamlit as st

    st.markdown(CSS, unsafe_allow_html=True)


# ---------------- 下面都是拼 HTML 的小工具 ----------------

def esc(text):
    """拼 HTML 之前先转义，免得文件名/回答里的符号把标签搞坏"""
    return _html.escape(str(text))


def lines(text):
    """转义 + 换行变 <br>，用于把多行纯文本塞进 HTML 块"""
    return esc(text).replace("\n", "<br>")


def kv(key, value):
    return '<div class="qb-kv"><span class="k">%s</span><span class="v">%s</span></div>' % (esc(key), value)


def section(label, body):
    return '<div class="qb-sec"><div class="qb-insp-label">%s</div>%s</div>' % (esc(label), body)


def panel(title, tag, body):
    """右栏那种带标题条的浅色面板"""
    head = '<div class="qb-panel-title">%s<span class="tag">%s</span></div>' % (esc(title), esc(tag))
    return '<div class="qb-panel">%s%s</div>' % (head, body)


def page_head(title, sub):
    return '<div class="qb-head"><div class="qb-h1">%s</div><div class="qb-sub">%s</div></div>' % (
        esc(title), esc(sub))


def topbar(crumb, meta_html):
    return ('<div class="qb-topbar"><div class="crumb">%s</div>'
            '<div class="meta">%s</div></div>') % (esc(crumb), meta_html)


def doc_row(name, count):
    return ('<div class="qb-doc"><span class="grain"></span>'
            '<span class="t">%s</span><span class="c">%s</span></div>') % (esc(name), count)


def badge(text, kind="ok"):
    return '<span class="qb-badge %s">%s</span>' % (kind, esc(text))


def metric(label, value):
    return '<div class="qb-metric"><div class="l">%s</div><div class="n">%s</div></div>' % (
        esc(label), esc(value))


def todo(text, done=True):
    cls = "done" if done else "todo-item"
    mark = "✓" if done else ""
    return '<div class="qb-todo %s"><span class="mk">%s</span><span>%s</span></div>' % (cls, mark, esc(text))
