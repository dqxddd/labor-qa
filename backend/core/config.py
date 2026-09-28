import os
from dotenv import load_dotenv

load_dotenv()

def _to_int(name, default):
    return int(os.getenv(name, str(default)))

def _to_float(name, default):
    return float(os.getenv(name, str(default)))

def _to_bool(name, default):
    """认 1/true/yes/on 这些写法，其余（包括空串）算 False"""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")

#路径配置
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CORE_DIR)
BASE_DIR = os.path.dirname(BACKEND_DIR)

DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
VECTOR_DIR = os.path.join(DATA_DIR, "vectorstore")
DB_PATH = os.path.join(DATA_DIR, "app.db")

for _d in (DATA_DIR, UPLOAD_DIR, VECTOR_DIR):
    os.makedirs(_d, exist_ok=True)

#应用配置
APP_NAME = os.getenv("APP_NAME", "劳动权益咨询问答台")
APP_ENV = os.getenv("APP_ENV", "development")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = _to_int("PORT", 8000)

#大模型配置
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TEMPERATURE = _to_float("LLM_TEMPERATURE", 0.2)
LLM_TOP_P = _to_float("LLM_TOP_P", 1.0)
LLM_MAX_TOKENS = _to_int("LLM_MAX_TOKENS", 1024)
LLM_TIMEOUT = _to_int("LLM_TIMEOUT", 60)

#有些模型把采样参数锁死，只认固定值，传别的直接 400。
#实测 2026-09-21（kimi-k3）：
#   temperature=0.6 -> 400 invalid temperature: only 1 is allowed for this model
#   top_p=0.5       -> 400 invalid top_p: only 0.95 is allowed for this model
#   max_tokens      -> 不受限，可以随便设
#换成 deepseek-chat 这类模型时表里查不到，参数就自动放开可调。
MODEL_LOCKS = {
    "kimi-k3": {"temperature": 1.0, "top_p": 0.95},
}

#向量模型配置
#默认走 api（硅基流动的 bge-m3，免费、1024 维、不装 torch）。
#把 EMBED_PROVIDER 改成 local 会退回关键词检索 —— 本地 bge-small-zh
#那条路要装 2G 多的 torch，代码里还没接（embedding.enabled() 会说明原因）。
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "api")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
EMBED_API_KEY = os.getenv("EMBED_API_KEY", "")
EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "https://api.siliconflow.cn/v1")

#切分检索配置
CHUNK_SIZE = _to_int("CHUNK_SIZE", 500)
CHUNK_OVERLAP = _to_int("CHUNK_OVERLAP", 80)

TOP_K = _to_int("TOP_K", 5)

#关键词检索用的阈值（兜底那条路）
SCORE_THRESHOLD = _to_float("SCORE_THRESHOLD", 0.35)

#阈值要分开写，两条路的分数口径完全不一样：
#  关键词检索的分数 = 查询词在片段里的覆盖率，相关的一般也就 0.2~0.4，所以 0.35
#  向量检索的分数   = 余弦相似度，相关的一般 0.5 以上，不相关的 0.3~0.5
#要是共用一个 0.35，向量这条路会把"怎么申请专利"这种库外问题也判成命中，
#拒答直接失效 —— 所以这个值不能拍脑袋，9.22 是拿真实问题标定出来的：
#
#  库里 11 个片段、18 个库内问题、20 个库外问题实测（详见报告 / scripts/calibrate_vector2.py）：
#    库内问题最低分 0.579   ← 阈值必须低于它，否则该答的答不出来
#    完全无关问题最高分 0.544（"租房押金不退怎么办"）← 阈值必须高于它，否则拒答失效
#  0.55 卡在中间，实测：库内 18/18 命中、完全无关问题 0/10 放行。
#  对照关键词检索的 0.35：库内只命中 13/18，还误放行了"怎么注销一家公司"（0.772）。
#
#⚠️ 余量只有 0.03 左右，偏紧 —— 根因是知识库太小（4 份资料 11 个片段），
#   而 4 份全是劳动法，任何劳动法问题都"话题相似"。把 6 份补充资料入库后会松一些。
VECTOR_SCORE_THRESHOLD = _to_float("VECTOR_SCORE_THRESHOLD", 0.55)

HISTORY_TURNS = _to_int("HISTORY_TURNS", 8)

#业务工具总开关。关掉之后问答链路完全不碰工具，跟以前一模一样 ——
#留这个开关是为了对照演示：报告里"开 / 关"两组跑同一批问题，看得出差别。
TOOL_ENABLED = _to_bool("TOOL_ENABLED", True)

#前端「模型参数」面板的定义。范围和默认值只在这里写一遍，
#前端拿到 /health 报上去的这份直接画滑块，想改范围不用动前端。
PARAM_SPEC = {
    "history_turns": {
        "label": "历史对话轮数", "min": 0, "max": 20, "step": 1,
        "default": HISTORY_TURNS,
        "help": "把同一会话里最近 N 轮问答带进上下文，0 表示不带历史、每次都是单轮问答。",
    },
    "temperature": {
        "label": "temperature", "min": 0.0, "max": 2.0, "step": 0.1,
        "default": LLM_TEMPERATURE,
        "help": "越高回答越发散，越低越稳。部分模型把它锁成固定值，锁了会自动置灰。",
    },
    "top_p": {
        "label": "top-p", "min": 0.05, "max": 1.0, "step": 0.05,
        "default": LLM_TOP_P,
        "help": "按累计概率截断候选词，一般跟 temperature 二选一调。",
    },
    "max_tokens": {
        "label": "max-tokens", "min": 128, "max": 4096, "step": 128,
        "default": LLM_MAX_TOKENS,
        "help": "单次回答最长生成多少 token，设小了回答会被截断。",
    },
}

if __name__ == "__main__":
    print(APP_NAME)
    print(HOST)
    print(PORT)
    print(LLM_API_KEY)
    print(LLM_BASE_URL)
    print(LLM_MODEL)
    print(LLM_TEMPERATURE)
    print(LLM_TIMEOUT)
