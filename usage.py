# -*- coding: utf-8 -*-
"""
千帆用量自助统计 —— 纯标准库，无需 pip install。

背景：千帆 v2 模型网关**没有**用量查询接口（/v2/usage 等全部 404），
      所以「实时用量」只有两个来源：
        1) 控制台账单（计费口径，最准）
        2) 每次响应里的 usage 字段 + X-Ratelimit-* 响应头（本脚本做的事）

用法：
    set QIANFAN_API_KEY=bce-v3/ALTAK-xxx/xxx     # 或 PowerShell: $env:QIANFAN_API_KEY="..."

    python usage.py ask "你好"                       # 发一次请求并记账
    python usage.py ask "写首诗" --model deepseek-v4-pro
    python usage.py report                           # 汇总：按模型 / 按天 / 总费用
    python usage.py report --days 7
    python usage.py limits --model glm-5.3-flash     # 看当前限流窗口还剩多少
    python usage.py clear                            # 清空本地账本
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE_URL = os.environ.get("QIANFAN_BASE_URL", "https://qianfan.baidubce.com/v2")
API_KEY = os.environ.get("QIANFAN_API_KEY", "").strip()
LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage_ledger.jsonl")


def headers():
    if not API_KEY:
        sys.exit('缺少 API Key，请先设置环境变量 QIANFAN_API_KEY')
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def request_json(path, payload=None, method="POST"):
    """返回 (json_body, response_headers)"""
    url = BASE_URL + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers(), method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}\n{e.read().decode('utf-8', 'replace')}")
    body = json.loads(resp.read().decode("utf-8"))
    return body, dict(resp.headers)


def get_pricing():
    """从 /v2/models 拿价格（元/千 tokens）。返回 {model: (in, out)}"""
    models, _ = request_json("/models", method="GET")
    price = {}
    for m in models.get("data", []):
        p = m.get("pricing") or {}
        pin, pout = _num(p.get("prompt")), _num(p.get("completion"))
        if pin is not None:
            price[m["id"]] = (pin, pout if pout is not None else pin)
    return price


def _num(v):
    """价格字段可能是 '0.008' 也可能是 [{up_to:32,price:0.004}, ...] 分档"""
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
        # 取最后（最高）档，偏保守：宁可高估
        prices = [x.get("price") for x in v if isinstance(x, dict) and x.get("price") is not None]
        return float(prices[-1]) if prices else None
    return None


def estimate_cost(model, prompt_tokens, completion_tokens, pricing=None):
    pricing = pricing or get_pricing()
    pin, pout = pricing.get(model, (None, None))
    if pin is None:
        return None
    return prompt_tokens / 1000 * pin + completion_tokens / 1000 * pout


def record(entry):
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def cmd_ask(args):
    model = "ernie-5.1"
    if "--model" in args:
        i = args.index("--model")
        model = args[i + 1]
        del args[i:i + 2]
    prompt = " ".join(args) or "你好"

    payload = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    body, hdrs = request_json("/chat/completions", payload)

    usage = body.get("usage") or {}
    det = usage.get("completion_tokens_details") or {}
    pt = usage.get("prompt_tokens", 0)
    ct = usage.get("completion_tokens", 0)
    rt = det.get("reasoning_tokens", 0)
    cost = estimate_cost(model, pt, ct)

    entry = {
        "ts": int(time.time()),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": model,
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "reasoning_tokens": rt,
        "total_tokens": usage.get("total_tokens", pt + ct),
        "cost_est": cost,
        "request_id": hdrs.get("X-Request-ID") or body.get("id"),
        "prompt": prompt[:60],
    }
    record(entry)

    content = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
    print("--- 回答 ---")
    print(content)
    print("\n--- 本次用量 ---")
    print(f"model            : {model}")
    print(f"prompt_tokens    : {pt}")
    print(f"completion_tokens: {ct}  (其中思考 reasoning: {rt})")
    print(f"total_tokens     : {entry['total_tokens']}")
    print(f"估算费用         : {('%.6f 元' % cost) if cost is not None else '价格未知'}")
    print(f"request_id       : {entry['request_id']}")
    print(f"已写入账本       : {LEDGER}")


def cmd_report(args):
    days = None
    if "--days" in args:
        i = args.index("--days")
        days = int(args[i + 1])
    if not os.path.exists(LEDGER):
        sys.exit("还没有账本，先跑一次：python usage.py ask \"你好\"")

    since = time.time() - days * 86400 if days else 0
    rows = []
    with open(LEDGER, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("ts", 0) >= since:
                rows.append(e)

    if not rows:
        sys.exit("该时间段内没有记录")

    # 按模型
    by_model = {}
    # 按天
    by_day = {}
    for e in rows:
        m = by_model.setdefault(e["model"], {"n": 0, "pt": 0, "ct": 0, "rt": 0, "cost": 0.0})
        m["n"] += 1
        m["pt"] += e.get("prompt_tokens", 0)
        m["ct"] += e.get("completion_tokens", 0)
        m["rt"] += e.get("reasoning_tokens", 0)
        m["cost"] += e.get("cost_est") or 0

        d = by_day.setdefault(e["time"][:10], {"n": 0, "tok": 0, "cost": 0.0})
        d["n"] += 1
        d["tok"] += e.get("total_tokens", 0)
        d["cost"] += e.get("cost_est") or 0

    print(f"账本: {LEDGER}")
    print(f"范围: {'最近 %d 天' % days if days else '全部'}  共 {len(rows)} 次调用\n")

    print(f"{'模型':26} {'次数':>5} {'输入tok':>10} {'输出tok':>10} {'思考tok':>9} {'费用(元)':>10}")
    print("-" * 76)
    for name, v in sorted(by_model.items(), key=lambda x: -x[1]["cost"]):
        print(f"{name:26} {v['n']:>5} {v['pt']:>10} {v['ct']:>10} {v['rt']:>9} {v['cost']:>10.6f}")

    tot_pt = sum(v["pt"] for v in by_model.values())
    tot_ct = sum(v["ct"] for v in by_model.values())
    tot_cost = sum(v["cost"] for v in by_model.values())
    print("-" * 76)
    print(f"{'合计':26} {len(rows):>5} {tot_pt:>10} {tot_ct:>10} "
          f"{sum(v['rt'] for v in by_model.values()):>9} {tot_cost:>10.6f}")

    print(f"\n{'日期':12} {'次数':>5} {'tokens':>10} {'费用(元)':>10}")
    print("-" * 42)
    for d, v in sorted(by_day.items()):
        print(f"{d:12} {v['n']:>5} {v['tok']:>10} {v['cost']:>10.6f}")

    print(f"\n注意：费用是「按当前价格表估算」，不等于账单。"
          f"真实扣费请看控制台 → 财务与订单。")


def cmd_limits(args):
    model = "glm-5.3-flash"
    if "--model" in args:
        i = args.index("--model")
        model = args[i + 1]
    _, hdrs = request_json(
        "/chat/completions",
        {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
    )
    print(f"model: {model}  （响应头实测）\n")
    for k in ("X-Ratelimit-Limit-Requests", "X-Ratelimit-Remaining-Requests",
              "X-Ratelimit-Limit-Tokens", "X-Ratelimit-Remaining-Tokens",
              "X-Request-ID"):
        if k in hdrs:
            print(f"{k:32}: {hdrs[k]}")
    print("\n说明：Remaining 是**限流窗口**余量（会回补），不是余额。")


def cmd_clear():
    if os.path.exists(LEDGER):
        os.remove(LEDGER)
        print("账本已清空")
    else:
        print("账本本来就不存在")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    cmd = args[0]
    {"ask": cmd_ask, "report": cmd_report, "limits": cmd_limits,
     "clear": lambda a: cmd_clear()}.get(cmd, lambda a: sys.exit(f"未知命令: {cmd}"))(args[1:])


if __name__ == "__main__":
    main()
