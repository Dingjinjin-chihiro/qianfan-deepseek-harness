# -*- coding: utf-8 -*-
"""
全链路自检 —— 一条命令验证「千帆 API + DeepSeek 接入」是否正常。

    set QIANFAN_API_KEY=bce-v3/ALTAK-xxx/xxx
    python selftest.py
    python selftest.py --offline        # 只检查本地文件和库，不联网

退出码：0 = 全过；1 = 有失败项。
"""

import json
import os
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = os.environ.get("QIANFAN_BASE_URL", "https://qianfan.baidubce.com/v2").rstrip("/")
ANTHROPIC = "https://qianfan.baidubce.com/anthropic"
KEY = os.environ.get("QIANFAN_API_KEY", "").strip()
OFFLINE = "--offline" in sys.argv

results = []

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code, text):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def check(name, fn, critical=True):
    try:
        detail = fn()
        results.append((True, name, detail or ""))
        print(f"  {_c('32', 'PASS')}  {name}" + (f"  [{detail}]" if detail else ""))
    except Exception as e:
        results.append((False, name, f"{type(e).__name__}: {e}"))
        print(f"  {_c('31', 'FAIL')}  {name}  -> {type(e).__name__}: {e}")
    return results[-1][0]


def post(path, payload, headers=None, base=None):
    url = (base or BASE) + path
    h = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(),
                                 headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode()), dict(r.headers)


def get(path):
    req = urllib.request.Request(BASE + path,
                                 headers={"Authorization": f"Bearer {KEY}"}, method="GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


# ---------------- 本地 ----------------

def c_env():
    assert sys.version_info >= (3, 9), f"需要 Python 3.9+，当前 {sys.version.split()[0]}"
    return sys.version.split()[0]


def c_files():
    here = os.path.dirname(os.path.abspath(__file__))
    # README.md 只是文档，缺了不影响运行，所以不列为必需
    need = ["demo.py", "usage.py", "deepseek.py", "deepseek_client.py", "selftest.py"]
    missing = [f for f in need if not os.path.exists(os.path.join(here, f))]
    assert not missing, f"缺少文件: {missing}"
    return f"{len(need)} 个"


def c_import():
    from deepseek_client import DeepSeek, Conversation, DeepSeekError  # noqa: F401
    return "deepseek_client 可导入"


# ---------------- 联网 ----------------

def c_models():
    data = get("/models")
    ids = [m["id"] for m in data.get("data", [])]
    for must in ("deepseek-v4-pro", "deepseek-v4-flash-0731"):
        assert must in ids, f"模型清单里没有 {must}（共 {len(ids)} 个）"
    return f"{len(ids)} 个模型"


def c_chat():
    body, _ = post("/chat/completions", {
        "model": "deepseek-v4-flash-0731",
        "messages": [{"role": "user", "content": "只回答两个字：收到"}]})
    msg = body["choices"][0]["message"]
    assert msg.get("content"), "content 为空（可能 max_tokens 被思考占用）"
    return f"content={msg['content'][:10]!r}"


def c_reasoning():
    body, _ = post("/chat/completions", {
        "model": "deepseek-v4-pro",
        "messages": [{"role": "user", "content": "1+1=?"}]})
    msg = body["choices"][0]["message"]
    usage = body.get("usage", {})
    assert "reasoning_content" in msg, "缺少 reasoning_content 字段（不是推理模型？）"
    return f"思考 {usage.get('completion_tokens_details', {}).get('reasoning_tokens', 0)} tok"


def c_stream():
    payload = {"model": "deepseek-v4-flash-0731", "stream": True,
               "stream_options": {"include_usage": True},
               "messages": [{"role": "user", "content": "数到3"}]}
    req = urllib.request.Request(BASE + "/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {KEY}",
                                          "Content-Type": "application/json"}, method="POST")
    got_content, got_usage = False, False
    with urllib.request.urlopen(req, timeout=120) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            try:
                d = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if d.get("usage"):
                got_usage = True
            for c in d.get("choices") or []:
                if (c.get("delta") or {}).get("content"):
                    got_content = True
    assert got_content, "流里没有正文 content"
    assert got_usage, "流里没有 usage（检查 stream_options.include_usage）"
    return "content+usage 都收到"


def c_tools():
    tools = [{"type": "function", "function": {
        "name": "add", "description": "两数相加",
        "parameters": {"type": "object",
                       "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                       "required": ["a", "b"]}}}]
    body, _ = post("/chat/completions", {
        "model": "deepseek-v4-flash-0731",
        "messages": [{"role": "user", "content": "算一下 12+30"}],
        "tools": tools, "tool_choice": "auto"})
    calls = body["choices"][0]["message"].get("tool_calls") or []
    assert calls, "没有返回 tool_calls"
    return f"调用 {calls[0]['function']['name']}"


def c_json():
    body, _ = post("/chat/completions", {
        "model": "deepseek-v4-flash-0731",
        "messages": [{"role": "user", "content": "抽取：张三 30 岁"}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "p", "schema": {"type": "object",
                                    "properties": {"name": {"type": "string"},
                                                   "age": {"type": "integer"}},
                                    "required": ["name", "age"],
                                    "additionalProperties": False}}}})
    content = body["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    assert "name" in parsed and "age" in parsed, f"JSON 不符合 schema: {parsed}"
    return json.dumps(parsed, ensure_ascii=False)


def c_embed():
    body, _ = post("/embeddings", {"model": "bge-large-zh", "input": ["测试", "向量"]})
    vecs = body["data"]
    assert len(vecs) == 2 and len(vecs[0]["embedding"]) > 0, "向量结果异常"
    return f"维度 {len(vecs[0]['embedding'])}"


def c_error_path():
    """假 key 必须报 invalid_iam_token —— 这条区分了「key 坏」和「模型名坏」"""
    req = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps({"model": "deepseek-v4-pro",
                         "messages": [{"role": "user", "content": "hi"}]}).encode(),
        headers={"Authorization": "Bearer bce-v3/ALTAK-fakefakefake/fakefakefake",
                 "Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=30)
        raise AssertionError("假 key 竟然成功了？")
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode())
        code = body.get("error", {}).get("code", "")
        assert code == "invalid_iam_token", f"预期 invalid_iam_token，实际 {code}"
        return "401 invalid_iam_token"


def c_anthropic():
    """DSH 走的就是这条通道：x-api-key + anthropic-version + anthropic-beta"""
    req = urllib.request.Request(
        ANTHROPIC + "/v1/messages",
        data=json.dumps({"model": "deepseek-v4-pro", "max_tokens": 200,
                         "thinking": {"type": "enabled"},
                         "messages": [{"role": "user", "content": "只回答两个字：收到"}]}).encode(),
        headers={"x-api-key": KEY, "anthropic-version": "2023-06-01",
                 "anthropic-beta": "files-api-2025-04-14",
                 "content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        body = json.loads(r.read().decode())
    assert body.get("type") == "message", f"不是 Anthropic 响应格式: {body.get('type')}"
    blocks = [b.get("type") for b in body.get("content", [])]
    assert "text" in blocks, f"响应里没有 text block: {blocks}"
    return f"blocks={blocks}"


def c_anthropic_tools():
    """Anthropic 工具 + tool_result 回灌（DSH 的 agent 循环依赖这个）"""
    payload = {
        "model": "deepseek-v4-pro", "max_tokens": 400,
        "thinking": {"type": "enabled"},
        "tools": [{"name": "get_weather", "description": "查天气",
                   "input_schema": {"type": "object",
                                    "properties": {"city": {"type": "string"}},
                                    "required": ["city"]}}],
        "messages": [
            {"role": "user", "content": "北京天气"},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "调工具"},
                {"type": "tool_use", "id": "call_x1", "name": "get_weather",
                 "input": {"city": "北京"}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "call_x1", "content": "晴，26℃"}]},
        ]}
    req = urllib.request.Request(
        ANTHROPIC + "/v1/messages", data=json.dumps(payload).encode(),
        headers={"x-api-key": KEY, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        body = json.loads(r.read().decode())
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    assert "26" in text, f"模型没读到工具结果: {text[:60]}"
    return "工具结果已消费"


def c_client_lib():
    from deepseek_client import DeepSeek
    ds = DeepSeek(model="deepseek-v4-flash-0731", ledger=False)
    ans = ds.chat("只回答两个字：收到")
    assert ans["content"], "客户端返回空 content"
    assert ans["request_id"], "缺少 request_id"
    return f"usage={ans['usage'].get('total_tokens')} tok"


TESTS = [
    ("环境 Python>=3.9", c_env, False),
    ("交付文件齐全", c_files, False),
    ("deepseek_client 可导入", c_import, False),
    ("GET /v2/models", c_models, True),
    ("对话（非流式）", c_chat, True),
    ("reasoning_content 字段", c_reasoning, True),
    ("流式 + include_usage", c_stream, True),
    ("工具调用", c_tools, True),
    ("结构化 JSON 输出", c_json, True),
    ("向量化", c_embed, True),
    ("错误路径（假 key）", c_error_path, True),
    ("Anthropic 兼容通道", c_anthropic, True),
    ("Anthropic 工具结果回灌", c_anthropic_tools, True),
    ("deepseek_client 客户端库", c_client_lib, True),
]


def main():
    print("=" * 62)
    print("千帆 API / DeepSeek 接入 全链路自检")
    print("=" * 62)
    if not KEY and not OFFLINE:
        print("\n缺少 QIANFAN_API_KEY 环境变量。\n"
              '  PowerShell: $env:QIANFAN_API_KEY="bce-v3/ALTAK-xxx/xxx"\n'
              "  cmd:        set QIANFAN_API_KEY=bce-v3/ALTAK-xxx/xxx\n"
              "只想检查本地文件？加 --offline 参数，跳过联网测试。")
        return 1

    if KEY:
        print(f"\nkey: {KEY[:12]}...{KEY[-6:]}   模式: {'离线（忽略联网项）' if OFFLINE else '联网'}")
    else:
        print("\nkey: 未设置   模式: 离线")

    print("\n[本地检查]")
    for name, fn, net in TESTS:
        if net:
            continue
        check(name, fn)

    if not OFFLINE:
        print("\n[联机检查]")
        for name, fn, net in TESTS:
            if not net:
                continue
            check(name, fn)

    passed = sum(1 for ok, _, _ in results if ok)
    total = len(results)
    print("\n" + "=" * 62)
    print(f"结果: {passed}/{total} 通过")
    for ok, name, detail in results:
        if not ok:
            print(f"  未通过: {name} -> {detail}")
    print("=" * 62)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
