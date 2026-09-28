"""业务工具：把"法定期限"算成具体日期。

和检索不一样 —— 检索负责"资料里是怎么写的"，工具负责"落到你身上是哪一天"。
用户问「我 2026 年 3 月 1 日被辞退，现在还能申请仲裁吗」，检索只能翻出
「时效期间为一年」这条原文，算不出截止日；这个工具就是补这一段的。

动这个文件之前先看三条硬规矩：

1. **只算不判**。工具不决定"该不该回答"，那是检索和阈值的事。
   编排里它排在"检索命中之后"（见 qa._tool_round），所以库外问题
   （怎么申请专利）根本走不到这里，拒答底线不受影响。
2. **算不出来就明说**。缺起算日、日期格式不对，一律返回 ok=False + 原因，
   由模型转成一句追问。**绝不猜一个日期出来** —— 猜出来的日期比不答更危险，
   用户照着错的截止日去准备材料，损失是实打实的。
3. **法条原文照抄**。BASIS 里的条文是给人核对用的，别顺手润色。

9.22 新加。三类期限，跟 README 待办里写的一致。
"""

import re
from datetime import date, timedelta

TOOL_NAME = "arbitration_limit"

# 三类期限，key 就是工具的 topic 入参
TOPIC_NAMES = {
    "arbitration": "劳动争议申请仲裁时效",
    "wage": "追索劳动报酬的时效",
    "injury": "工伤认定申请期限",
}

# "从哪一天开始算"。这一步最容易搞错，所以要原样列给用户看
START_LABELS = {
    "arbitration": "知道或者应当知道权利被侵害之日",
    "wage": "劳动关系终止之日（也就是离职那天）",
    "injury": "事故伤害发生之日（或者被诊断、鉴定为职业病之日）",
}

BASIS = {
    "arbitration": "《劳动争议调解仲裁法》第二十七条第一款：劳动争议申请仲裁的时效期间为一年。"
                   "仲裁时效期间从当事人知道或者应当知道其权利被侵害之日起计算。",
    "wage": "《劳动争议调解仲裁法》第二十七条第四款：劳动关系存续期间因拖欠劳动报酬发生争议的，"
            "劳动者申请仲裁不受本条第一款规定的仲裁时效期间的限制；但是，劳动关系终止的，"
            "应当自劳动关系终止之日起一年内提出。",
    "injury": "《工伤保险条例》第十七条：职工发生事故伤害或者按照职业病防治法规定被诊断、"
              "鉴定为职业病，所在单位应当自事故伤害发生之日或者被诊断、鉴定为职业病之日起"
              "三十日内，向统筹地区社会保险行政部门提出工伤认定申请。用人单位未按前款规定"
              "提出工伤认定申请的，工伤职工或者其近亲属、工会组织在事故伤害发生之日或者被"
              "诊断、鉴定为职业病之日起一年内，可以直接向用人单位所在地统筹地区社会保险"
              "行政部门提出工伤认定申请。",
}

# ==================== 什么时候该调这个工具（规则预判） ====================
#
# 为什么不交给模型自己决定：实测（scripts/probe_toolcall2.py）把选择权完全
# 交给模型、tool_choice 设成 auto 时，DeepSeek-V3.1 **不调**，反而回一句
# "请问今天是几号" —— 换成 deepseek-ai/DeepSeek-V3、Qwen3-8B、Qwen2.5-7B
# 都肯调。所以改成后端先用规则判断，判断该调才把工具递上去、并强制调用。
#
# 两道门槛都要过：既要有"局限"的意思，又要落到某个话题上。
TIME_WORDS = ("时效", "期限", "多久", "多长时间", "过期", "超期",
              "还来得及", "来得及", "来不及", "还能申请", "还能告", "还能不能",
              "截止", "最后期限", "时间内", "多少天", "几个月内", "几年内")

TOPIC_WORDS = {
    "arbitration": ("仲裁",),
    # "拖欠"单独列出来："拖欠我工资""拖欠了工资"这种中间插字的写法，
    # "拖欠工资"四个字连不上，逐字匹配会漏
    "wage": ("拖欠工资", "拖欠", "欠薪", "欠工资", "工资没发", "工资不发",
             "克扣工资", "追索劳动报酬", "要回工资", "要得回工资", "工资不给", "不给工资"),
    "injury": ("工伤",),
}

# 有些说法本身就自带了"期限"的意思，不必再等"时效"两个字出现。
# 只有明确指向某个期限规则的说法才算强词 —— 比如"工伤认定"本身就是一个
# 有法定申请期的动作，"仲裁"却不是（光说仲裁可能是问流程）。
STRONG_WORDS = {
    "arbitration": (),
    "wage": ("拖欠", "欠薪", "欠工资", "追索劳动报酬", "克扣工资",
             "要回工资", "要得回工资", "工资不给", "不给工资"),
    "injury": ("工伤认定", "认定工伤", "申报工伤", "工伤申请"),
}


def match(question):
    """这个问题需不需要算期限？返回可能相关的 topic 列表，空列表表示不用调。

    话题词命中之后，还要再过一道：要么问题里问到了时限，要么用的是强词。
    这样才不会把"泛问"也拽进来：
      「仲裁流程是什么」   有"仲裁"但没问时限、也不是强词 -> 不调
      「工伤待遇有哪些」   有"工伤"但没问时限、也不是强词 -> 不调
      「老板拖欠我工资」   强词命中（拖欠工资本身就带期限规则）-> 调
      「工伤认定要在多久内申请」问到了时限 -> 调
    """
    text = question or ""
    asked_time = any(w in text for w in TIME_WORDS)

    topics = []
    for key, words in TOPIC_WORDS.items():
        if not any(w in text for w in words):
            continue
        if asked_time or any(w in text for w in STRONG_WORDS.get(key, ())):
            topics.append(key)
    return topics


# ==================== 工具本体 ====================

def compute(topic=None, start_date=None, still_employed=None):
    """执行工具。任何情况都返回结构化结果，不往上抛异常。

    返回 ok=True 时带 deadlines 列表；ok=False 时带 error 说明为什么算不出来
    （由模型转成向用户追问）。
    """
    topic = (topic or "").strip()
    if topic not in TOPIC_NAMES:
        return _fail("不认识的话题 %r，只能是 %s 之一"
                     % (topic, " / ".join(TOPIC_NAMES)))

    checked_on = date.today()

    # 拖欠工资是唯一的例外：还在职的时候压根没有截止日
    if topic == "wage" and still_employed is True:
        return {
            "ok": True,
            "tool": TOOL_NAME,
            "topic": topic,
            "topic_name": TOPIC_NAMES[topic],
            "start_date": None,
            "start_label": START_LABELS[topic],
            "deadlines": [],
            "summary": "劳动关系还在存续期间，因拖欠劳动报酬发生争议的，"
                       "申请仲裁不受一年时效限制，所以没有截止日。"
                       "但要留意：一旦离职，就要从离职之日起一年内提出。",
            "basis": BASIS[topic],
            "checked_on": checked_on.isoformat(),
        }

    start = _parse_date(start_date)
    if start is None:
        return _fail("拿不到起算日（收到的是 %r）。请先问用户一个具体日期，"
                     "比如哪天被辞退的、哪天受的伤。" % (start_date,))

    if topic == "arbitration":
        deadlines = [_one("劳动者（申请人）", "自起算日起一年内",
                          _add_years(start, 1), checked_on)]
    elif topic == "wage":
        deadlines = [_one("劳动者（申请人）", "自劳动关系终止之日起一年内",
                          _add_years(start, 1), checked_on)]
    else:
        # 工伤是两个并行期限，不是一个
        deadlines = [
            _one("用人单位", "自起算日起三十日内",
                 start + timedelta(days=30), checked_on),
            _one("工伤职工或其近亲属、工会组织", "自起算日起一年内",
                 _add_years(start, 1), checked_on),
        ]

    return {
        "ok": True,
        "tool": TOOL_NAME,
        "topic": topic,
        "topic_name": TOPIC_NAMES[topic],
        "start_date": start.isoformat(),
        "start_label": START_LABELS[topic],
        "deadlines": deadlines,
        "summary": _summarize(start, deadlines),
        "notes": _notes(topic, still_employed),
        "basis": BASIS[topic],
        "checked_on": checked_on.isoformat(),
    }


def spec():
    """OpenAI 格式的工具声明，直接塞进请求的 tools 字段"""
    return [{
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "计算劳动法定期限的截止日。当用户问「我某天被辞退 / 受伤，"
                "现在还能不能办、要在多久之内办」这类涉及期限的问题时调用。"
                "这个工具只做日期计算，法律依据仍然由资料片段提供。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "enum": list(TOPIC_NAMES),
                        "description": "arbitration=申请仲裁的时效；"
                                       "wage=追索被拖欠的劳动报酬；"
                                       "injury=申请工伤认定",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "起算日，格式 YYYY-MM-DD。"
                                       "用户没有说出任何具体日期时，"
                                       "必须填空字符串，不要自己编一个日期。",
                    },
                    "still_employed": {
                        "type": "boolean",
                        "description": "只对 topic=wage 有意义：用户是否仍在该单位上班。"
                                       "用户没明说就别填。",
                    },
                },
                "required": ["topic", "start_date"],
            },
        },
    }]


def info():
    """/health 报给前端看的工具清单 —— 前端不写死这几个名字，加一类只动上面的表"""
    return {
        "name": TOOL_NAME,
        "topics": [{"key": k, "name": v} for k, v in TOPIC_NAMES.items()],
    }


# ==================== 内部小工具 ====================

def _one(who, rule, deadline, checked_on):
    left = (deadline - checked_on).days
    return {
        "who": who,
        "rule": rule,
        "deadline": deadline.isoformat(),
        "days_left": left,
        "expired": left < 0,
    }


def _summarize(start, deadlines):
    parts = []
    for d in deadlines:
        if d["expired"]:
            parts.append("%s 的截止日是 %s，已经过了 %d 天"
                         % (d["who"], d["deadline"], -d["days_left"]))
        elif d["days_left"] == 0:
            parts.append("%s 的截止日就是今天（%s）" % (d["who"], d["deadline"]))
        else:
            parts.append("%s 的截止日是 %s，还剩 %d 天"
                         % (d["who"], d["deadline"], d["days_left"]))
    return "按起算日 %s 计算：%s。" % (start.isoformat(), "；".join(parts))


def _notes(topic, still_employed):
    """附带的提醒。这些都是"光看数字会误解"的地方，宁可多说一句"""
    if topic == "wage" and still_employed is None:
        return ["没能确定用户是否还在职。上面按已离职算的一年 —— "
                "如果还在职，这一条不适用，不受一年限制。"]
    if topic == "injury":
        return ["工伤是两个并行期限：单位 30 日、职工一方 1 年，"
                "哪一条适用要看是谁去申请。"]
    if topic == "arbitration":
        return ["起算日是「知道权利被侵害之日」，一般跟离职日同一天，"
                "但如果是后来才发现被拖欠，以后者为准。"]
    return []


def _fail(reason):
    return {"ok": False, "tool": TOOL_NAME, "error": reason}


# 认 2026-03-01 / 2026/3/1 / 2026.3.1 / 2026年3月1日 几种写法
_DATE_RE = re.compile(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})")


def _parse_date(text):
    """认不出来就返回 None —— 交给调用方报"缺起算日"，不猜"""
    if not text:
        return None
    found = _DATE_RE.search(str(text))
    if not found:
        return None
    try:
        return date(int(found.group(1)), int(found.group(2)), int(found.group(3)))
    except ValueError:      # 比如 2 月 30 日这种不存在的日期
        return None


def _add_years(day, years):
    try:
        return day.replace(year=day.year + years)
    except ValueError:      # 2 月 29 日加一年没有这天，退到 2 月 28 日
        return day.replace(year=day.year + years, month=2, day=28)
