# -*- coding: utf-8 -*-
"""
百度千帆（Qianfan）v2 API 最小可用示例 —— 纯标准库，无需 pip install。

用法：
    set QIANFAN_API_KEY=bce-v3/ALTAK-xxxxx/xxxxx      # Windows cmd
    $env:QIANFAN_API_KEY="bce-v3/ALTAK-xxxxx/xxxxx"    # PowerShell
    python demo.py

    python demo.py "写一首五言绝句"
    python demo.py --model deepseek-v4-pro "解释一下什么是 RAG"
    python demo.py --models                            # 列出账号可用的模型
"""

import json
import os
import sys
import urllib.request
import urllib.error

BASE_URL = os.environ.get("QIANFAN_BASE_URL", "https://qianfan.baidubce.com/v2")
API_KEY = os.environ.get("QIANFAN_API_KEY", "").strip()

DEFAULT_MODEL = "ernie-5.1"          # 你也可以换成 deepseek-v4-pro / glm-5.3 等
EMBED_MODEL = "bge-large-zh"


def _headers():
    if not API_KEY:
        sys.exit(
            "缺少 API Key。请先设置环境变量 QIANFAN_API_KEY，例如：\n"
            '  PowerShell: $env:QIANFAN_API_KEY="bce-v3/ALTAK-xxx/xxx"\n'
            '  cmd:        set QIANFAN_API_KEY=bce-v3/ALTAK-xxx/xxx'
        )
    return {
        # 注意：Bearer 后面直接跟整串 bce-v3/ALTAK-.../... ，不要再套 AK/SK 签名
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


def _post(path, payload, stream=False):
    url = BASE_URL + path
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=_headers(), method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        # 千帆的报错体也是 JSON，直接打印出来方便排查
        detail = e.read().decode("utf-8", "replace")
        sys.exit(f"HTTP {e.code}\n{detail}")
    if stream:
        return resp                      # 交给调用方逐行读 SSE
    return json.loads(resp.read().decode("utf-8"))


def chat(prompt, model=DEFAULT_MODEL, system=None, **kwargs):
    """一次性返回（非流式）"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {"model": model, "messages": messages, **kwargs}
    data = _post("/chat/completions", payload)

    msg = data["choices"][0]["message"]
    return msg.get("content", ""), data


def chat_stream(prompt, model=DEFAULT_MODEL, system=None, **kwargs):
    """流式返回，逐 token 打印"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {"model": model, "messages": messages, "stream": True, **kwargs}
    resp = _post("/chat/completions", payload, stream=True)

    answer = []
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if chunk in ("", "[DONE]"):
            if chunk == "[DONE]":
                break
            continue
        try:
            delta = json.loads(chunk)["choices"][0]["delta"]
        except (KeyError, IndexError, json.JSONDecodeError):
            continue
        piece = delta.get("content") or ""
        if piece:
            answer.append(piece)
            print(piece, end="", flush=True)
    print()
    return "".join(answer)


def embed(texts, model=EMBED_MODEL):
    """文本向量化"""
    data = _post("/embeddings", {"model": model, "input": texts})
    return [item["embedding"] for item in data["data"]], data


def list_models():
    req = urllib.request.Request(BASE_URL + "/models", headers=_headers(), method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    rows = data.get("data", [])
    print(f"{'model':26} {'type':12} {'ctx':>10}  owner")
    print("-" * 70)
    for m in sorted(rows, key=lambda x: (x.get("owned_by", ""), x.get("id", ""))):
        print(f"{m.get('id', ''):26} {m.get('type', ''):12} "
              f"{str(m.get('context_length') or '-'):>10}  {m.get('owned_by', '')}")
    print(f"\n共 {len(rows)} 个模型")


def main():
    args = sys.argv[1:]

    if "--models" in args:
        list_models()
        return

    model = DEFAULT_MODEL
    if "--model" in args:
        i = args.index("--model")
        try:
            model = args[i + 1]
            del args[i:i + 2]
        except IndexError:
            sys.exit("--model 后面要跟模型名，例如 --model deepseek-v4-pro")

    prompt = " ".join(args) or "用一句话介绍你自己"

    print(f"--- 非流式（model={model}）---")
    text, data = chat(prompt, model=model, system="你是一个简洁的中文助手")
    print(text)
    print("usage:", json.dumps(data.get("usage"), ensure_ascii=False))

    print(f"\n--- 流式（model={model}）---")
    chat_stream("数到 5，只输出数字", model=model)

    print("\n--- 向量化 ---")
    vecs, data = embed(["千帆平台", "大模型 API"])
    print(f"条数: {len(vecs)}  维度: {len(vecs[0])}  "
          f"usage: {data.get('usage')}  首向量前 5 位: {vecs[0][:5]}")


if __name__ == "__main__":
    main()
