"""大模型调用。走 OpenAI 兼容的接口，所以换供应商只改 .env 里的地址和模型名。

这块分三层：

1. resolve_params()  —— 参数自适应。前端滑块传进来的值先在这里核对一遍：
   有的模型把参数锁死了（实测 kimi-k3 只认 temperature=1、top_p=0.95），
   传别的值直接 400，所以这里按 MODEL_LOCKS 把值校正到合法范围，
   并且把"哪些值被改过、为什么"一并返回，前端照实展示给用户。

2. chat()    —— 同步，一次性拿回整段回答。

3. stream()  —— 流式，一段一段 yield，前端边收边显示。

9.22 傍晚加了第四层：
4. chat_message() —— 和 chat() 一样发请求，但把整条 message 原样返回，
   用来读模型给的 tool_calls（业务工具那套）。chat() 也改成走它，
   免得两条路各写一份请求代码。
"""

import json

import httpx

from backend.core.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_TIMEOUT,
    LLM_TOP_P,
    MODEL_LOCKS,
)

#参数兜底的取值范围，超出就夹回来，免得白跑一次请求换回一个 400
TEMPERATURE_RANGE = (0.0, 2.0)
TOP_P_RANGE = (0.01, 1.0)
MAX_TOKENS_RANGE = (1, 8192)


class LLMError(Exception):
    pass


def model_locks(model=None):
    """当前模型锁死了哪些参数，返回 {参数名: 固定值}；没锁就是空字典"""
    return dict(MODEL_LOCKS.get((model or LLM_MODEL or "").lower(), {}))


def resolve_params(options=None):
    """把前端传来的参数规整成这次请求真正会用的值。

    返回 (params, notes)：
      params —— 实际会发出去的那几个值
      notes  —— 哪些值被调整过、为什么，直接给用户看

    只有"用户显式调过"的参数才会记进 notes。走默认值的参数被模型锁住时
    不出提示 —— 用户没动它，说"你设的 1.0 发不出去"只会让人莫名其妙。
    """
    options = options or {}
    model = LLM_MODEL
    locks = model_locks(model)
    notes = []

    def read(name, fallback, caster):
        """取参数。注意不能用 `or fallback` —— 0.0 是合法取值但布尔上是假"""
        value = options.get(name)
        return fallback if value is None else caster(value)

    temperature = read("temperature", LLM_TEMPERATURE, float)
    top_p = read("top_p", LLM_TOP_P, float)
    max_tokens = read("max_tokens", LLM_MAX_TOKENS, int)

    #一、模型锁死的参数，一律用它的固定值
    for name, value, current in (("temperature", locks.get("temperature"), temperature),
                                 ("top_p", locks.get("top_p"), top_p)):
        if value is None:
            continue
        if name in options and abs(current - value) > 1e-6:
            notes.append("%s 被 %s 固定在 %s，你设的 %s 发不出去 —— 已按固定值发送"
                         % (name, model, value, current))
    temperature = locks.get("temperature", temperature)
    top_p = locks.get("top_p", top_p)

    #二、范围兜底，免得白跑一次请求换回一个 400
    if temperature < TEMPERATURE_RANGE[0] or temperature > TEMPERATURE_RANGE[1]:
        temperature = min(max(temperature, TEMPERATURE_RANGE[0]), TEMPERATURE_RANGE[1])
        notes.append("temperature 只支持 0~2，已按 %.1f 发送" % temperature)
    if top_p < TOP_P_RANGE[0] or top_p > TOP_P_RANGE[1]:
        top_p = min(max(top_p, TOP_P_RANGE[0]), TOP_P_RANGE[1])
        notes.append("top-p 只支持 0.01~1，已按 %.2f 发送" % top_p)
    if max_tokens < MAX_TOKENS_RANGE[0] or max_tokens > MAX_TOKENS_RANGE[1]:
        max_tokens = min(max(max_tokens, MAX_TOKENS_RANGE[0]), MAX_TOKENS_RANGE[1])
        notes.append("max-tokens 只支持 1~8192，已按 %d 发送" % max_tokens)

    params = {
        "model": model,
        "temperature": round(float(temperature), 2),
        "top_p": round(float(top_p), 2),
        "max_tokens": int(max_tokens),
    }
    return params, notes


def _url():
    return LLM_BASE_URL.rstrip("/") + "/chat/completions"


def _headers():
    if not LLM_API_KEY:
        raise LLMError("没有配置 LLM_API_KEY，先把 .env 里的 key 填上")
    return {
        "Authorization": "Bearer %s" % LLM_API_KEY,
        "Content-Type": "application/json",
    }


def _body(messages, params, stream=False, tools=None, tool_choice=None):
    body = {
        "model": params.get("model") or LLM_MODEL,
        "messages": messages,
        "temperature": params["temperature"],
        "top_p": params["top_p"],
        "max_tokens": params["max_tokens"],
        "stream": stream,
    }
    if tools:
        # 只在需要算期限的那一轮才带 tools —— 别的问题连这个字段都不出现，
        # 模型没有任何机会"顺手"调一个不该调的工具
        body["tools"] = tools
        body["tool_choice"] = tool_choice or "auto"
    return body


def chat_message(messages, params=None, tools=None, tool_choice=None):
    """发一次请求，把整条 message 原样返回 —— 需要看 tool_calls 时用它。

    注意：模型决定调工具时 content 往往是空的，别拿它当回答。
    tool_choice 传 "required" 表示强制它必须调（实测 DeepSeek-V3.1 在 "auto"
    下不肯调，所以业务工具那条路走的是 required）。
    """
    if params is None:
        params, _ = resolve_params(None)

    try:
        resp = httpx.post(_url(), headers=_headers(),
                          json=_body(messages, params, tools=tools,
                                     tool_choice=tool_choice),
                          timeout=LLM_TIMEOUT)
    except httpx.HTTPError as e:
        raise LLMError("请求大模型失败：%s" % e)

    if resp.status_code != 200:
        raise LLMError("大模型返回 %s：%s" % (resp.status_code, resp.text[:200]))

    data = resp.json()
    try:
        return data["choices"][0]["message"]
    except (KeyError, IndexError):
        raise LLMError("大模型返回的结构看不懂：%s" % str(data)[:200])


def chat(messages, params=None):
    """同步调用，一次性拿回整段回答。params 用 resolve_params() 先算好"""
    return chat_message(messages, params).get("content") or ""


def stream(messages, params=None):
    """流式调用，逐段 yield 文本。

    注意：这是个生成器 —— 报错要等你开始取用才会抛出来，
    所以调用方必须把 for 循环包在 try / except LLMError 里。
    """
    if params is None:
        params, _ = resolve_params(None)

    try:
        with httpx.stream("POST", _url(), headers=_headers(),
                          json=_body(messages, params, stream=True),
                          timeout=LLM_TIMEOUT) as resp:
            if resp.status_code != 200:
                detail = resp.read().decode("utf-8", "ignore")
                raise LLMError("大模型返回 %s：%s" % (resp.status_code, detail[:200]))

            # 服务端按 SSE 推：一行一个 data: {...}，最后跟一个 data: [DONE]
            for line in resp.iter_lines():
                if not line or not line.startswith("data:"):
                    continue                      # 空行、以及 ": keep-alive" 这种注释行
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                text = _delta_text(chunk)
                if text:
                    yield text
    except httpx.HTTPError as e:
        raise LLMError("请求大模型失败：%s" % e)


def _delta_text(chunk):
    """从一条 SSE 数据里取出增量文本；取不到（比如只带 role 的首包）就返回空串"""
    try:
        obj = json.loads(chunk)
        return obj["choices"][0]["delta"].get("content") or ""
    except (ValueError, KeyError, IndexError, TypeError):
        return ""
