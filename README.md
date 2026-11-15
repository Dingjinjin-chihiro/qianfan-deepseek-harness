# 百度千帆（Qianfan）API Key 使用指南

> 本目录下的脚本都是**已实测跑通**的（纯标准库，无需安装依赖）。
> 下面的结论都是拿你这把 key 实际请求 `qianfan.baidubce.com` 验证过的，不是抄文档。

**想直接上 DeepSeek？** → 看 [第 5 章](#5-deepseek-接入)，一行启动：

```powershell
$env:QIANFAN_API_KEY = "bce-v3/ALTAK-xxx/xxx"
python deepseek.py "你好"
```

---

## 1. 你手里这把 key 是什么

```
bce-v3/ALTAK-xxxxxxxxxxxxxxxxxxxx/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

这是千帆的**统一 API Key（V2 接口用）**，不是传统的 AK/SK。
用法就一句话：

```
Authorization: Bearer bce-v3/ALTAK-...(整串，斜杠不用转义)
```

✅ 好消息：我用它调 `/v2/models` 返回 **200**，能正常对话、流式、向量化 —— **这把 key 是有效的**。

---

## 2. 接口信息

| 项目 | 值 |
|---|---|
| Base URL | `https://qianfan.baidubce.com/v2` |
| 对话补全 | `POST /chat/completions`（OpenAI 格式） |
| 文本向量 | `POST /embeddings` |
| 模型列表 | `GET /models` |
| 鉴权头 | `Authorization: Bearer <API Key>` |

---

## 3. 五种调用方式

### 3.1 curl（最快验证）

```bash
curl https://qianfan.baidubce.com/v2/chat/completions \
  -H "Authorization: Bearer bce-v3/ALTAK-xxx/xxx" \
  -H "Content-Type: application/json" \
  -d '{"model":"ernie-5.1","messages":[{"role":"user","content":"你好"}]}'
```

### 3.2 PowerShell

```powershell
$env:QIANFAN_API_KEY = "bce-v3/ALTAK-xxx/xxx"
$h = @{ Authorization = "Bearer $env:QIANFAN_API_KEY"; "Content-Type" = "application/json" }
$b = @{ model = "ernie-5.1"; messages = @(@{ role = "user"; content = "你好" }) } | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "https://qianfan.baidubce.com/v2/chat/completions" -Method Post -Headers $h -Body $b
```

### 3.3 Python（零依赖，见 `demo.py`）

```powershell
$env:QIANFAN_API_KEY = "bce-v3/ALTAK-xxx/xxx"
python demo.py                          # 跑完整演示：非流式 + 流式 + 向量
python demo.py "写一首关于秋天的五言绝句"
python demo.py --model deepseek-v4-pro "解释 RAG"
python demo.py --models                 # 看你的账号能用哪些模型
```

### 3.4 Python + OpenAI SDK（官方兼容，已实测）

```powershell
pip install openai
```

```python
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["QIANFAN_API_KEY"],      # bce-v3/ALTAK-.../...
    base_url="https://qianfan.baidubce.com/v2",
)

resp = client.chat.completions.create(
    model="ernie-5.1",
    messages=[{"role": "user", "content": "你好"}],
)
print(resp.choices[0].message.content)
```

实测结果（openai 3.51.0）：
```
glm-5.3-flash → content: '收到'
ernie-5.1     → content: '1 + 1 = 2.'
流式 ernie-5.1 → stream: 1, 2, 3 🔢
```

原版 OpenAI 的写法可以**原样搬过来**，只改 `base_url` 和 `model`。

流式：

```python
stream = client.chat.completions.create(
    model="glm-5.3-flash",
    messages=[{"role": "user", "content": "数到 5"}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

### 3.5 Node.js / 前端

```js
const res = await fetch("https://qianfan.baidubce.com/v2/chat/completions", {
  method: "POST",
  headers: {
    Authorization: `Bearer ${process.env.QIANFAN_API_KEY}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    model: "ernie-5.1",
    messages: [{ role: "user", content: "你好" }],
  }),
});
console.log((await res.json()).choices[0].message.content);
```

> ⚠️ 浏览器前端**不要**直连，key 会被抓包拿走。放后端 / 云函数里代理。

---

## 4. 你这把 key 实际可用的模型

> 实测时间：2026-11-16，来自 `GET /v2/models`（共 31 个）。
> 价格单位：**元 / 千 tokens**。

| 模型 ID | 类型 | 上下文 | 输入价 | 说明 |
|---|---|---|---|---|
| `ernie-5.1` | chat | 248,832 | 0.004 / 0.006 | 百度旗舰，带思维链 |
| `ernie-5.5-flash-preview` | chat | 2,097,152 | 0.0005 | 超长上下文，便宜 |
| `ernie-light-dt-1.0` | chat | 1,179,648 | 0.008 | |
| `deepseek-v4-pro` | chat | 1,441,792 | 0.012 | DeepSeek 旗舰 |
| `deepseek-v4-pro-0813` | chat | 1,441,792 | 0.0045 | 便宜版 |
| `deepseek-v4-flash-0731` | chat | 1,441,792 | 0.0015 | 性价比高 |
| `deepseek-v4.1-flash-1017` | 多模态 | 1,441,792 | 0.001 | |
| `glm-5.2` | chat | 1,179,648 | 0.008 | 智谱 |
| `glm-5.3` | chat | 1,179,648 | 0.008 | 智谱新版 |
| `glm-5.3-flash` | 多模态 | 1,179,648 | 0.0008 | 快且便宜 |
| `glm-5.2-fast` | chat | 1,179,648 | 0.016 | 高速版 |
| `glm-5.1` | chat | 333,824 | 0.006 / 0.008 | |
| `qwen3.5-27b / 35b-a3b / 122b-a10b / 397b-a17b` | 多模态 | 407,552 | 0.0004 ~ 0.0012 | 通义千问 |
| `bge-large-zh` / `bge-large-en` | embeddings | 512 | 0.0005 | 中文/英文向量，1024 维 |
| `qwen3-embedding-0.6b / 4b / 8b` | embeddings | 8,192 | 0.0005 | 长文本向量 |
| `qianfan-ocr` / `pp-structurev3` / `deepseek-ocr` / `internvl3-38b` | 图像理解 | — | 0.0003 ~ 0.09 | OCR / 文档解析 |
| `qwen-image` / `qwen-image-edit` | 文生图 | — | 按张计费 | |

**常用起步**：`ernie-5.1`（效果）或 `glm-5.3-flash` / `deepseek-v4-flash-0731`（便宜快）。

---

## 5. DeepSeek 接入

### 5.1 你的 key 直接就能用

千帆上挂了 4 个 DeepSeek 模型，实测全部在线、都能调通：

| 模型 ID | 上下文 | 输入（元/千tok） | 输出 | 定位 |
|---|---|---|---|---|
| `deepseek-v4-pro` | 1,441,792 | 0.012 | 0.024 | 旗舰，推理最强 |
| `deepseek-v4-pro-0813` | 1,441,792 | 0.0045 | 0.0135 | 同代快照，便宜 2.7 倍 |
| `deepseek-v4-flash-0731` | 1,441,792 | 0.0015 | 0.0045 | 便宜 8 倍，**日常首选** |
| `deepseek-v4.1-flash-1017` | 1,441,792 | 0.001 | 0.004 | 最便宜 + 多模态 |

共同的 `features`（实测可用）：

- `function_call` —— 工具调用
- `structured_output` —— `response_format: json_schema`
- `prompt_caching` —— 命中缓存只收 0.001/千tok（pro 缓存价是输入价的 1/12），长系统提示能省很多
- `fim_completion` —— 代码补全
- 都支持 **144 万上下文**、单次最多 393k 输出

### 5.2 命令行直接用

```powershell
$env:QIANFAN_API_KEY = "bce-v3/ALTAK-xxx/xxx"

python deepseek.py "用一句话解释量子纠缠"
python deepseek.py -i                                    # 多轮对话，记得上下文
python deepseek.py --stream "写一首五言绝句"              # 边说边出
python deepseek.py --reasoning "9.11 和 9.9 谁大"         # 顺便看思考过程
python deepseek.py --tools "现在几点？顺便算 37*89"        # 真调工具
python deepseek.py --json "从『李四 28 岁住成都』抽取字段"  # 结构化输出
python deepseek.py --list                                 # 看模型
python deepseek.py --model deepseek-v4-flash-0731 "你好"  # 换便宜模型
```

`--tools` 实测输出（两个工具串在同一次回答里）：

```
  ↳ get_current_time({}) → {"time": "2026-11-16 06:50:03", "weekday": "Monday"}
  ↳ calculate({"expression": "37*89"}) → {"expression": "37*89", "result": 3293}

现在的北京时间是 **2026年11月16日（星期一）06:50:03**。
37 × 89 = **3293**。
```

`--json` 实测输出（schema 约束生效，直接是合法 JSON）：

```json
{"age": 28, "city": "成都", "name": "李四"}
```

### 5.3 当库用

```python
from deepseek_client import DeepSeek, Conversation

ds = DeepSeek()                       # 走千帆 + deepseek-v4-pro
ans = ds.chat("你好")
print(ans["content"])                 # 答案
print(ans["reasoning"])               # 思维链（单独放，不混进答案）
print(ans["usage"])                   # token 用量

# 多轮
conv = Conversation(ds, system="你是一个简洁的助手")
conv.say("我叫丁丁")
conv.say("我叫什么？")                 # 记得住

# 工具循环（模型要调 → 你执行 → 结果回灌 → 模型总结，全自动）
ans, msgs, trace = ds.chat_with_tools("37*89 等于多少", tools=[...], handlers={...})
```

所有调用会自动记进 `usage_ledger.jsonl`，`python usage.py report` 直接能看到 DeepSeek 的消耗。

### 5.4 三条接入通道，按场景选

| 通道 | base_url | 什么时候用 |
|---|---|---|
| **OpenAI 兼容** | `https://qianfan.baidubce.com/v2` | 绝大多数场景，本目录默认 |
| **Anthropic 兼容** | `https://qianfan.baidubce.com/anthropic` | 想接 Claude Code / Anthropic SDK |
| DeepSeek 官方 | `https://api.deepseek.com/v1` | 办了官方 key 之后，`--official` |

Anthropic 通道实测（`x-api-key` 和 `Authorization: Bearer` 两种都认）：

```json
{"type":"message","role":"assistant","content":[
  {"type":"thinking","thinking":"用户要求只回两个字……"},
  {"type":"text","text":"收到"}
]}
```

⚠️ 注意两边字段名不一样：OpenAI 通道叫 `reasoning_content`，Anthropic 通道叫 `thinking` 块。

### 5.5 DeepSeek 特有的坑

| 现象 | 原因 | 解决 |
|---|---|---|
| 回答空、只有思考 | 4 个模型**全是推理模型**，思考 token 吃掉 `max_tokens` | 别设或设 ≥ 512 |
| 工具调用第二次请求 400 | assistant 的 `tool_calls` 没放回历史 | `chat_with_tools()` 已处理 |
| 长系统提示很贵 | 没命中缓存 | 稳定的前缀放最前面，命中后只要 1/12 价格 |
| 中文从管道喂进去报 surrogates | Windows 管道编码 | 已在客户端做 `_clean()` 兜底 |

> 官方通道（`--official`）我手上没有 DeepSeek 官方 key，**没实测**；代码路径是通的，但第一次用请自己验一下。

---

## 6. 踩坑清单（我实测遇到的）

| 现象 | 原因 | 解决 |
|---|---|---|
| `401 invalid_iam_token` | key 写错 / 没加 `Bearer ` / 复制不全 / 已删除 | 检查请求头 |
| `401 invalid_model`（令人困惑，其实是模型问题） | **key 是好的**，只是模型名不对或没开通 | 用 `GET /v2/models` 里的 `id`，别猜老名字 |
| 试 `ernie-speed-128k`、`deepseek-v3`、`ernie-4.0-8k` 全部失败 | 这些旧模型名在当前账号不可用 | 换用上表中的新 ID |
| **`content` 返回空字符串 `''`**（返回 200 但没内容） | 推理模型的思考 token 把 `max_tokens` 预算吃光了 | **别设或把 `max_tokens` 设 ≥ 512**，看 `usage.completion_tokens_details.reasoning_tokens` 确认 |
| `429` | 超 RPM/TPM（比如 glm-5.2-fast 只有 60 rpm） | 加退避重试 |
| 余额/额度问题 | 千帆按量计费，需先在控制台开通模型服务 | 百度智能云控制台 → 千帆 → 在线服务 |

### 特别注意：`reasoning_content`

`ernie-5.1`、`glm-5.x`、`deepseek-v4` 等是**推理模型**，返回体里有两个字段：

```json
"message": {
  "content": "最终答案",
  "reasoning_content": "模型的思考过程"
}
```

- `content` 才是答案，`reasoning_content` 是思维链
- 流式时也是先吐 `reasoning_content` 再吐 `content`
- 只取 `content`，否则你会在界面上看到一堆内心戏

---

## 7. 查看用量

**先说结论（实测）**：千帆 v2 的模型网关**没有**用量/余额查询接口。我把常见路径都探了一遍，全部 404：

```
/v2/usage  /v2/usages  /v2/usage/summary  /v2/billing  /v2/quota
/v2/account  /v2/dashboard  /v2/statistics  /v2/usage/stats  /v2/credits  /v2/balance
→ 全部 404 {"code":"ResourceNotFound"}
```

所以只有两条路：**看控制台**（准，计费口径）或**自己在代码里记账**（实时，能做告警）。

### 7.1 控制台看（计费口径，最准）

| 看什么 | 路径 |
|---|---|
| 各模型调用量 / token 消耗 | [千帆控制台](https://console.bce.baidu.com/qianfan) → 左侧「用量统计」或「在线服务」 |
| 账单 / 消费明细 / 余额 | [财务与订单](https://console.bce.baidu.com/billing/#/account/index) |
| 免费额度还剩多少 | 千帆控制台 → 模型「在线服务」列表，每个模型单独显示 |

> 控制台是**按天/小时聚合**的，有延迟；急着看「刚才那次花了多少」，用下面的代码方式。

### 7.2 代码里拿（三个来源，都已实测）

**a) 响应体 `usage`** —— 每次调用都有，最直接：

```json
"usage": {
  "prompt_tokens": 17,
  "completion_tokens": 79,
  "total_tokens": 96,
  "completion_tokens_details": { "reasoning_tokens": 45 }
}
```

⚠️ `reasoning_tokens` 也按输出计费，算钱时别漏（推理模型里它经常占大头）。

**b) 流式必须显式开 `include_usage`**，否则整个流里一个 usage 都没有：

```python
{"model": "glm-5.3-flash", "messages": [...],
 "stream": True, "stream_options": {"include_usage": True}}
```

实测最后一个 chunk 会带上完整 usage。

**c) 响应头 `X-Ratelimit-*`** —— 实时限流余量：

```
X-Ratelimit-Limit-Requests     : 60
X-Ratelimit-Remaining-Requests : 58
X-Ratelimit-Limit-Tokens       : 1000000
X-Ratelimit-Remaining-Tokens   : 999789
X-Request-ID                   : as-910kz7bzcu
```

⚠️ 这是**限流窗口**余量（按分钟回补），**不是账户余额**。余额只能看控制台。

### 7.3 用 `usage.py` 本地记账（推荐）

既然没有用量 API，最实用的就是自己记一笔：

```powershell
$env:QIANFAN_API_KEY = "bce-v3/ALTAK-xxx/xxx"
python usage.py ask "你好"                        # 发请求 + 记账
python usage.py ask "写首诗" --model deepseek-v4-pro
python usage.py report                            # 按模型 / 按天 / 估算费用
python usage.py report --days 7
python usage.py limits --model glm-5.3-flash      # 当前限流余量
python usage.py clear                             # 清空账本
```

`report` 输出示例：

```
模型                            次数      输入tok      输出tok     思考tok      费用(元)
----------------------------------------------------------------------------
ernie-5.1                      1          9         54        14   0.001242
glm-5.3-flash                  1         15        170       166   0.000488
----------------------------------------------------------------------------
合计                             2         24        224       180   0.001730
```

- 账本落 `usage_ledger.jsonl`，一行一次调用，带 `request_id`，可以直接和账单对账
- 单价从 `/v2/models` 实时拉，不会因为调价而算错
- 费用是**估算**，够用来做预算告警，精确扣费仍以账单为准

---

## 8. 费用与限流

- **计价**：按 token 计，上表是「元 / 千 tokens」。例如 `deepseek-v4-pro` 输入 0.012 元/千 tokens ≈ 12 元/百万 tokens。
- **限流**：每个模型有独立 rpm/tpm（如 `glm-5.2-fast` 250k tpm / 60 rpm；`glm-5.2` 更高）。
- **免费额度**：新账号通常有各模型的免费 token 额度，控制台可查。

---

## 9. 安全建议（重要）

**API Key 等同于账号密码**，泄露后可能被别人拿去跑账单。四条底线：

1. 只从环境变量读，**绝不硬编码进源码、绝不提交进 git**。
2. `.gitignore` 里加上 `.env`、`usage_ledger.jsonl`。
3. 生产环境把 key 放在后端，前端只调你自己的接口，不直连千帆。
4. **如果 key 曾经贴到公开渠道**（聊天、issue、博客截图、录屏），视为已泄露，立即去
   **百度智能云控制台 → 千帆 → API Key 管理** 删除并重建。

发版前可以用 `tools/check-secrets.ps1` 自动扫一遍仓库：

```powershell
pwsh -File tools/check-secrets.ps1
# ✅ 未发现密钥或本机路径残留，可以发布。
```

---

## 10. 文件说明

- `demo.py` —— 零依赖演示：非流式对话、SSE 流式、向量化、模型列表
- `usage.py` —— 用量记账与统计：`ask` / `report` / `limits` / `clear`
- `deepseek_client.py` —— **DeepSeek 接入库**：对话 / 流式 / 工具循环 / JSON 输出 / 用量记账，双通道（千帆 + 官方）
- `deepseek.py` —— DeepSeek 命令行：一次性问答、`-i` 多轮、流式、工具、JSON
- `selftest.py` —— 14 项全链路自检，一条命令验证全部能力
- `tools/read-asar.mjs` —— 解析 Electron `app.asar`，定位内置插件源码
- `tools/check-secrets.ps1` —— 发布前脱敏检查（密钥 / 本机用户名残留）
- `RUNBOOK.md` —— **完整可复现操作手册**（可对外发布）
- `usage_ledger.jsonl` —— 跑 `usage.py ask` 或 `deepseek.py` 后自动生成的账本（不入 git）

