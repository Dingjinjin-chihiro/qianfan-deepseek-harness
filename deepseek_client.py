# -*- coding: utf-8 -*-
"""
DeepSeek 接入层 —— 双通道：千帆（默认）/ DeepSeek 官方 API。

为什么默认走千帆：你手里已经有千帆的 key，不用再申请；模型是一样的
（deepseek-v4-pro / v4-flash / v4.1-flash）。等哪天办了官方 key，
把 provider 换成 "official" 即可，业务代码一行不用改。

用法（库）：
    from deepseek_client import DeepSeek, Conversation

    ds = DeepSeek()                       # 默认千帆 + deepseek-v4-pro
    print(ds.chat("你好")["content"])

    conv = Conversation(ds)
    conv.say("我叫丁丁")
    conv.say("我叫什么？")                 # 记住上下文

用法（命令行）：见 deepseek.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

try:  # Windows 控制台默认 GBK，模型输出里的 emoji 会炸，这里强制 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage_ledger.jsonl")

PROVIDERS = {
    "qianfan": {
        "base_url": "https://qianfan.baidubce.com/v2",
        "key_env": "QIANFAN_API_KEY",
        "default_model": "deepseek-v4-pro",
        "models": {
            "deepseek-v4-pro": "旗舰，144 万上下文，最强推理",
            "deepseek-v4-pro-0813": "同一代快照版，便宜 2.7 倍",
            "deepseek-v4-flash-0731": "高速版，便宜 8 倍，日常够用",
            "deepseek-v4.1-flash-1017": "多模态 + 最便宜",
        },
    },
    "official": {
        "base_url": "https://api.deepseek.com/v1",
        "key_env": "DEEPSEEK_API_KEY",
        "default_model": "deepseek-chat",
        "models": {
            "deepseek-chat": "官方通用对话模型",
            "deepseek-reasoner": "官方推理模型",
        },
    },
}


class DeepSeekError(RuntimeError):
    def __init__(self, status, code, message, raw=""):
        self.status, self.code, self.message, self.raw = status, code, message, raw
        super().__init__(f"HTTP {status} [{code}] {message}")


class DeepSeek:
    """一个够用的 DeepSeek 客户端：对话 / 流式 / 工具调用 / JSON 输出 / 用量记账。"""

    def __init__(self, provider="qianfan", api_key=None, model=None,
                 ledger=True, timeout=180, base_url=None, api_key_env=None):
        if provider not in PROVIDERS:
            raise ValueError(f"provider 只能是 {list(PROVIDERS)}")
        self.provider = provider
        conf = PROVIDERS[provider]

        self.api_key = (api_key or os.environ.get(api_key_env or conf["key_env"], "")).strip()

        if base_url:
            self.base_url = base_url
        elif provider == "qianfan":
            self.base_url = os.environ.get("QIANFAN_BASE_URL") or conf["base_url"]
        else:
            self.base_url = conf["base_url"]
        self.base_url = self.base_url.rstrip("/")
        self.model = model or conf["default_model"]
        self.ledger = ledger
        self.timeout = timeout
        self._pricing = None

        if not self.api_key:
            raise ValueError(
                f"缺少 API Key：请设置环境变量 {conf['key_env']}，或传 api_key=..."
            )

    # ---------- 底层 ----------

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _open(self, payload):
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(), method="POST")
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                err = json.loads(raw)["error"]
                raise DeepSeekError(e.code, err.get("code", ""), err.get("message", ""), raw)
            except (json.JSONDecodeError, KeyError, TypeError):
                raise DeepSeekError(e.code, "unknown", raw[:200], raw)

    # ---------- 对话 ----------

    def chat(self, messages, model=None, tools=None, tool_choice=None,
             json_schema=None, temperature=None, max_tokens=None, system=None):
        """非流式。messages 可以是 str（自动包成单轮）。"""
        msgs = self._normalize(messages, system)
        payload = {"model": model or self.model, "messages": msgs}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        if json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": json_schema},
            }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens:
            payload["max_tokens"] = max_tokens

        with self._open(payload) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            headers = dict(resp.headers)

        msg = (body.get("choices") or [{}])[0].get("message", {}) or {}
        answer = {
            "content": msg.get("content") or "",
            "reasoning": msg.get("reasoning_content") or "",
            "tool_calls": msg.get("tool_calls") or [],
            "finish_reason": (body.get("choices") or [{}])[0].get("finish_reason"),
            "usage": body.get("usage") or {},
            "model": body.get("model", payload["model"]),
            "request_id": headers.get("X-Request-ID") or body.get("id"),
            "raw": body,
        }
        if self.ledger:
            self._record(answer, msgs)
        return answer

    def stream(self, messages, model=None, system=None, tools=None,
               temperature=None, max_tokens=None):
        """流式。逐块 yield {"type": "reasoning"|"content"|"usage"|"done", ...}"""
        msgs = self._normalize(messages, system)
        payload = {
            "model": model or self.model, "messages": msgs, "stream": True,
            # 不显式开这个，流里一个 usage 都拿不到
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens:
            payload["max_tokens"] = max_tokens

        answer = {"content": "", "reasoning": "", "tool_calls": [], "usage": {}}
        with self._open(payload) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    data = json.loads(chunk)
                except json.JSONDecodeError:
                    continue

                if data.get("usage"):
                    answer["usage"] = data["usage"]
                    yield {"type": "usage", "usage": data["usage"]}

                for choice in data.get("choices") or []:
                    delta = choice.get("delta") or {}
                    # 推理模型先吐思维链，再吐正文，必须分开收
                    if delta.get("reasoning_content"):
                        answer["reasoning"] += delta["reasoning_content"]
                        yield {"type": "reasoning", "text": delta["reasoning_content"]}
                    if delta.get("content"):
                        answer["content"] += delta["content"]
                        yield {"type": "content", "text": delta["content"]}
                    if delta.get("tool_calls"):
                        answer["tool_calls"].extend(delta["tool_calls"])

        if self.ledger:
            self._record(answer, msgs)
        yield {"type": "done", "answer": answer}

    # ---------- 工具调用 ----------

    def chat_with_tools(self, messages, tools, handlers, model=None,
                        max_rounds=5, system=None, on_tool=None):
        """完整工具循环：模型要调工具 → 你执行 → 结果回灌 → 模型总结。

        tools    : OpenAI 格式的工具定义列表
        handlers : {"工具名": 可调用对象}，参数以 dict 传入
        """
        msgs = self._normalize(messages, system)
        trace = []
        for _ in range(max_rounds):
            ans = self.chat(msgs, model=model, tools=tools)
            if not ans["tool_calls"]:
                return ans, msgs, trace

            # 把 assistant 的工具请求原样放回历史，否则下一次调用会 400
            msgs.append({
                "role": "assistant",
                "content": ans["content"] or "",
                "tool_calls": ans["tool_calls"],
            })
            for call in ans["tool_calls"]:
                fn = call.get("function") or {}
                name = fn.get("name")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                handler = handlers.get(name)
                if handler is None:
                    result = {"error": f"没有名为 {name} 的工具"}
                else:
                    try:
                        result = handler(**args)
                    except Exception as e:  # 工具抛错也要回灌，别让整条链断掉
                        result = {"error": f"{type(e).__name__}: {e}"}
                trace.append({"tool": name, "args": args, "result": result})
                if on_tool:
                    on_tool(name, args, result)
                msgs.append({
                    "role": "tool",
                    "tool_call_id": call.get("id") or f"call_{len(msgs)}",
                    "content": json.dumps(result, ensure_ascii=False),
                })

        ans = self.chat(msgs, model=model)
        return ans, msgs, trace

    # ---------- 内部 ----------

    @staticmethod
    def _normalize(messages, system):
        if isinstance(messages, str):
            msgs = [{"role": "user", "content": _clean(messages)}]
        else:
            msgs = []
            for m in messages:
                m = dict(m)
                m["content"] = _clean(m.get("content", ""))
                msgs.append(m)
        if system:
            msgs = [{"role": "system", "content": _clean(system)}] + msgs
        return msgs

    def _prices(self):
        """千帆能从 /v2/models 拿实时价，官方 API 拿不到就返回 None。"""
        if self.provider != "qianfan":
            return None
        if self._pricing is not None:
            return self._pricing
        try:
            req = urllib.request.Request(self.base_url + "/models",
                                         headers=self._headers(), method="GET")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            table = {}
            for m in data.get("data", []):
                p = m.get("pricing") or {}
                table[m["id"]] = (_num(p.get("prompt")), _num(p.get("completion")),
                                  _num(p.get("cache")))
            self._pricing = table
        except Exception:
            self._pricing = {}
        return self._pricing

    def _record(self, answer, msgs):
        usage = answer.get("usage") or {}
        det_in = usage.get("prompt_tokens_details") or {}
        det_out = usage.get("completion_tokens_details") or {}
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        cached = det_in.get("cached_tokens", 0)
        rt = det_out.get("reasoning_tokens", 0)

        cost = None
        table = self._prices()
        if table and answer.get("model") in table:
            pin, pout, pcache = table[answer["model"]]
            if pin is not None:
                cache_hit = min(cached or 0, pt)
                cost = ((pt - cache_hit) * pin + cache_hit * (pcache or pin)
                        + ct * (pout if pout is not None else pin)) / 1000

        first_user = next((m.get("content") for m in msgs if m.get("role") == "user"), "")
        if isinstance(first_user, list):  # 多模态消息可能是数组
            first_user = str(first_user)[:60]

        entry = {
            "ts": int(time.time()),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "model": answer.get("model", self.model),
            "provider": self.provider,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "cached_tokens": cached,
            "reasoning_tokens": rt,
            "total_tokens": usage.get("total_tokens", pt + ct),
            "cost_est": cost,
            "request_id": answer.get("request_id"),
            "prompt": (first_user or "")[:60],
        }
        try:
            with open(LEDGER, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # 记账失败不能影响主流程


def _clean(text):
    """去掉孤立的代理字符（Unicode 区间 U+D800 到 U+DFFF）。

    Windows 下把中文从别的程序管道喂进来时，很容易出现这种半个字符，
    json.dumps 会直接抛 UnicodeEncodeError: surrogates not allowed。
    """
    if not isinstance(text, str):
        return text
    try:
        text.encode("utf-8")
        return text
    except UnicodeEncodeError:
        return text.encode("utf-8", "ignore").decode("utf-8")


def _num(v):
    """价格字段可能是 '0.008'、0.008 或 [{up_to,price},...] 分档"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    if isinstance(v, list) and v:
        prices = [x.get("price") for x in v if isinstance(x, dict) and x.get("price") is not None]
        return float(prices[-1]) if prices else None
    return None


class Conversation:
    """多轮对话，自动维护历史。"""

    def __init__(self, client=None, system=None, model=None):
        self.client = client or DeepSeek(model=model)
        self.system = system
        self.messages = []
        if system:
            self.messages.append({"role": "system", "content": system})

    def say(self, text, model=None, stream=False, on_delta=None):
        self.messages.append({"role": "user", "content": text})
        if stream:
            answer = {"content": "", "reasoning": "", "usage": {}}
            for ev in self.client.stream(self.messages, model=model):
                if ev["type"] in ("content", "reasoning") and on_delta:
                    on_delta(ev)
                if ev["type"] == "done":
                    answer = ev["answer"]
            self.messages.append({"role": "assistant", "content": answer["content"]})
            return answer

        answer = self.client.chat(self.messages, model=model)
        self.messages.append({"role": "assistant", "content": answer["content"]})
        return answer

    def reset(self, keep_system=True):
        self.messages = [m for m in self.messages if m["role"] == "system"] if keep_system else []
