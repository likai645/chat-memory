## DeepSeek 长期记忆插件 v0.1.0

> ⚠️ **只建议私人使用，不建议接入群聊**（多人混在一起，隐私和归属都处理不好）。

给聊天机器人（QQ / 微信 / 抖音 / Discord）用的**跨上下文记忆服务**。纯 Python 标准库，不联网，数据全在本地。

### 三个理由

- **不会忘**：每天存档，月底归档，重启不丢，问旧事能翻出原文
- **不会拖垮宿主**：服务挂了客户端返回空记忆，聊天照常
- **不绑平台**：一段 JSON 就能接，平台字段随便填

### 下载哪个

| 文件 | 适合谁 |
|---|---|
| chat-memory-win64.zip | Windows 用户，解压双击 exe 就能用 |
| Source code | 开发者，`pip install .` 或直接跑 py |

### 实测数据

- 100 万条消息：召回 0.1 ms，数据库 116 MB
- 11 项回归测试全过，含「服务重启后记忆不丢」的真机演练
- 同一条消息重复推送不会重复入库

### 快速开始

```bash
python demo_run.py      # 看它怎么记、怎么查
python tests.py         # 跑测试
python memory_service.py serve --port 5299
```

接进自己的 bot：

```python
from client import Memory
mem = Memory("http://127.0.0.1:5299")
memory = mem.recall("qq", chat=group, user=qq)   # 回消息前拿到记忆
mem.remember("qq", chat=group, user=qq, role="user", text=msg, msg_id=msg_id)
```

### 用 MCP 一行接入（推荐）

```json
{"mcpServers": {"chat-memory": {"command": "python", "args": ["路径/mcp_server.py"]}}}
`
放进任何 MCP 客户端的配置，模型即可调用 7 个记忆工具（recall / remember / batch / facts / forget / ask / hints）。

### 已知局限

事实抽取是规则版（喜欢/讨厌/住在/叫…），复杂表达会漏；没有语义检索；群聊暂不区分「谁在跟谁说话」。发布时请如实说明，别让人以为它能读懂人心。


