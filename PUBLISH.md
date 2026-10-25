# 长期记忆插件（Chat Memory）

给任何聊天机器人用的**跨上下文记忆**：记得住昨天，翻得出上个月，不会因为换窗口就忘干净。
纯 Python 标准库，不联网、不绑定平台、数据全在本地。

## 30 秒上手

```bash
python demo_run.py     # 造 6 天假对话，跑完整流程，看它怎么记、怎么查
```

真实使用：

```bash
# 1. 起一个本地服务
python memory_service.py serve --port 5299

# 2. 收消息
curl -X POST 127.0.0.1:5299/remember -H "Content-Type: application/json" \
     -d '{"platform":"qq","chat":"g1","user":"u1","role":"user","text":"我养了只猫叫煤球"}'

# 3. 回消息前取记忆，拼进你的 prompt
curl -X POST 127.0.0.1:5299/recall -H "Content-Type: application/json" \
     -d '{"platform":"qq","chat":"g1","user":"u1"}'
```

## 它怎么组织记忆

```
data/
  days/                     当月：一天一个文件（正文）
    2026-10-26.md
    index/2026-10-26.json   当天目录：摘要 / 关键词 / 事实
  months/                   月底整月搬进来，按天平铺
    2026-09/
      2026-09-23.md
      2026-09-23.index.json
      MONTH-INDEX.md
  likes/                    他喜欢的东西（独立文件，跨天累积）
    u1.md
  files.db                  文件定位表（搬家后也能 O(1) 找到）
```

**读取规则（这是设计的核心）**
- 开场只读**昨天**全文
- 更早的一律不动，用户问到才查：先查目录 → 目录不够 → 下钻那天的原文
- 一个月只碰一次：归档

## 六个模块

| 文件 | 干什么 |
|---|---|
| `memory_service.py` | HTTP 服务：`/remember` `/recall` `/compact` `/facts` `/forget` |
| `layered.py` | 三层按天记忆：`ingest` `seal` `day` `context` `ask` `pending` |
| `archive.py` | 月归档：`close-month` `month-index` `autocheck`（带清单/校验/冲突即停） |
| `catalog.py` | 文件定位表，搬家不影响检索 |
| `profile.py` | 「他喜欢的东西」：`learn` `infer` `hints` `forget` `deny` |
| `when.py` | 口语时间换算：昨天/上周三/上个月/9月23号 |

## 摘要谁来写

两条路：
1. **不配模型**：规则摘要（挑信息量大的句子）。免费，但像机器话。
2. **配模型**：设环境变量即可，一天一次调用，成本极低。
```bash
DSH_MEM_LLM_URL=https://api.deepseek.com/v1/chat/completions
DSH_MEM_LLM_KEY=sk-...
DSH_MEM_LLM_MODEL=deepseek-chat
```
也可以人工/外部模型写好后写回：
```bash
python layered.py day   --day 2026-09-23            # 导出原文
python layered.py seal  --day 2026-09-23 --summary "…"  # 写回摘要
python layered.py pending                            # 哪些天还没模型摘要
```

## 性能（实测）

10 万条：召回 0.1 ms。100 万条：召回仍是 0.1 ms，全卡 116 MB，写入 2.2 秒。

## 已知局限（别当它能读懂人心）

- 事实抽取是**规则**（我喜欢/讨厌/住在/叫…），复杂表达会漏
- 推断的喜好很保守，宁可不写也不乱写
- 没有语义检索：问“那个能拍照的玩意儿”可能找不到（除非关键词对得上）
- 群聊里只按 `user` 分档案，暂时不区分“谁在跟谁说话”

## 路线图

1. 语义检索（向量）
2. 群聊里的对话关系（谁对谁）
3. 记忆衰减权重（旧的变淡，但不删）
4. Web 面板：看某个人的记忆长什么样

---

## 无痛接入任意平台（2026-10-26 加）

client.py：一行接入，**服务挂了也不影响聊天**（所有错误吞掉，返回空）。

`python
from client import Memory, chat_hook

mem = Memory("http://127.0.0.1:5299", token="可选")

# 回消息前：拿记忆
memory = mem.recall("qq", chat=group_id, user=user_id)
reply = llm(system="你是助手。\n" + memory, user=msg)

# 收到消息：存下来（msg_id 保证重复推送不会入库两次）
mem.remember("qq", chat=group_id, user=user_id, role="user", text=msg, msg_id=msg_id)

# 最省事：一个函数包完 recall→llm→remember
chat_hook(mem, "qq", group_id, user_id, incoming, your_llm_call)
`

平台无关：platform 随便填（qq / wechat / douyin / discord …），互不串味。

### 五个“无痛”保证（都实测过）

| 问题 | 处理 | 实测 |
|---|---|---|
| 平台回调会重试，同一条推两次 | msg_id 唯一索引 | 第二次返回 duplicate: true |
| 要导入几个月历史 | /remember_batch 批量接口 | API 端 5000 条一次入库（10 万量级见 bench） |
| 图片 / 语音 / 表情 | 存占位文本 [图片]，带 kind | 正常入库，不报错 |
| 一条消息几千字 | 截断到 4000 字 | 9000 字存进去变 4000 |
| 记忆服务挂了 | 客户端吞异常、2 秒超时、单次重试 | 服务关闭时返回空字符串，聊天继续 |

### 安全

设置 DSH_MEM_TOKEN=xxx 后，所有写接口要求 Authorization: Bearer xxx；不设就是本机免密（仅监听 127.0.0.1）。
实测：无 token 的客户端写入被拒、ecall 返回空，不会抛异常。
