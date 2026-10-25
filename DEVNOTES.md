# 聊天记忆服务（MVP）

给任何聊天 bot 用的“跨上下文记忆”。不绑平台、不联网、数据全在本地。

## 跑起来

```bash
python memory_service.py serve --port 5299     # 起服务
python memory_service.py demo                  # 看一段假对话的记忆效果
python memory_service.py facts  --user alice   # 查某个人被记住了什么
python memory_service.py forget --user alice   # 删掉某个人的全部记忆
```

数据库是同目录的 `memory.db`（SQLite），删掉即清空。

## 接口（HTTP，JSON）

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/health` | 存活检查 |
| POST | `/remember` | `{platform, chat, user, role, text}` 存一条消息，顺便抽事实 |
| POST | `/recall` | `{platform, chat, user}` 返回一段“该注入的记忆” |
| POST | `/compact` | `{platform, chat, user}` 把 7 天前的对话压成摘要 |
| POST | `/facts` | `{platform, chat, user}` 列出记住的事实 + 消息条数 |
| POST | `/forget` | `{platform, chat, user}` 删掉这个人的全部记忆 |

接入方式（伪代码）：

```python
mem = recall(platform="qq", chat=group_id, user=user_id)["memory"]
reply = llm(system=persona + "\n" + mem, user=msg)
remember(platform="qq", chat=group_id, user=user_id, role="user", text=msg)
remember(platform="qq", chat=group_id, user=user_id, role="assistant", text=reply)
```

## 当前实现到哪一步

- **分三层**：最近消息（原文，7 天）→ 摘要（`/compact` 生成）→ 事实（长期一行一条）
- **注入预算**：单次最多 700 字符，超了从头部截断
- **事实抽取**：正则（我叫…/我喜欢…/讨厌…/宠物叫…/记住：…），同一句里长的优先、短的若是子串就丢
- **压缩**：抽取式（挑对方说的前几句），**没有调模型**——这是 MVP 的取舍

## 还没做 / 下一步

1. 压缩改成“模型摘要”，质量会明显更好，但要花 token，需要配一个便宜模型
2. 群聊里“谁在跟谁说话”的归属（现在按 user_id 一人一份）
3. 记忆的“遗忘曲线”：越久的事权重越低，而不是简单按时间切
4. 冲突处理：同一件事前后说法不同（“我住杭州” vs “我搬去上海了”）
5. 隐私开关：敏感话题（地址、电话、密码）自动不入库

---

# layered.py — 三层按天记忆（按 2026-10-26 的规则）

```
第三层 data/raw/YYYY-MM-DD.md    当天完整整理文档（不删、不压）
第二层 data/index/YYYY-MM-DD.json 精细目录：摘要 + 关键词 + 事实 + 可直接回答的条目
第一层 context()                 开场注入：昨天全文 + 更早各天的目录行（上限 3500 字符）
```

读取规则：
- 第 N 天：**直接读 N-1 全部内容**
- N-2 及更早：平时不读；用户问到先查目录
- 目录命中（分数 ≥4）→ 直接用目录回答
- 目录不够 → 下钻该天 raw 原文找句子

命令：
```bash
python layered.py demo                                  # 三天模拟，看三种命中路径
python layered.py ingest --day 2026-10-26 --who 用户 --text "......"
python layered.py seal   --day 2026-10-26               # 生成第三层文档 + 第二层目录
python layered.py context --now 2026-10-27              # 看开场会注入什么
python layered.py ask --now 2026-10-27 --q "猫叫什么"    # 查过去
```

实测三种路径（demo 输出）：
| 问法 | 命中 | 结果 |
|---|---|---|
| 我那只猫叫什么（前天） | 目录 | 直接答"猫叫煤球" |
| 那本书后半段讲了啥（前天，目录没有） | 原文 | 翻出两句原话 |
| 昨天西湖边怎么样（昨天） | 上下文 | 指出已在上下文里 |

---

# archive.py — 周档 / 月档

规则：**7 天封一个周档，4 个周档（28 天）归进一个月份文件夹**，月份按年月命名。

`
data/
  live/                              当期（没满 7 天）按天写
    2026-10-27.md
    index/2026-10-27.json
  weeks/                             满 7 天封一个周档
    2026-10-20_2026-10-26/
      days/2026-10-20.md ...         当天原文
      days/index/2026-10-20.json     当天目录
      WEEK-INDEX.md                  7 天目录合并
      week.json
  months/                            4 个周档凑够就归月
    2026-10/
      weeks/2026-10-20_2026-10-26/ ...
      MONTH-INDEX.md                 月目录（含周目录、事实、关键词）
`

命令：
```bash
python archive.py seal-week --start 2026-10-20   # 把 live 里这 7 天收进周档
python archive.py rollup    --month 2026-10     # 4 个周档归进月份文件夹
python archive.py tree                          # 看结构
```

**归档不影响回忆**：layered.py 的 ind_raw / ind_index 会按
live → weeks/*/days → months/*/weeks/*/days 顺序找。实测把 10-24 归档进月文件夹之后，
问“我那只猫叫什么”照样命中目录、答出“猫叫煤球”。

## 月归档布局（2026-10-26 定稿）

当月两个文件（正文 + 目录）平铺在 days/；月底整月搬进 months/YYYY-MM/，按天平铺：

`
data/
  days/
    2026-10-26.md              当月正文
    index/2026-10-26.json      当月目录
  months/2026-09/
    2026-09-15.md              该日正文
    2026-09-15.index.json      该日目录
    ...
    MONTH-INDEX.md             月目录
`

一个月约 60 个文件（30 天 × 2）+ 1 个月目录。
实测：9 月 16 天归档后 → 33 个文件，days/ 剩 19 天；查 9-23 的“猫”仍命中（走月文件夹）。

## 三条保险（2026-10-26 补）

1. **目录表 data/files.db**：catalog.py 记着每天正文/目录的真实路径（iles(day, raw, idx, loc)）。
   检索先查表（O(1)），查不到才按目录结构猜，猜到了顺手登记。文件搬去月文件夹也不影响定位。
2. **搬家三保险**（rchive.close_month）：先写 MANIFEST.json → 目标已存在就报错停下（绝不覆盖）→
   搬完核对数量，对不上就报错。
3. **每天自检**（rchive.autocheck）：发现上个自然月还有日档留在 days/ 就自动归档。

实测：25 天落盘 → 目录表 25 条；归档 9 月 21 天 → 表里 2026-09: 21；冲突时返回
"目标已存在，停止归档（不覆盖）"；utocheck 能自动把遗留的 10 月档收走。

---

# profile.py — 用户画像（独立文件）

**独立的**一份文件，只记“他是什么样的人”，不跟日档混在一起。

`
data/profile/
  xiaolin.md
`

文件长这样（实测输出）：
```markdown
# 用户画像 · xiaolin

## 他明确说过的（可信）
- [喜欢] 下雨天（2026-10-20）
- [不喜欢] 排队（2026-10-20）
- [喜欢] 胶片相机（2026-10-21）

## 我猜的（可能不对，他否认就删）
- [可能喜欢] 下雨（2026-10-22：2026-10-20、2026-10-21、2026-10-22）
```

规则：
- **明确层**：从“我喜欢 / 我讨厌 / 我迷上了…”抽出来，带日期，可信
- **推断层**：跨天才算——同一件事出现在 ≥2 天且累计 ≥3 次，标“可能喜欢”，附证据日期
- 用户否认 → 我改条目或删掉；prune 可把总量压到上限（默认 60 条）
- **不自动注入**：开场不读它；只有我想找话题、或回答“他喜欢什么”时才 show / hints

命令：
```bash
python profile.py show  --user xiaolin
python profile.py learn --user xiaolin --day 2026-10-20   # 从那天原文抽偏好
python profile.py infer --user xiaolin                    # 跨天推断
python profile.py hints --user xiaolin                    # 找话题用的 3-5 条
python profile.py prune --user xiaolin --max 60
```

## 否认与删除（2026-10-26 加）

他说“我不喜欢这个 / 你记错了”时：

```bash
python profile.py forget --user xiaolin --text "吃辣"        # 直接删掉这条
python profile.py deny   --user xiaolin --text "胶片相机"    # 删掉并记成 [不喜欢]
```

实测：orget 删掉“吃辣”；deny 把“胶片相机”从 [喜欢] 改成 [不喜欢]（带当天日期）。

---

# when.py / 事实有效期 / 模型写目录（2026-10-26 凌晨补）

## 1. 口语时间 → 具体日期（when.py）

```
昨天 → 2026-10-25      上周三 → 2026-10-21     三天前 → 2026-10-23
上个月 → 2026-09（范围）  9月23号 → 2026-09-23   这个月 → 2026-10（范围）
```
layered.ask() 里先用它定位，定位到就直接读那天，不再靠关键词硬碰。
实测：问“10月21号那天聊了什么”→ 精确返回那天的原话。

## 2. 事实有效期（memory_service.py）

同一话题的新说法会让旧说法作废（**不删除**，标记 superseded，能追溯）：

| 说的话 | 结果 |
|---|---|
| 我住在杭州 → 我搬到上海了 | 杭州那条 superseded，上海 ctive |
| 我喜欢喝美式 → 我喜欢喝茶 | 美式 superseded，茶 ctive |
| 我讨厌下雨 | 独立话题，不受影响 |

话题按意思分组：地点（住在/搬到/来自）、喜欢（喜欢/爱/想买）、讨厌（讨厌/怕）、称呼（叫/是）。

## 3. 模型写目录（可选）

seal() 里加了钩子：设了环境变量就用模型写摘要，没设就退回抽取式（现在的默认）。

```
DSH_MEM_LLM_URL=https://api.deepseek.com/v1/chat/completions
DSH_MEM_LLM_KEY=sk-...
DSH_MEM_LLM_MODEL=deepseek-chat   # 可选
```

没 key 时不报错、不阻塞，静默用规则摘要（已实测）。
