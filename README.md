# chat-memory · 聊天长期记忆

> 让聊天机器人记得住昨天。换窗口、换上下文、重启服务，都不会忘。

给 **QQ / 微信 / 抖音 / Discord / 任意聊天框架** 用的本地记忆服务。
纯 Python 标准库，不联网、不绑定平台，数据全在自己机器上。

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
