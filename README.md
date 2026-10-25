# chat-memory · 聊天长期记忆

> 让聊天机器人记得住昨天。换窗口、换上下文、重启服务，都不会忘。

给 **QQ / 微信 / 抖音 / Discord / 任意聊天框架** 用的本地记忆服务。
纯 Python 标准库，不联网、不绑定平台，数据全在自己机器上。

> [!WARNING]
> **只建议私人使用，不建议接入群聊。**
> 群里有多个人的消息混在一起，隐私、"谁在跟谁说话"的归属都处理不好。
> 当前版本按“一人一份档案”设计，私聊最稳。群聊支持等后续版本。

```bash
python demo_run.py      # 不用装任何依赖，直接跑一遍看效果
```

## 它解决什么问题

聊天模型每次开新窗口就忘干净。这个服务在**模型之外**记东西：

- 每句话存下来，抽成「事实」
- 每天一个文件，月底归档成月份文件夹
- 回消息前，取一小段相关记忆拼进 prompt（默认 ≤700 字）
- 用户问旧事，先查目录；目录不够，再翻当天原文

## 三种用法

### 1. Windows 双击即用

下载 Release 里的 `chat-memory-win64.zip` → 解压 → 双击 `chat-memory.exe`。不需要安装 Python。

### 2. pip 安装（任意系统）

```bash
pip install .
chat-memory            # 默认监听 127.0.0.1:5299
```

### 3. 源码运行

```bash
python memory_service.py serve --port 5299
python selfcheck.py        # 自检：文件、可写、库结构、导入
python tests.py           # 回归测试（11 项）
```

## 接进你自己的 bot

```python
from client import Memory, chat_hook

mem = Memory("http://127.0.0.1:5299", token="可选")

# 最简单：一个函数包完 recall → 你的模型 → remember
reply = chat_hook(mem, platform="qq", chat=group_id, user=user_id,
                  incoming=msg, llm_call=your_llm_function)

# 或者分开控制
memory = mem.recall("qq", chat=group_id, user=user_id)
reply = your_llm(system="你是助手。\n" + memory, user=msg)
mem.remember("qq", chat=group_id, user=user_id, role="user", text=msg, msg_id=msg_id)
```

**服务挂了不影响聊天**：客户端吞掉所有异常、2 秒超时，返回空记忆继续跑。

## 接口

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/remember` | 存一条消息（`msg_id` 去重） |
| POST | `/remember_batch` | 批量导入历史 |
| POST | `/recall` | 取该注入的记忆 |
| POST | `/compact` | 压缩旧对话 |
| POST | `/facts` | 列出记住的事实 |
| POST | `/forget` | 删除某人的全部记忆 |
| GET | `/health` | 存活检查 |

## 记忆怎么组织

```
data/
  days/2026-10-26.md              正文
  days/index/2026-10-26.json      目录：摘要 / 关键词 / 事实
  months/2026-09/                 月底整月归档，按天平铺
  likes/u1.md                     他喜欢的东西（独立文件）
  files.db                        文件定位表（搬家也不丢）
```

读取规则：**开场只读昨天**，更早的只在被问到时才查（先目录，后原文）。

## 摘要谁来写

1. **不配模型**：规则摘要，免费，像机器话
2. **配模型**：设环境变量，一天一次调用
```bash
DSH_MEM_LLM_URL=https://api.deepseek.com/v1/chat/completions
DSH_MEM_LLM_KEY=sk-...
```
3. **人工/外部模型写**：`python layered.py day --day 2026-09-23` 导出 → 写完用 `seal --summary "…"` 写回

## 性能（实测）

| 数据量 | 召回 | 全卡 | 写入 |
|---|---|---|---|
| 10 万条 | 0.1 ms | 11.8 MB | — |
| 100 万条 | 0.1 ms | 116 MB | 2.2 s |

## 已知局限

- 事实抽取是**规则**（我喜欢/讨厌/住在/叫…），复杂表达会漏
- 没有语义检索，同义说法可能找不到
- 群聊只按 `user` 分档案，暂不区分“谁在跟谁说话”
- 摘要默认是规则版，不是人话

## 文档

- [`PUBLISH.md`](PUBLISH.md) — 接入说明、五个「无痛」保证、安全
- [`DEVNOTES.md`](DEVNOTES.md) — 开发笔记、模块细节、踩过的坑
- `tests.py` / `e2e_bot.py` — 回归测试与真机演练

## 许可

MIT

## 用 MCP 接（最省事的“安装”方式）

mcp_server.py 是标准 MCP server（stdio，零依赖）。任何支持 MCP 的客户端加一段配置就能用：

```json
{
  "mcpServers": {
    "chat-memory": {
      "command": "python",
      "args": ["D:/chat-memory/mcp_server.py"]
    }
  }
}
```

然后模型就能直接调用 7 个工具：

| 工具 | 作用 |
|---|---|
| memory_recall | 回消息前取记忆 |
| memory_remember | 存一条消息（msg_id 去重） |
| memory_batch | 批量导入历史 |
| memory_facts | 看记住了什么 |
| memory_forget | 删掉某人的记忆 |
| memory_ask | 问过去的事（支持“昨天”“上周三”） |
| memory_hints | 找话题用的小清单 |

自测：python test_mcp.py（模拟客户端发 JSON-RPC，逐个验证工具）。

## 联想检索（assoc.py）

提到一个词，把散落在各月文件夹里的旧事都牵出来。三层：

1. **实体触发**：实体表记着“这个词出现在哪些天”，命中即拉齐（哪怕已经归档到 months/）
2. **共现联想**：同一天常一起出现的词算相邻，从命中实体扩散一跳（可 depth=2）
3. **语义联想**：未做，需要向量模型

```bash
python assoc.py build          # 建索引，一天跑一次，几十毫秒
python assoc.py ask --q "猫" --depth 2
```

实测（9 月已归档 + 10 月存档）：

| 问 | 结果 |
|---|---|
| 猫 | 2026-10-20 拍猫、2026-09-15 养猫叫煤球 |
| 煤球 | 2026-09-15、2026-09-16 两次提到 |
| 杭州 | 2026-09-15（已归档到月份文件夹，照样翻出来） |

在 layered.ask() 里已经接好：目录没命中时自动走联想，不影响原有逻辑。

### 联想什么时候触发（可调）

配置文件 data/assoc_config.json，默认：

```json
{
  "mode": "fallback",
  "cooldown_hours": 12,
  "max_per_day": 3,
  "min_days": 1
}
```

| 参数 | 含义 |
|---|---|
| mode | allback 只在查不到时联想；lways 每次都试；off 关掉 |
| cooldown_hours | 同一话题多久内不重复联想（默认 12 小时） |
| max_per_day | 一天最多联想几次（默认 3） |
| min_days | 实体至少出现在几天才算“常聊的事”（设 2 更保守） |

**为什么不用概率**：随机触发会导致“有时记得有时不记得”，体验更差，也不好复现问题。
用「冷却 + 频控 + 阈值」三个确定性的开关，行为可预期、可调试。

实测：连问两次「猫」→ 第二次返回 skipped（刚联想过了）；换话题「胶片」→ 正常联想；
一天第 4 次 → 被上限挡住。

---

## 记忆会衰减、会竞争、会被回忆强化（activation.py，v0.2）

参考「石海」那套思路，落成可运行的公式：

```
激活值 = 内容匹配 × 情绪关联 × 意义强度 × 身份相关性 × 时间衰减 × 回忆强化
```

- **时间衰减**：默认半衰期 30 天。重要的事和带情绪的事衰得慢（半衰期被拉长）；再久也留 12% 的底，**不会彻底归零**
- **情绪 / 意义 / 身份**：建索引时从原话里认（难过开心累、决定第一次搬家、我叫我做我喜欢…），存进表里
- **回忆强化**：被想起一次，ecall_count + 1，下次更容易浮上来——这就是“回忆改写记忆”
- **竞争出线**：一次最多浮上来 5 条（	op_k），按激活值排，不是命中即返回

实测（同一批数据）：

| 日子 | 情况 | 激活值 |
|---|---|---|
| 2026-08-01 | 86 天前，带情绪、被想起过 | **0.759** |
| 2025-12-01 | 329 天前，但很重（意义+情绪高） | **0.524** |
| 2026-10-20 | 6 天前，平淡小事 | 0.326 |

年多以前的重事，比上周的小事更容易被想起来。参数都在 ctivation.CONFIG 里，可调。

---

## 信念层（beliefs.py，v0.3）

记忆回答“他说过什么”，信念回答“**我相信什么、有多信**”。

- 同一句话被确认多次：每次 **+0.12** 置信度，并记下证据日期
- 出现矛盾的说法：老的**不删**，标 `challenged`，置信度打 0.75 折
- **一次否认不足以推翻三次确认**：3 次确认（0.79）遇到 1 次否认后是 0.59，仍高于新说法的 0.40
- 三档状态：`active` / `challenged`（被质疑过，还留着）/ `retracted`（被推翻）

实测：

| 说法 | 次数 | 置信度 | 状态 |
|---|---|---|---|
| 他养了只猫叫煤球 | 3 | 0.59 | challenged（被一次否认过） |
| 他其实没有猫 | 1 | 0.40 | active |

召回生成的内容会多出一段：

```
【我确信的】猫叫煤球；我住在杭州
【我记得的他/她】我住在杭州；猫叫煤球
【最近几句】…
```

命令：`python beliefs.py add/show/doubt --user u1 --text "…"`

