# 千帆 API · DeepSeek · DeepSeek Harness 全流程操作手册

> **文档类型**：可复现操作手册（runbook）
> **目标读者**：另一个执行 AI（或工程师），无需任何前置上下文
> **实测环境**：Windows 11 / PowerShell 7 / Python 3.14.6 / Node 26.13.0 / DeepSeek Harness 0.2.2-rc.1
> **实测日期**：2026-11-16
> **总耗时**：约 20 分钟（不含 Harness 重启）

---

## 0. 给执行 AI 的元指令

1. **按章节顺序执行**，不要跳步。每一节都有「验收标准」，不通过就不要进入下一节。
2. 命令以 ```powershell 或 ```bash 标注。`# 预期：` 后面是应该看到的结果，格式为「关键片段」而非全文。
3. 文档里的路径用占位符：
   - `<DEMO_DIR>` = 代码工作目录（本文档所在目录）
   - `<DSH_HOME>` = DeepSeek Harness 的数据目录，Windows 默认 `%USERPROFILE%\.dsh`
   - `<APP_ASAR>` = Electron 应用的 asar 包，Windows 默认
     `%LOCALAPPDATA%\Programs\DeepSeek Harness\resources\app.asar`
4. 遇到不符合预期的情况，先查 **§10 故障排查总表**，再决定是否继续。
5. **不要跳过 §4.3 的「双 401 判别法」** —— 这是本流程中最容易误判的一步，`invalid_model` 看起来像密钥错误，其实密钥是好的。
6. 涉及修改用户配置的步骤（§9）必须先备份，且必须保留回滚命令。

---

## 1. 目标与产出

完成本手册后，你将得到：

| # | 产出 | 位置 | 验收方式 |
|---|---|---|---|
| 1 | 千帆 API 连通 | 云端 | `GET /v2/models` 返回 200 |
| 2 | 6 个可运行脚本 | `<DEMO_DIR>` | `python selftest.py` 全绿 |
| 3 | DeepSeek 三通道接入示例 | `<DEMO_DIR>` | `python deepseek.py "你好"` 有回答 |
| 4 | 本地用量账本 | `<DEMO_DIR>\usage_ledger.jsonl` | `python usage.py report` 有汇总 |
| 5 | Harness 跑在千帆 DeepSeek 上 | `<DSH_HOME>` 配置 | 模型选择器出现 `(千帆)` 模型 |

**关键结论（先记住，后文有证据）**：

- 千帆 v2 模型网关是 **OpenAI 兼容**协议：`https://qianfan.baidubce.com/v2`
- 千帆同时提供 **Anthropic Messages 兼容**端点：`https://qianfan.baidubce.com/anthropic`
- DeepSeek Harness 的 DeepSeek 适配器 **只说 Anthropic Messages 协议**，所以接 Harness 必须走第二条
- 千帆 **没有**用量查询 API，用量只能看控制台或本地记账

---

## 2. 环境前置检查

```powershell
pwsh --version          # 预期：PowerShell 7.x
python --version        # 预期：Python 3.9 以上
node --version          # 预期：v18 以上（只用于 §9 的 asar 探针）
curl.exe --version      # 预期：curl 8.x（Windows 10+ 自带）
```

**验收标准**：python ≥ 3.9 必须满足，否则 `selftest.py` 里的类型注解和 f-string 用法可能有兼容问题。
node 和 curl 只在特定步骤需要；若缺失，§9 的推导步骤和部分 curl 示例需改用 Python 实现。

还需确认：

```powershell
# 能访问千帆网关
Test-NetConnection qianfan.baidubce.com -Port 443 | Select-Object TcpTestSucceeded
# 预期：TcpTestSucceeded : True
```

---

## 3. 凭证与基本信息

### 3.1 凭证格式

```
bce-v3/ALTAK-<20 位> / <64 位十六进制>
```

- 这是千帆的 **统一 API Key（V2 接口）**，**不是**传统 AK/SK，不需要任何签名计算。
- 用法：`Authorization: Bearer <整串>`。**斜杠不用转义，整串照抄。**
- 官方端点的另一种认证头：`x-api-key: <整串>`（Anthropic 兼容端点两种都认，已实测）

### 3.2 环境变量

Windows PowerShell（当前会话）：

```powershell
$env:QIANFAN_API_KEY = "bce-v3/ALTAK-xxxxx/xxxxx"
```

Windows cmd：

```bat
set QIANFAN_API_KEY=bce-v3/ALTAK-xxxxx/xxxxx
```

**验收标准**：

```powershell
$env:QIANFAN_API_KEY.Length   # 预期：约 75（bce-v3/ + ALTAK- + 20 + / + 64）
```

### 3.3 安全约束（必须执行）

1. 密钥**只存环境变量**或凭证库，禁止硬编码进源码、禁止提交 Git（`.gitignore` 已含 `.env`）。
2. 若密钥曾在聊天/日志/截图中明文出现，**视为已泄露**，应到 百度智能云控制台 → 千帆 → API Key 管理 重建。
3. 浏览器前端**禁止**直连，必须经后端代理。

### 3.4 端点对照表

| 用途 | 方法 | URL |
|---|---|---|
| 对话补全（OpenAI 兼容） | POST | `https://qianfan.baidubce.com/v2/chat/completions` |
| 文本向量 | POST | `https://qianfan.baidubce.com/v2/embeddings` |
| 模型清单 | GET | `https://qianfan.baidubce.com/v2/models` |
| 对话补全（Anthropic 兼容） | POST | `https://qianfan.baidubce.com/anthropic/v1/messages` |

---

## 4. 阶段一：连通性验证

### 4.1 列出模型（最快探活）

```powershell
curl.exe -s "https://qianfan.baidubce.com/v2/models" -H "Authorization: Bearer $env:QIANFAN_API_KEY"
```

**验收标准**：返回 `{"object":"list","data":[...]}`，且 `data` 长度 > 0。
实测该账号返回 **31 个模型**。

### 4.2 发一次对话

```powershell
$body = '{"model":"ernie-5.1","messages":[{"role":"user","content":"你好"}]}'
$tmp = "$env:TEMP\q.json"
[IO.File]::WriteAllText($tmp, $body, [Text.UTF8Encoding]::new($false))
curl.exe -s -X POST "https://qianfan.baidubce.com/v2/chat/completions" `
  -H "Authorization: Bearer $env:QIANFAN_API_KEY" `
  -H "Content-Type: application/json" --data-binary "@$tmp"
```

**验收标准**：返回体含 `"object":"chat.completion"` 与 `"choices":[{"message":{"content":"..."}}]`。

> ⚠️ 中文请求体务必按 UTF-8 **无 BOM** 写入文件再用 `--data-binary` 发送。
> 直接 `-d` 拼中文在部分 Windows 终端会按 GBK 编码，服务端收到乱码。

### 4.3 【关键】双 401 判别法

千帆的 401 有两种，**含义完全不同**，这是整个流程最容易踩的坑：

| 现象 | 真实原因 | 判定 |
|---|---|---|
| `401` + `invalid_iam_token` | key 本身无效/被删/复制不全 | **密钥问题** |
| `401` + `invalid_model` | key **是好的**，只是模型名不存在或未开通 | **模型名问题** |

验证方法（两步对照）：

```powershell
# 第一步：用假 key 调真模型 → 应该得到 invalid_iam_token
curl.exe -s -X POST "https://qianfan.baidubce.com/v2/chat/completions" `
  -H "Authorization: Bearer bce-v3/ALTAK-fakefakefake/fakefakefake" `
  -H "Content-Type: application/json" `
  -d '{\"model\":\"ernie-5.1\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}'
# 预期：{"error":{"code":"invalid_iam_token",...}}

# 第二步：用真 key 调一个不存在的模型 → 得到 invalid_model
# 如果第二步是 invalid_model，说明你的 key 通过认证了
```

**结论规则**：

- 假 key → `invalid_iam_token`，真 key → `invalid_model` ⇒ **key 有效，去查模型名**
- 真 key 也返回 `invalid_iam_token` ⇒ **key 无效**

**实测记录**：用 `ernie-speed-128k`、`ernie-4.0-8k`、`deepseek-v3` 等"常见"模型名调用，全部返回 `invalid_model`；换成 `/v2/models` 里真实存在的 id 后立刻成功。
**所以：永远不要凭记忆猜模型名，必须先查 `/v2/models`。**

### 4.4 错误码速查

| HTTP | code | 含义 | 处置 |
|---|---|---|---|
| 401 | `invalid_iam_token` | 密钥无效 | 检查 Bearer、是否复制完整、是否已删除 |
| 401 | `invalid_model` | 模型名不存在/无权限 | 查 `/v2/models` 拿真实 id |
| 404 | `ResourceNotFound` | 路径不存在 | 检查 baseURL 是否带了 `/v2` |
| 429 | — | 超 RPM/TPM | 退避重试；限流值见响应头 `X-Ratelimit-*` |
| 200 + 空 content | — | 推理模型思考 token 把 `max_tokens` 吃光 | 见 §7.4 |

---

## 5. 阶段二：模型资产盘点

### 5.1 拉取并格式化

```powershell
python "<DEMO_DIR>\demo.py" --models
```

或零依赖单行版：

```powershell
python -c "import json,urllib.request,os;r=urllib.request.Request('https://qianfan.baidubce.com/v2/models',headers={'Authorization':'Bearer '+os.environ['QIANFAN_API_KEY']});d=json.load(urllib.request.urlopen(r));[print(m['id'],m['type'],m.get('context_length'),m['owned_by']) for m in d['data']]"
```

### 5.2 完整清单（实测快照，2026-11-16，共 31 个）

**对话类（chat）**

| 模型 ID | 上下文 | 输入(元/千tok) | 输出 | 厂商 |
|---|---|---|---|---|
| `ernie-5.1` | 248,832 | 0.004 / 0.006 分档 | — | Baidu |
| `ernie-5.5-flash-preview` | 2,097,152 | 0.0005 | — | Baidu |
| `ernie-light-dt-1.0` | 1,179,648 | 0.008 | — | Baidu |
| `deepseek-v4-pro` | 1,441,792 | 0.012 | 0.024 | DeepSeek |
| `deepseek-v4-pro-0813` | 1,441,792 | 0.0045 | 0.0135 | DeepSeek |
| `deepseek-v4-flash-0731` | 1,441,792 | 0.0015 | 0.0045 | DeepSeek |
| `glm-5.2` | 1,179,648 | 0.008 | — | Zhipu |
| `glm-5.3` | 1,179,648 | 0.008 | — | Zhipu |
| `glm-5.2-fast` | 1,179,648 | 0.016 | — | Zhipu |
| `glm-5.1` | 333,824 | 0.006 / 0.008 分档 | — | Zhipu |

**多模态 / 图像理解**

| 模型 ID | 上下文 | 输入 | 厂商 |
|---|---|---|---|
| `deepseek-v4.1-flash-1017` | 1,441,792 | 0.001 | DeepSeek |
| `glm-5.3-flash` | 1,179,648 | 0.0008 | Zhipu |
| `qwen3.5-27b` / `35b-a3b` / `122b-a10b` / `397b-a17b` | 407,552 | 0.0004 ~ 0.0012 | Tongyi Lab |
| `qianfan-ocr` | 61,440 | 0.00045 | Baidu |
| `pp-structurev3` / `paddleocr-vl-0.9b` | — | 0.09 | Baidu |
| `deepseek-ocr` | — | 0.0003 | DeepSeek |
| `internvl3-38b` | 32,768 | 0.008 | Shanghai AI Lab |
| `unlimited-ocr-2` | — | 0.001 | Baidu |

**向量 / 生成**

| 模型 ID | 类型 | 维度 / 说明 | 输入 |
|---|---|---|---|
| `bge-large-zh` / `bge-large-en` | embeddings | 1024 | 0.0005 |
| `embedding` | embeddings | 384 | 0.0005 |
| `qwen3-embedding-0.6b` / `4b` / `8b` | embeddings | 支持 8192 上下文 | 0.0005 |
| `qwen-image` / `qwen-image-edit` | text2image | 按张计费 | — |
| `ernie-wizshot-me` | video | — | — |

**验收标准**：`/v2/models` 返回的 id 集合 ⊇ {`deepseek-v4-pro`, `deepseek-v4-flash-0731`, `bge-large-zh`, `ernie-5.1`}。
若有缺失 ⇒ 账号未开通对应模型，去控制台开通；**不影响 §9 的 Harness 接入**（只要 `deepseek-*` 在即可）。

---

## 6. 阶段三：交付代码

### 6.1 文件清单

| 文件 | 作用 | 依赖 |
|---|---|---|
| `demo.py` | 最小演示：非流式 / 流式 / 向量化 / 列模型 | 仅标准库 |
| `usage.py` | 本地用量记账与统计（`ask` / `report` / `limits`） | 仅标准库 |
| `deepseek_client.py` | 可复用客户端库：对话 / 流式 / 工具循环 / JSON / 双通道 | 仅标准库 |
| `deepseek.py` | DeepSeek 命令行入口（一次性 / `-i` 多轮 / 工具 / JSON） | 上述库 |
| `selftest.py` | 14 项全链路自检 | 仅标准库 |
| `tools/read-asar.mjs` | 解析 Electron `app.asar`，定位内置插件源码 | Node 18+ |
| `tools/check-secrets.ps1` | 发布前脱敏检查（密钥 / 本机用户名残留） | PowerShell 7 |
| `.gitignore` | 排除账本与 `.env` | — |

**全部文件内容见附录 A，必须逐字创建，不要改写。**

### 6.2 一键自检

```powershell
cd <DEMO_DIR>
$env:QIANFAN_API_KEY = "bce-v3/ALTAK-xxxxx/xxxxx"
python selftest.py
```

**验收标准（实测输出）**：

```
[本地检查]
  PASS  环境 Python>=3.9  [3.14.6]
  PASS  交付文件齐全  [5 个]
  PASS  deepseek_client 可导入
[联机检查]
  PASS  GET /v2/models  [31 个模型]
  PASS  对话（非流式）  [content='收到']
  PASS  reasoning_content 字段  [思考 27 tok]
  PASS  流式 + include_usage  [content+usage 都收到]
  PASS  工具调用  [调用 add]
  PASS  结构化 JSON 输出  [{"name": "张三", "age": 30}]
  PASS  向量化  [维度 1024]
  PASS  错误路径（假 key）  [401 invalid_iam_token]
  PASS  Anthropic 兼容通道  [blocks=['thinking', 'text']]
  PASS  Anthropic 工具结果回灌  [工具结果已消费]
  PASS  deepseek_client 客户端库  [usage=98 tok]
结果: 14/14 通过
```

**14/14 通过 = 阶段一~三全部完成**。任何一项 FAIL 都会打印 `-> 异常类型: 原因`，按 §10 定位。

> ⚠️ 上面的 token 数量、`content` 具体文字会随模型随机性浮动（例如 `[思考 27 tok]` 可能是 31 tok）。
> **判断标准只有两条：每项都是 PASS，且最后一行是 `14/14`。** 不要比对具体数字。
退出码：0 全过，1 有失败。

`--offline` 只跑本地 3 项（无需联网）。

### 6.3 各脚本冒烟测试

```powershell
python demo.py "用一句话解释量子纠缠"           # 预期：一句话回答 + usage
python demo.py --models                        # 预期：31 行模型表
python usage.py ask "你好"                     # 预期：回答 + 本次 tokens + 写入账本
python usage.py report                         # 预期：按模型/按天汇总表
python usage.py limits --model glm-5.3-flash   # 预期：X-Ratelimit-* 四个值
python deepseek.py "你好"                      # 预期：回答 + [输入 x · 输出 y · 其中思考 z]
python deepseek.py --stream "数到5"             # 预期：逐字输出
python deepseek.py -i                          # 预期：进入 你 > 提示符，/exit 退出
```

---

## 7. 阶段四：DeepSeek 接入（代码层）

### 7.1 三通道选型

| 通道 | baseURL | 认证头 | 用途 |
|---|---|---|---|
| **OpenAI 兼容** | `https://qianfan.baidubce.com/v2` | `Authorization: Bearer` | 通用开发、SDK 生态 |
| **Anthropic 兼容** | `https://qianfan.baidubce.com/anthropic` | `x-api-key` 或 Bearer | 接 Harness / Claude Code / Anthropic SDK |
| 官方（自备 key） | `https://api.deepseek.com/v1` | `Authorization: Bearer` | 有 DeepSeek 官方账号时 |

> Anthropic 通道实测两种认证头都接受，`anthropic-version: 2023-06-01` 与
> `anthropic-beta: files-api-2025-04-14` 均不报错（§9 依赖这一点）。

### 7.2 Open 兼容通道示例

```python
from openai import OpenAI
import os

client = OpenAI(api_key=os.environ["QIANFAN_API_KEY"],
                base_url="https://qianfan.baidubce.com/v2")
resp = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[{"role": "user", "content": "你好"}])
print(resp.choices[0].message.content)
```

OpenAI SDK 可**原样照搬**，只改 `base_url` 和 `model`（实测 openai 3.51.0 通过）。

### 7.3 四个 DeepSeek 模型的能力矩阵（实测）

| 能力 | 结果 |
|---|---|
| 上下文 | 1,441,792 tokens |
| 单次最大输出 | 393,216 tokens |
| `function_call` | ✅ 返回标准 `tool_calls` |
| `structured_output` | ✅ `response_format: json_schema` |
| `prompt_caching` | ✅ 响应含 `prompt_tokens_details.cached_tokens` |
| `fim_completion` | ✅（模型 `features` 声明） |
| 推理输出 | ✅ 全部返回 `reasoning_content` |

### 7.4 【关键】推理模型的两个必踩坑

**坑 1：`content` 返回空字符串**

四个 DeepSeek 模型**全是推理模型**，响应体有两个字段：

```json
"message": {
  "content": "最终答案",
  "reasoning_content": "思维链"
}
```

若设置 `max_tokens` 过小（如 50），思考 token 会先把它吃光，`content` 变成 `""`，
但 HTTP 仍是 **200**，看起来像"成功但没内容"。

- 判定：看 `usage.completion_tokens_details.reasoning_tokens` 是否接近 `max_tokens`
- 处置：**不设 `max_tokens`，或设 ≥ 512**

**坑 2：流式拿不到 usage**

流式若不加 `stream_options: {"include_usage": true}`，整个 SSE 流里**没有** usage。
兼容 OpenAI 的写法：

```json
{"model": "deepseek-v4-pro", "messages": [...], "stream": true,
 "stream_options": {"include_usage": true}}
```

**坑 3：工具循环第二轮 400**

多轮工具调用时，必须把 assistant 的 `tool_calls` 原样放回历史，再追加 `role: "tool"` 的结果：

```python
msgs.append({"role": "assistant", "content": ans["content"] or "",
             "tool_calls": ans["tool_calls"]})   # ← 少这一条就 400
msgs.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
```

`deepseek_client.chat_with_tools()` 已封装完整循环。

**坑 4：Windows 管道喂中文报 surrogates**

```
UnicodeEncodeError: 'utf-8' codec can't encode character '\ud800'
```

原因：PowerShell 管道把 UTF-8 字节写入 stdin，Python 按 GBK 解码失败产生孤立代理字符，
`json.dumps().encode("utf-8")` 直接抛错。

- 修复 1：`sys.stdin.reconfigure(encoding="utf-8", errors="replace")`（非 tty 时）
- 修复 2：发送前用 `_clean()` 剔除孤立代理字符（已内置）
- 修复 3：避免在 docstring 里写 `\ud800` 这种转义（会被解析成真代理字符）

### 7.5 Anthropic 通道最小示例

```powershell
$body = '{"model":"deepseek-v4-pro","max_tokens":200,"messages":[{"role":"user","content":"只回答两个字：收到"}]}'
$tmp = "$env:TEMP\a.json"
[IO.File]::WriteAllText($tmp, $body, [Text.UTF8Encoding]::new($false))
curl.exe -s -X POST "https://qianfan.baidubce.com/anthropic/v1/messages" `
  -H "x-api-key: $env:QIANFAN_API_KEY" `
  -H "anthropic-version: 2023-06-01" `
  -H "Content-Type: application/json" --data-binary "@$tmp"
```

**验收标准**：

```json
{"type":"message","role":"assistant","content":[
  {"type":"thinking","thinking":"..."},
  {"type":"text","text":"收到"}]}
```

注意字段名差异：**OpenAI 通道叫 `reasoning_content`，Anthropic 通道叫 `thinking` 块。**

---

## 8. 阶段五：用量与成本

### 8.1 【重要】千帆没有用量查询 API

实测下列路径**全部 404**（`{"code":"ResourceNotFound"}`）：

```
/v2/usage  /v2/usages  /v2/usage/summary  /v2/billing  /v2/quota
/v2/account  /v2/dashboard  /v2/statistics  /v2/usage/stats  /v2/credits  /v2/balance
```

**所以只有两条路**：看控制台，或代码里自己记账。不要在这上面反复试探接口。

### 8.2 控制台路径

| 看什么 | 地址 |
|---|---|
| 各模型调用量 / token 消耗 | `https://console.bce.baidu.com/qianfan` → 左侧「用量统计」/「在线服务」 |
| 账单 / 余额 / 消费明细 | `https://console.bce.baidu.com/billing/#/account/index` |
| 免费额度剩余 | 千帆控制台 → 模型「在线服务」列表 |

### 8.3 代码侧三个来源（均已实测）

1. **响应体 `usage`**：每次调用都有，含 `reasoning_tokens` 和 `cached_tokens`
2. **流式需开 `stream_options.include_usage`**：否则全流无 usage
3. **响应头 `X-Ratelimit-*`**：

```
X-Ratelimit-Limit-Requests     : 60
X-Ratelimit-Remaining-Requests : 58
X-Ratelimit-Limit-Tokens       : 1000000
X-Ratelimit-Remaining-Tokens   : 999789
```

⚠️ `Remaining` 是**限流窗口余量**（按分钟回补），**不是账户余额**。

### 8.4 本地记账

```powershell
python usage.py ask "你好"                       # 记账
python usage.py report                           # 汇总
python usage.py report --days 7
python usage.py clear
```

账本 `<DEMO_DIR>\usage_ledger.jsonl`，一行一次调用，字段：

```json
{"ts":1794782xxx,"time":"2026-11-16 06:50:03","model":"deepseek-v4-pro",
 "provider":"qianfan","prompt_tokens":9,"completion_tokens":165,
 "cached_tokens":0,"reasoning_tokens":122,"total_tokens":174,
 "cost_est":0.004068,"request_id":"as-xxx","prompt":"你好"}
```

- 单价从 `/v2/models` **实时拉取**，调价不会算错
- 费用是**估算**（按当前价目表），精确扣费以账单为准
- `deepseek_client.py` 的所有调用也会自动写同一账本，`usage.py report` 统一汇总

---

## 9. 阶段六：接入 DeepSeek Harness（GUI 客户端）

> 本节是全文最关键、也最容易搞错的部分。核心结论：
> **Harness 的 DeepSeek 适配器只说 Anthropic Messages 协议，所以必须把它的 `baseURL` 指向千帆的 `/anthropic` 端点。**

### 9.1 原理推导（可复现）

**第 1 步：确认 Harness 的 provider 机制**

Harness 用 `cordis` 插件树组织配置。配置分三层：

```
bundle 层（内置，打包在 app.asar）
   ↓
profile 层 cordis.patch.yml（用户可改，覆盖 bundle 同 id 条目）
   ↓
命令行 --patch 覆盖
```

用户可写的层是 `<DSH_HOME>\profiles\<profile>\cordis.patch.yml`。
它要求入口是 `- id: X` + `name: 包名` + `config: {...}`，`id` 相同即覆盖内置条目。

**第 2 步：找到 LLM 适配器**

用附录 A 的 `tools/read-asar.mjs` 列举内置包：

```powershell
node "<DEMO_DIR>\tools\read-asar.mjs" list "<APP_ASAR>" "@deepseek-ai/dsh-llm"
```

预期看到（节选）：

```
@deepseek-ai/dsh-llm
@deepseek-ai/dsh-llm-deepseek
@deepseek-ai/dsh-llm-deepseek-account
@deepseek-ai/dsh-llm-deepseek-api-key
@deepseek-ai/dsh-llm-pi-ai
@deepseek-ai/dsh-llm-retry
```

**第 3 步：确认协议与端点**

```powershell
node "<DEMO_DIR>\tools\read-asar.mjs" cat "<APP_ASAR>" `
  "/dsh/node_modules/@deepseek-ai/dsh-llm-deepseek/lib/index.js" |
  Select-String -Pattern 'PUBLIC_BASE_URL|anthropic-version|MESSAGES_FILES_BETA'
```

实测关键行：

```js
const PUBLIC_BASE_URL = "https://api.deepseek.com/anthropic";   // ← 协议是 Anthropic Messages
const MESSAGES_FILES_BETA = "files-api-2025-04-14";
headers.set("anthropic-version", "2023-06-01");
headers.set("anthropic-beta", MESSAGES_FILES_BETA);
function messagesApiRoot(baseURL) {  // baseURL 不以 /v1 结尾时自动补 /v1
  return endsWith("/v1") ? base : `${base}/v1`;
}
```

**结论**：请求最终打到 `<baseURL>/v1/messages`，带 `anthropic-version` + `anthropic-beta`。
千帆的 `https://qianfan.baidubce.com/anthropic/v1/messages` **完全匹配**（已在 §4 与 selftest 中验证）。

**第 4 步：确认认证方式**

```powershell
node "<DEMO_DIR>\tools\read-asar.mjs" cat "<APP_ASAR>" `
  "/dsh/node_modules/@deepseek-ai/dsh-llm-deepseek-api-key/lib/index.js" |
  Select-String -Pattern 'PROVIDER|x-api-key|apiKeyEnv'
```

实测关键行：

```js
const PROVIDER = "deepseek-official";
apiKeyEnv: z.string().role("credential-ref").default("DEEPSEEK_API_KEY")
resolveAuth: async (connection) => ({ headers: { "x-api-key": await resolveApiKey(connection) } })
```

**结论**：认证头是 `x-api-key`，密钥由 `apiKeyEnv` 指定的**凭证引用名**解析。
千帆的 Anthropic 端点接受 `x-api-key`（已验证）。

**第 5 步：确认可配置字段**

`dsh-llm-deepseek` 的 `deepSeekConfigFields`（实测）：

```js
baseURL, thinking('enabled'|'disabled'), reasoningEffort('off'|'low'|'high'|'max'),
maxTokens, defaultContextWindow, models[], streamIdleTimeoutMs, retryPolicy,
maxRequestFilesBytes, maxImagesPerRequest, ...
catalogModel = { id(必填), name, description, contextWindow, maxTokens,
                 imagePixelBudget, imageMaxBytes, inputModalities }   // 默认 ["text"]
```

**第 6 步：确认默认模型条目 id**

```powershell
node "<DEMO_DIR>\tools\read-asar.mjs" cat "<APP_ASAR>" `
  "/dsh/node_modules/@deepseek-ai/dsh-base/cordis.patch.yml" |
  Select-String -Pattern 'llm-deepseek|agent-default-model' -Context 0,3
```

实测结论：内置条目 **`id: llm-deepseek`** 使用包 `@deepseek-ai/dsh-llm-deepseek-api-key`，
默认 `agent-default-model` 为 `provider: deepseek-official / model: deepseek-flash`。
**因此只要覆盖 `llm-deepseek` 这一条即可，不需要新增插件。**

> 若版本不同导致 id/包名变化，用 `list` 子命令按 `llm` 关键字重新查找，逻辑不变。

### 9.2 定位配置目录

```powershell
$DSH_HOME = if ($env:DSH_HOME) { $env:DSH_HOME } else { "$env:USERPROFILE\.dsh" }
Get-ChildItem $DSH_HOME           # 预期：profiles/ sessions/ storages/ .credentials.yaml ...
Get-ChildItem "$DSH_HOME\profiles"  # 预期：desktop/ 等
```

**验收标准**：`<DSH_HOME>\profiles\<profile>\cordis.patch.yml` 存在且是一个 YAML 数组。

```powershell
Get-Content "$DSH_HOME\profiles\desktop\cordis.patch.yml" -Encoding utf8 | Select-Object -First 5
# 预期：注释行 + 一个 - id: ... 条目
```

### 9.3 备份（强制）

```powershell
$P = "$DSH_HOME\profiles\desktop"
$ts = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item "$P\cordis.patch.yml" "$P\cordis.patch.yml.backup-$ts"
Copy-Item "$DSH_HOME\.credentials.yaml" "$DSH_HOME\.credentials.yaml.backup-$ts"
Write-Output "备份时间戳: $ts"     # 记下来，回滚要用
```

**验收标准**：两个 `.backup-<ts>` 文件存在，大小与原文件一致。

### 9.4 修改 `cordis.patch.yml`

插入（或覆盖）下面这一条，**位置放在数组里任意处即可**（同 id 后出现者覆盖）：

```yaml
- id: llm-deepseek
  name: "@deepseek-ai/dsh-llm-deepseek-api-key"
  config:
    baseURL: https://qianfan.baidubce.com/anthropic
    apiKeyEnv: QIANFAN_API_KEY
    maxTokens: 32768
    thinking: enabled
    reasoningEffort: max
    models:
      - id: deepseek-v4-pro
        name: DeepSeek V4 Pro (千帆)
        contextWindow: 1000000
        maxTokens: 32768
        inputModalities:
          - text
      - id: deepseek-v4-flash-0731
        name: DeepSeek V4 Flash (千帆)
        contextWindow: 1000000
        maxTokens: 32768
        inputModalities:
          - text
      - id: deepseek-v4.1-flash-1017
        name: DeepSeek V4.1 Flash (千帆)
        contextWindow: 1000000
        maxTokens: 32768
        inputModalities:
          - text
```

同时把默认模型指到新 provider：

```yaml
- id: agent-default-model
  name: "@deepseek-ai/dsh-agent-default-model"
  config:
    provider: deepseek-official
    model: deepseek-v4-pro
    reasoningEffort: max
```

**字段红线（写错任一项插件会加载失败）**：

| 字段 | 约束 | 本方案取值 |
|---|---|---|
| `baseURL` | 必须是合法 URL；不以 `/v1` 结尾会自动补 `/v1` | `.../anthropic` → `/anthropic/v1/messages` ✅ |
| `apiKeyEnv` | POSIX shell 标识符（凭证**引用名**，不是密钥本身） | `QIANFAN_API_KEY` ✅ |
| `models[].id` | 非空，且必须是千帆真实模型 id | `deepseek-v4-pro` ✅ |
| `models[].name` | 非空 | ✅ |
| `models[].contextWindow` | 正整数 | `1000000`（千帆实际 1,441,792，保守取值）|
| `models[].maxTokens` | 正整数 | `32768` |
| `models[].inputModalities` | 非空，只能含 `text` / `image` | `[text]`（DeepSeek 为纯文本）|
| `thinking` + `reasoningEffort` | `thinking: disabled` 时 `reasoningEffort` 只能是 `off` | `enabled` + `max` ✅ |
| `provider` | 必须是已注册的 provider id | `deepseek-official`（硬编码于插件）|

**验收标准**：YAML 能被解析且条目数 ≥ 原条目数。

### 9.5 写入凭证

`apiKeyEnv` 只是引用名，真值放凭证库 `<DSH_HOME>\.credentials.yaml` 的 `refs:` 段。

在 **保留原有 `records:` 全部内容** 的前提下，加入：

```yaml
version: 1
refs:
  QIANFAN_API_KEY: bce-v3/ALTAK-xxxxx/xxxxx
records:
  # ↓ 原文件内容，原样保留，不要删
  client-connection/browser-session: {...}
  deepseek-account-platform/device: {...}
  deepseek-account-platform/default: {...}
```

**格式红线**：

- 顶层必须有 `version: 1`
- `refs` 是**扁平映射**：`引用名: 值字符串`（不是 `{value: ...}`）
- 引用名须匹配合法标识符正则（`QIANFAN_API_KEY` 合规）
- 值**不能为空字符串**（要删除请移除整条）

**最省事的做法**：只加 3 行，其余原样不动：

```powershell
$c = "$DSH_HOME\.credentials.yaml"
$t = Get-Content $c -Raw -Encoding utf8
if ($t -notmatch 'refs:') {
  $t = $t -replace '(?m)^version: 1\s*$', "version: 1`nrefs:`n  QIANFAN_API_KEY: $env:QIANFAN_API_KEY"
  [IO.File]::WriteAllText($c, $t, [Text.UTF8Encoding]::new($false))
}
```

### 9.6 校验 YAML（进入重启前必须做）

用 Harness 自带的 `yaml` 包校验，避免语法错误导致客户端起不来：

```powershell
$js = @'
const fs=require("fs");
const YAML=require(process.argv[2]+"/node_modules/yaml");
const P=process.argv[3], C=process.argv[4];
const patch=YAML.parse(fs.readFileSync(P,"utf8"));
if(!Array.isArray(patch)) throw new Error("cordis.patch.yml 必须是数组");
const ds=patch.find(e=>e.id==="llm-deepseek");
if(!ds) throw new Error("缺少 llm-deepseek 条目");
if(!ds.config.baseURL.includes("/anthropic")) throw new Error("baseURL 不对");
if(!/^[A-Za-z_][A-Za-z0-9_]*$/.test(ds.config.apiKeyEnv)) throw new Error("apiKeyEnv 非法");
for(const m of ds.config.models){
  if(!m.id||!m.name) throw new Error("模型 id/name 不能为空");
  if(!(m.contextWindow>0&&m.maxTokens>0)) throw new Error("contextWindow/maxTokens 必须正整数");
  if(!m.inputModalities?.length) throw new Error("inputModalities 不能为空");
}
const cred=YAML.parse(fs.readFileSync(C,"utf8"));
if(cred.version!==1) throw new Error("credentials 缺少 version: 1");
const k=cred.refs?.[ds.config.apiKeyEnv];
if(!k) throw new Error("credentials 里没有 ref "+ds.config.apiKeyEnv);
const dm=patch.find(e=>e.id==="agent-default-model");
console.log("OK  provider="+dm.config.provider+"  model="+dm.config.model+
            "  keyLen="+k.length+"  models="+ds.config.models.map(m=>m.id).join(","));
'@
$tmp = "$env:TEMP\validate.js"
[IO.File]::WriteAllText($tmp, $js, [Text.UTF8Encoding]::new($false))
node $tmp "$DSH_HOME\profiles\desktop" "$DSH_HOME\profiles\desktop\cordis.patch.yml" "$DSH_HOME\.credentials.yaml"
```

**验收标准**：

```
OK  provider=deepseek-official  model=deepseek-v4-pro  keyLen=75  models=deepseek-v4-pro,deepseek-v4-flash-0731,deepseek-v4.1-flash-1017
```

**这一步不通过就绝对不要重启**，否则客户端可能起不来。

### 9.7 重启与验证

```powershell
# 完全退出（含托盘图标），再重新打开
Get-Process | Where-Object { $_.ProcessName -like '*DeepSeek*' } | Select-Object Id,ProcessName
```

> 配置在**启动时**加载，实测不会热更新（改完等待数分钟，provider 列表仍不变）。

重启后，按任一方式验证：

**方式 A：让会话里的 AI 调工具**

若当前 AI 有 `list_subagent_models` 之类的模型枚举工具，调用后应看到
`deepseek-official` provider 及其模型；**接入前只会有 `deepseek-account`**。

**方式 B：看 UI**

新建会话 → 输入框旁的模型选择器 → 应出现 `DeepSeek V4 Pro (千帆)` 等三个条目。

**方式 C：直接发一句话**

新会话里问「你好」，能正常流式回答即成功；回答框上方的模型名应显示 `(千帆)`。

**验收标准**：三条中至少两条成立，且能正常对话（含工具调用）。

### 9.8 回滚（出事时）

```powershell
$P = "$DSH_HOME\profiles\desktop"
$ts = "20261116-065542"        # ← 换成 §9.3 记下的时间戳
Copy-Item "$P\cordis.patch.yml.backup-$ts" "$P\cordis.patch.yml" -Force
Copy-Item "$DSH_HOME\.credentials.yaml.backup-$ts" "$DSH_HOME\.credentials.yaml" -Force
```

然后重启客户端。此操作不依赖客户端能正常启动，可在纯命令行完成。

### 9.9 已知限制

1. **官方 DeepSeek 路由被覆盖**：该方案改的是内置 `llm-deepseek` 条目，指向千帆后官方路由消失。
   需要两条并存时，改用 `@deepseek-ai/dsh-llm-pi-ai` 注册独立 provider（本手册**未实测**）。
2. **纯文本**：`inputModalities: [text]`，发图会走 harness 的降级文本路径。
3. **上下文按 1,000,000 声明**：千帆实际 1,441,792，保守取值避免压缩策略算错；可按需调高。
4. **计费**：走千帆账户。`deepseek-v4-pro` 输入 0.012 元/千tok，长任务成本可观；
   省钱可把 `agent-default-model.model` 改成 `deepseek-v4-flash-0731`（便宜 8 倍）。
5. **重启才会生效**，无热更新。
6. 不同 Harness 版本的内置 `id` / 包名 / 协议可能变化，**必须重跑 §9.1 的推导步骤确认**，不要盲抄。

---

## 10. 故障排查总表

| # | 现象 | 根因 | 处置 |
|---|---|---|---|
| 1 | `401 invalid_iam_token` | 密钥无效/不全/已删 | 检查 Bearer、`$env:QIANFAN_API_KEY.Length` |
| 2 | `401 invalid_model` | **密钥没问题**，模型名不存在 | 查 `/v2/models` 用真实 id |
| 3 | `404 ResourceNotFound` | 路径少了 `/v2` | baseURL 用 `https://qianfan.baidubce.com/v2` |
| 4 | 200 但 `content` 为 `""` | 思考 token 吃光 `max_tokens` | 不设或 ≥ 512 |
| 5 | 流式无 usage | 没开 `stream_options.include_usage` | 加上 |
| 6 | 工具第二轮 400 | assistant 的 `tool_calls` 没回灌历史 | 用 `chat_with_tools()` |
| 7 | `UnicodeEncodeError ... surrogates` | Windows 管道编码 | stdin reconfigure + `_clean()` |
| 8 | 请求体中文变乱码 | 终端按 GBK 写 body | UTF-8 无 BOM 写文件 + `--data-binary` |
| 9 | `/v2/usage` 404 | 千帆无此 API | 看控制台或本地记账 |
| 10 | 改配置后模型没出现 | 未重启 / YAML 未生效 | 完全退出重启；重跑 §9.6 校验 |
| 11 | 重启后会话报模型不存在 | `provider`/`model` 写错 | 回滚（§9.8）后重做 |
| 12 | 客户端起不来 | YAML 语法错误 | 回滚（§9.8） |
| 13 | `limits` 显示的 Remaining 很低 | 是限流窗口余量，非余额 | 等一分钟回补 |
| 14 | OpenAI SDK 返回空 | 推理模型 + `max_tokens` 过小 | 同 #4 |

---

## 11. 验收清单

- [ ] `curl /v2/models` 返回 200 且模型数 > 0
- [ ] 假 key 得 `invalid_iam_token`，真 key 得"成功" —— 双 401 判别通过
- [ ] `python selftest.py` → `14/14 通过`
- [ ] `python demo.py "测试"` 有中文回答
- [ ] `python usage.py ask "测试"` 后账本新增一行，`report` 能汇总
- [ ] `python deepseek.py --tools "算 37*89"` 出现 `↳ calculate` 且结果 3293
- [ ] `python deepseek.py --json "抽取：张三 30 岁"` 输出合法 JSON
- [ ] `python deepseek.py -i` 能多轮记忆（告知姓名后追问能答对）
- [ ] §9.3 备份文件已生成
- [ ] §9.6 校验输出 `OK provider=deepseek-official ...`
- [ ] 重启后模型选择器出现 `(千帆)` 条目
- [ ] 新会话能正常流式对话
- [ ] `pwsh -File tools/check-secrets.ps1` → ✅ 无残留（**发布前最后一步**）

---

## 12. 发布前脱敏检查（发博客 / GitHub / 公众号前必做）

> 本文档涉及真实账号的模型清单与配置路径，**发布前必须跑一次脱敏检查**。

### 12.1 一条命令

```powershell
cd <DEMO_DIR>
pwsh -File tools/check-secrets.ps1
```

**验收标准**：

```
扫描目录: <DEMO_DIR>
文件数  : 10

✅ 未发现密钥或本机路径残留，可以发布。
```

退出码 0 = 可发布；1 = 有命中，**禁止发布**，按提示替换成占位符后重跑。

### 12.2 它查什么

| 规则 | 匹配对象 | 为什么要拦 |
|---|---|---|
| 百度千帆 API Key | `bce-v3/ALTAK-` + 真实字符 | 完整密钥泄漏 |
| 千帆 secret 段 | `ALTAK-xxx/` 后的 32+ 位十六进制 | 密钥被拆分泄漏 |
| OpenAI 风格 Key | `sk-` + 20 位以上 | 通用规则 |
| AWS Access Key | `AKIA` + 16 位大写 | 通用规则 |
| 私钥块 | `-----BEGIN ... PRIVATE KEY-----` | 通用规则 |
| 本机用户名路径 | `C:\Users\<真实名>\` | 暴露 Windows 用户名 |

占位符 `ALTAK-xxx` / `ALTAK-fake...` / `<你的...>` **不会**误报（已做负向断言）。

### 12.3 本仓库实测结果（2026-11-16）

```powershell
# 真实密钥特征扫描
ALTAK-gYummBEKhBSOUOqFhsxUA         → 0 次
3ba623cb...62fd1a3（secret 段）      → 0 次
32 位以上十六进制串                   → 0 个
DINGJINJIN（用户名）                 → 0 次

# 占位符出现统计（正常）
ALTAK-xxx               18 处
ALTAK-xxxxx              8 处
ALTAK-xxxxxxxxxxxxxxxxxxxx 1 处
ALTAK-fakefakefake       3 处（selftest 故意构造的假 key，用于验证 401）
```

### 12.4 四个容易漏的地方（脚本查不到，必须人工确认）

1. **聊天记录与截图**：本次开发过程中真实 key 曾在对话里明文出现过。发布博客时**不要贴对话截图**，
   也不要把"AI 帮我配 key"的过程原样贴出来。
2. **会话日志**：`<DSH_HOME>\sessions\` 下的会话文件包含完整对话，**不要打包发布**。
3. **用量账本**：`usage_ledger.jsonl` 含 `request_id` 与 prompt 片段，已在 `.gitignore` 中排除。
4. **凭证库**：`<DSH_HOME>\.credentials.yaml` 是**明文密钥库**，绝对不能出现在仓库或文章里。

### 12.5 如果已经泄露

1. 立刻到 百度智能云控制台 → 千帆 → API Key 管理，**删除该 key 并新建**。
2. 更新 `<DSH_HOME>\.credentials.yaml` 的 `refs.QIANFAN_API_KEY`。
3. 重启 Harness（凭证按请求解析，但配置改动仍需重启生效）。
4. 检查账单有无异常调用。

---

## 附录 A：全部文件内容

> 以下文件必须**逐字创建**。修改任何一处都可能导致后续验收失败。

### A.1 demo.py —— 最小演示

`````python
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
`````

### A.2 usage.py —— 用量记账与统计

`````python
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
`````

### A.3 deepseek_client.py —— DeepSeek 客户端库（双通道）

`````python
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
`````

### A.4 deepseek.py —— DeepSeek 命令行入口

`````python
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
`````

### A.5 selftest.py —— 14 项全链路自检

`````python
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
`````

### A.6 tools/read-asar.mjs —— asar 读取工具

`````javascript
// asar 读取工具（纯 Node，无依赖）—— 用于在 Electron 应用里定位内置插件源码
//
// 用法：
//   node tools/read-asar.mjs list   <app.asar> [关键字]
//   node tools/read-asar.mjs cat    <app.asar> <asar 内路径>
//   node tools/read-asar.mjs extract<app.asar> <目录前缀> <输出目录>
//
// 例：
//   node tools/read-asar.mjs list "C:\...\app.asar" dsh-llm-deepseek
//   node tools/read-asar.mjs cat  "C:\...\app.asar" /dsh/node_modules/@deepseek-ai/dsh-llm-deepseek/lib/index.js
//
// asar 结构：16 字节头 + JSON 清单 + 文件区
//   0..4   uint32 = 4
//   4..8   uint32 = 文件区起始偏移 - 8
//   8..12  uint32 = 清单区长度（含对齐填充）
//   12..16 uint32 = 清单 JSON 字符串长度
//   16..   清单 JSON
// 文件区起点 = readUInt32LE(4) + 8；每个文件的 offset 相对文件区起点。
// 注意：本仓库实测 offset 被序列化成字符串，必须 Number() 转换。

import fs from 'node:fs';
import path from 'node:path';

const [, , cmd, asarPath, a3, a4] = process.argv;

if (!cmd || !asarPath) {
  console.error('用法: node read-asar.mjs <list|cat|extract> <app.asar> [...]');
  process.exit(2);
}

const fd = fs.openSync(asarPath, 'r');
const head = Buffer.alloc(16);
fs.readSync(fd, head, 0, 16, 0);
const filesBase = head.readUInt32LE(4) + 8;
const hlen = head.readUInt32LE(12);
const hbuf = Buffer.alloc(hlen);
fs.readSync(fd, hbuf, 0, hlen, 16);
const header = JSON.parse(hbuf.toString('utf8'));

const entries = [];
(function walk(node, prefix) {
  for (const [k, v] of Object.entries(node.files || {})) {
    const p = prefix + '/' + k;
    if (v.files) walk(v, p);
    else entries.push({ p, off: Number(v.offset), size: Number(v.size) });
  }
})(header, '');

function read(entry) {
  const b = Buffer.alloc(entry.size);
  fs.readSync(fd, b, 0, entry.size, filesBase + entry.off);
  return b;
}

if (cmd === 'list') {
  const kw = a3 ? new RegExp(a3, 'i') : null;
  const hits = kw ? entries.filter((e) => kw.test(e.p)) : entries;
  console.log(`共 ${entries.length} 个文件，匹配 ${hits.length} 个`);
  for (const e of hits) console.log(String(e.size).padStart(10), e.p);
} else if (cmd === 'cat') {
  const e = entries.find((x) => x.p === a3);
  if (!e) { console.error('未找到:', a3); process.exit(1); }
  process.stdout.write(read(e));
} else if (cmd === 'extract') {
  const outDir = a4;
  let n = 0;
  for (const e of entries) {
    if (!e.p.startsWith(a3 + '/')) continue;
    const dest = path.join(outDir, e.p.replace(/^\//, ''));
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, read(e));
    n++;
  }
  console.log('已导出', n, '个文件 →', outDir);
} else {
  console.error('未知子命令:', cmd);
  process.exit(2);
}

fs.closeSync(fd);
`````

### A.7 tools/check-secrets.ps1 —— 发布前脱敏检查

`````powershell
#requires -Version 7.0
<#
.SYNOPSIS
    发布前脱敏检查 —— 扫描目录里是否残留 API Key / 密钥 / 本机用户名。

.DESCRIPTION
    用于把技术文档、示例代码公开发布（博客 / GitHub / 公众号）之前的最后一道闸。
    命中即退出码 1，可直接挂到 CI 或 git pre-commit。

.PARAMETER Path
    要扫描的目录，默认是本脚本所在目录的上一级（即项目根）。

.PARAMETER Ignore
    忽略的文件名通配符，默认排除 node_modules、.git、__pycache__ 等。

.EXAMPLE
    pwsh -File tools/check-secrets.ps1
    pwsh -File tools/check-secrets.ps1 -Path D:\blog\qianfan
#>
param(
    [string]$Path = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

# 真实密钥的特征。占位符（xxx / fake / <你的...>）不算命中。
$rules = @(
    @{ Name = '百度千帆 API Key'; Regex = 'bce-v3/ALTAK-(?!x{3,}|fake)[A-Za-z0-9]{8,}'; Why = '完整 API Key' }
    @{ Name = '千帆 secret 段';    Regex = '(?<=ALTAK-[A-Za-z0-9]{6,}/)[0-9a-f]{32,}';    Why = 'Key 的 64 位 secret' }
    @{ Name = 'OpenAI 风格 Key';   Regex = '\bsk-[A-Za-z0-9]{20,}';                       Why = 'sk- 开头' }
    @{ Name = 'AWS Access Key';    Regex = '\bAKIA[0-9A-Z]{16}\b';                        Why = 'AWS' }
    @{ Name = '私钥块';            Regex = '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'; Why = 'PEM' }
    @{ Name = '本机用户名路径';    Regex = 'C:\\Users\\(?!<|xxx|\$env)[A-Za-z0-9._-]{3,}\\'; Why = '会暴露你的 Windows 用户名' }
)

$skipDirs = @('node_modules', '.git', '__pycache__', '.venv', 'dist', 'build')
$skipGlobs = @('*.pyc', '.env', '*.jsonl', '*.exe', '*.zip')

$files = Get-ChildItem -LiteralPath $Path -Recurse -File -Force | Where-Object {
    $rel = $_.FullName.Substring($Path.Length)
    $segments = $rel -split '[\\/]'
    if ($segments | Where-Object { $skipDirs -contains $_ }) { return $false }
    foreach ($g in $skipGlobs) {
        if ($_.Name -like $g) { return $false }
    }
    $_.Length -lt 5MB
}

Write-Host "扫描目录: $Path" -ForegroundColor Cyan
Write-Host "文件数  : $($files.Count)" -ForegroundColor Cyan
Write-Host ""

$findings = @()
foreach ($f in $files) {
    $text = Get-Content -LiteralPath $f.FullName -Raw -Encoding utf8
    if (-not $text) { continue }
    $lines = $text -split "`r?`n"
    for ($i = 0; $i -lt $lines.Count; $i++) {
        foreach ($rule in $rules) {
            $m = [regex]::Match($lines[$i], $rule.Regex)
            if ($m.Success) {
                $findings += [pscustomobject]@{
                    File = [System.IO.Path]::GetRelativePath($Path, $f.FullName)
                    Line = $i + 1
                    Rule = $rule.Name
                    Why  = $rule.Why
                    Snip = $m.Value.Substring(0, [Math]::Min(48, $m.Value.Length))
                }
            }
        }
    }
}

if ($findings.Count -eq 0) {
    Write-Host "✅ 未发现密钥或本机路径残留，可以发布。" -ForegroundColor Green
    exit 0
}

Write-Host "❌ 发现 $($findings.Count) 处可疑内容，禁止发布：" -ForegroundColor Red
Write-Host ""
$findings | Format-Table File, Line, Rule, Why, Snip -AutoSize | Out-String -Width 200 | Write-Host
Write-Host "处理方式：把命中内容替换成占位符（如 bce-v3/ALTAK-xxxxx/xxxxx），" -ForegroundColor Yellow
Write-Host "         或把 <用户名> 换成 <USER>，然后重新运行本脚本。" -ForegroundColor Yellow
exit 1
`````

### A.8 .gitignore

`````text
usage_ledger.jsonl
.env
*.pyc
__pycache__/
`````

### A.9 cordis.patch.yml（实测版本，路径 <DSH_HOME>/profiles/desktop/）

`````yaml
# Your patch layer for this dsh profile, applied after every bundle layer:
# a top-level YAML array of loader patch entries (id-targeted config
# overrides, disables, and insert lists; `!!js` expressions allowed).

# ── 用百度千帆（Qianfan）跑 DeepSeek ────────────────────────────────────────
# dsh-llm-deepseek 走的是 Anthropic Messages 协议，而千帆正好提供了
# 兼容端点 https://qianfan.baidubce.com/anthropic （/v1/messages）。
# 这里把默认的 DeepSeek 官方路由 baseURL 指到千帆，key 从凭证库的
# QIANFAN_API_KEY 取（已写入 ~/.dsh/.credentials.yaml 的 refs）。
# 想恢复官方路由：把下面这条整块删掉即可。
- id: llm-deepseek
  name: "@deepseek-ai/dsh-llm-deepseek-api-key"
  config:
    baseURL: https://qianfan.baidubce.com/anthropic
    apiKeyEnv: QIANFAN_API_KEY
    maxTokens: 32768
    thinking: enabled
    reasoningEffort: max
    models:
      - id: deepseek-v4-pro
        name: DeepSeek V4 Pro (千帆)
        contextWindow: 1000000
        maxTokens: 32768
        inputModalities:
          - text
      - id: deepseek-v4-flash-0731
        name: DeepSeek V4 Flash (千帆)
        contextWindow: 1000000
        maxTokens: 32768
        inputModalities:
          - text
      - id: deepseek-v4.1-flash-1017
        name: DeepSeek V4.1 Flash (千帆)
        contextWindow: 1000000
        maxTokens: 32768
        inputModalities:
          - text

- id: ui-settings-account
  name: "@deepseek-ai/dsh-client-ui-settings-account"
  config:
    version: 1
    step: done
    purpose: development
    process: compact
    completion: completed
    usage: detailed
    developerTools: true
- id: ui-chat
  name: "@deepseek-ai/dsh-client-ui-chat"
  config:
    transcriptView: compact
    performanceUsage: compact
    foldedReplies: final
- id: ui-settings
  name: "@deepseek-ai/dsh-client-ui-settings"
  config:
    enabled: true
- id: agent-default-model
  name: "@deepseek-ai/dsh-agent-default-model"
  config:
    provider: deepseek-account
    model: deepseek-flash
    reasoningEffort: high
- id: permission
  name: "@deepseek-ai/dsh-permission-presets"
  config:
    presets:
      read-only:
        sandbox: read-only
        approval: ask
      workspace-write:
        sandbox: workspace-write
        approval: ask
      danger-full-access:
        sandbox: danger-full-access
        approval: never
    defaultPreset: danger-full-access
- id: ui-conversation
  name: "@deepseek-ai/dsh-client-ui-conversation"
  config:
    busyEnter: steer
`````

### A.10 .credentials.yaml（模板，路径 <DSH_HOME>/.credentials.yaml）

`````yaml
version: 1
refs:
  QIANFAN_API_KEY: <你的 bce-v3/ALTAK-..../.... 整串>
records:
  # ↓ 保留原文件全部内容，不要删
  client-connection/browser-session:
    kind: grant
    payload:
      version: 1
      secret: <原值>
  deepseek-account-platform/device:
    kind: grant
    payload:
      id: <原值>
  deepseek-account-platform/default:
    kind: grant
    payload:
      version: 1
      token: <原值>
      issuer: https://platform.deepseek.com
`````


---

## 附录 B：实测数据快照

> 采集时间 2026-11-16，账号为文档所属用户。换账号后数值会变，**结论与流程不变**。

### B.1 模型数

`GET /v2/models` → **31 个**（chat 13 / multimodal-image 11 / embeddings 4 / text2image 2 / video 1）

### B.2 DeepSeek 四模型实测

| 模型 | 非流式 | 流式 | tools | json_schema | reasoning_content | 实测耗时 |
|---|---|---|---|---|---|---|
| `deepseek-v4-pro` | ✅ | ✅ | ✅ | ✅ | ✅ 155–376 字符 | 3–8 s |
| `deepseek-v4-pro-0813` | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| `deepseek-v4-flash-0731` | ✅ | ✅ | ✅ | ✅ | ✅ | 2–5 s |
| `deepseek-v4.1-flash-1017` | ✅ | ✅ | ✅ | ✅ | ✅ | — |

### B.3 Anthropic 兼容端点实测

| 项 | 结果 |
|---|---|
| `x-api-key` 认证 | ✅ |
| `Authorization: Bearer` 认证 | ✅ |
| `anthropic-version: 2023-06-01` | ✅ 不报错 |
| `anthropic-beta: files-api-2025-04-14` | ✅ 不报错 |
| `thinking: {type: enabled/disabled}` | ✅ 两种都生效 |
| `tools` → `tool_use` + `stop_reason: tool_use` | ✅ |
| `tool_result` 回灌 | ✅ 模型正确消费结果 |
| SSE 事件序列 | `message_start → ping → content_block_start(thinking) → deltas → content_block_stop → content_block_start(text) → deltas → content_block_stop → message_delta → message_stop`（32 个事件） |

### B.4 用量与限流实测

- 单次普通问答（无工具）：输入 9–20 tok，输出 54–175 tok（其中思考占 80–95%）
- 工具调用场景：工具定义本身约占 360–490 输入 tok
- 缓存命中：同一 system 前缀二次调用可命中 256 tok，按缓存价计费
- 限流头：`Limit-Requests: 60 / Limit-Tokens: 1,000,000`（每分钟窗口）

### B.5 Harness 接入结果

| 项 | 值 |
|---|---|
| Harness 版本 | 0.2.2-rc.1 |
| 适配器包 | `@deepseek-ai/dsh-llm-deepseek-api-key` |
| 内置条目 id | `llm-deepseek` |
| provider id | `deepseek-official`（插件内硬编码） |
| 认证头 | `x-api-key` |
| 最终请求 URL | `https://qianfan.baidubce.com/anthropic/v1/messages` |
| 配置生效方式 | 重启客户端 |
