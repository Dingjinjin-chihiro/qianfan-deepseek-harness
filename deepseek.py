# -*- coding: utf-8 -*-
"""
DeepSeek 命令行入口（走千帆，你的 key 直接可用）。

常用：
    python deepseek.py "用一句话解释量子纠缠"
    python deepseek.py -i                              # 多轮对话，记得上下文
    python deepseek.py --stream "写一首五言绝句"        # 边说边出
    python deepseek.py --reasoning "9.11 和 9.9 谁大"   # 顺便看思考过程
    python deepseek.py --tools "现在几点，另外 37*89 等于多少"
    python deepseek.py --json "从『张三 30 岁，住在杭州』抽取字段"
    python deepseek.py --list                          # 看可用 DeepSeek 模型

    python deepseek.py --official "你好"               # 改用 DeepSeek 官方 key（需 DEEPSEEK_API_KEY）
"""

import datetime
import json
import os
import re
import sys

from deepseek_client import PROVIDERS, Conversation, DeepSeek, DeepSeekError

# 输入是从管道来的（比如 `"问题" | python deepseek.py -i`）时按 UTF-8 读，
# 否则 Windows 会拿 GBK 解出乱码 / 半个字符。
if not sys.stdin.isatty():
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---- 颜色：不是终端就自动关掉，避免日志里一堆 \033[90m ----
if os.name == "nt":
    os.system("")  # 让 cmd.exe 打开 VT 转义支持

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(code, text):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else str(text)


DIM = lambda t: c("90", t)
GREEN = lambda t: c("32", t)
CYAN = lambda t: c("36", t)
RED = lambda t: c("31", t)

EXIT_HINT = "输入 /exit 退出、/clear 清空、/model <名字> 换模型、/reasoning 开关思考过程"


def fmt_usage(u):
    if not u:
        return ""
    det_in = u.get("prompt_tokens_details") or {}
    det_out = u.get("completion_tokens_details") or {}
    parts = [f"输入 {u.get('prompt_tokens', 0)}", f"输出 {u.get('completion_tokens', 0)}"]
    if det_in.get("cached_tokens"):
        parts.append(f"命中缓存 {det_in['cached_tokens']}")
    if det_out.get("reasoning_tokens"):
        parts.append(f"其中思考 {det_out['reasoning_tokens']}")
    return " · ".join(parts)


def print_answer(ans, show_reasoning=False):
    if show_reasoning and ans.get("reasoning"):
        print(DIM("[思考过程]\n" + ans["reasoning"]))
    print(ans["content"])
    u = fmt_usage(ans.get("usage"))
    if u:
        print(DIM(f"[{u} · request_id {ans.get('request_id')}]"))


# ---------------- 工具演示（真调，不是摆设） ----------------

def tool_get_current_time(timezone="Asia/Shanghai"):
    now = datetime.datetime.now()
    return {"time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "weekday": now.strftime("%A"), "timezone": timezone}


def tool_calculate(expression="0"):
    if not re.fullmatch(r"[0-9+\-*/(). %]+", str(expression)):
        return {"error": "只支持数字和 + - * / ( )"}
    try:
        return {"expression": expression, "result": eval(expression, {"__builtins__": {}}, {})}
    except Exception as e:
        return {"error": str(e)}


TOOLS = [
    {"type": "function", "function": {
        "name": "get_current_time", "description": "获取当前日期和时间",
        "parameters": {"type": "object", "properties": {
            "timezone": {"type": "string", "description": "时区，默认 Asia/Shanghai"}}}}},
    {"type": "function", "function": {
        "name": "calculate", "description": "计算数学表达式。任何算术都必须用它，不要心算",
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "例如 37*89"}},
            "required": ["expression"]}}},
]
HANDLERS = {"get_current_time": tool_get_current_time, "calculate": tool_calculate}

PERSON_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "age": {"type": "integer"},
                   "city": {"type": "string"}},
    "required": ["name", "age"],
    "additionalProperties": False,
}


def interactive(client):
    print(DIM(f"已连接 {client.provider} / {client.model}。{EXIT_HINT}\n"))
    show_reasoning = False
    conv = Conversation(client, system="你是一个简洁、准确的中文助手。")

    while True:
        try:
            text = input(CYAN("你 > ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue

        if text.startswith("/"):
            cmd, _, arg = text[1:].partition(" ")
            if cmd in ("exit", "quit", "q"):
                break
            elif cmd == "clear":
                conv.reset()
                print(DIM("已清空上下文"))
            elif cmd == "model":
                if arg:
                    client.model = arg
                print(DIM(f"当前模型：{client.model}"))
            elif cmd == "reasoning":
                show_reasoning = not show_reasoning
                print(DIM(f"思考过程：{'开' if show_reasoning else '关'}"))
            elif cmd == "help":
                print(DIM(EXIT_HINT))
            else:
                print(DIM(f"未知命令 /{cmd}"))
            continue

        try:
            print(GREEN("DS > "), end="", flush=True)

            def on_delta(ev):
                if ev["type"] == "content":
                    print(ev["text"], end="", flush=True)
                elif ev["type"] == "reasoning" and show_reasoning:
                    print(DIM(ev["text"]), end="", flush=True)

            ans = conv.say(text, stream=True, on_delta=on_delta)
            u = fmt_usage(ans.get("usage"))
            print("\n" + (DIM(f"[{u}]") if u else ""))
        except DeepSeekError as e:
            print("\n" + RED(f"请求失败：{e}"))


def main(argv):
    args = list(argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return

    provider = "official" if "--official" in args else "qianfan"
    args = [a for a in args if a != "--official"]
    conf = PROVIDERS[provider]

    if "--list" in args:
        print(f"{provider} 可用 DeepSeek 模型：\n")
        for name, desc in conf["models"].items():
            print(f"  {name:28} {desc}")
        return

    model = conf["default_model"]
    if "--model" in args:
        i = args.index("--model")
        try:
            model = args[i + 1]
            del args[i:i + 2]
        except IndexError:
            sys.exit("--model 后面要跟模型名")

    for f in ("--stream", "--reasoning", "--tools", "--json"):
        args = [a for a in args if a != f]

    try:
        client = DeepSeek(provider=provider, model=model)
    except ValueError as e:
        sys.exit(str(e))

    if "-i" in argv or "--chat" in argv:
        interactive(client)
        return

    prompt = " ".join(args).strip() or "用一句话介绍你自己"
    show_r = "--reasoning" in argv

    try:
        if "--tools" in argv:
            print(DIM(f"[{client.provider} / {client.model}]\n"))

            def on_tool(name, a, r):
                print(DIM(f"  ↳ {name}({json.dumps(a, ensure_ascii=False)}) "
                          f"→ {json.dumps(r, ensure_ascii=False)}"))

            ans, _, _ = client.chat_with_tools(prompt, TOOLS, HANDLERS,
                                               model=client.model, on_tool=on_tool)
            print("\n" + ans["content"])
            u = fmt_usage(ans.get("usage"))
            if u:
                print("\n" + DIM(f"[{u}]"))
            return

        if "--json" in argv:
            ans = client.chat(prompt, json_schema=PERSON_SCHEMA)
            try:
                print(json.dumps(json.loads(ans["content"]), ensure_ascii=False, indent=2))
            except json.JSONDecodeError:
                print(ans["content"])
            return

        if "--stream" in argv:
            for ev in client.stream(prompt):
                if ev["type"] == "reasoning" and show_r:
                    print(DIM(ev["text"]), end="", flush=True)
                elif ev["type"] == "content":
                    print(ev["text"], end="", flush=True)
                elif ev["type"] == "usage":
                    print("\n\n" + DIM(f"[{fmt_usage(ev['usage'])}]"))
            print()
            return

        print_answer(client.chat(prompt), show_reasoning=show_r)

    except DeepSeekError as e:
        sys.exit(RED(f"请求失败：{e}"))


if __name__ == "__main__":
    main(sys.argv[1:])
