# -*- coding: utf-8 -*-
"""验证：去重、批量导入、客户端容错。"""
import json
import sys
from pathlib import Path

WS = Path(r"C:\Users\douco\Documents\deepseek-harness\default-workspace")
sys.path.insert(0, str(WS / "chat-memory"))
import memory_service as m  # noqa: E402

DB = WS / "chat-memory" / "memory.db"
if DB.exists():
    DB.unlink()

base = {"platform": "qq", "chat": "g1", "user": "u1"}
print("1) 同一条消息推两次：")
print("   第一次:", m.remember(dict(base, role="user", text="我养了只猫叫煤球", msg_id="m1")))
print("   第二次:", m.remember(dict(base, role="user", text="我养了只猫叫煤球", msg_id="m1")))

print("\n2) 批量导入 5000 条：")
batch = [{"platform": "qq", "chat": "g1", "user": "u2", "role": "user",
          "text": f"第{i}条消息", "msg_id": f"b{i}"} for i in range(5000)]
print("  ", m.remember_batch({"messages": batch}))
print("   再导一次（应全是 duplicate）:")
print("  ", m.remember_batch({"messages": batch}))

print("\n3) 非文本消息（图片/语音）占位：")
print("  ", m.remember(dict(base, role="user", text="[图片]", kind="image", msg_id="m2")))
print("  ", m.remember(dict(base, role="user", text="[语音 8秒]", kind="voice", msg_id="m3")))

print("\n4) 超长消息截断：")
long_text = "啊" * 9000
m.remember(dict(base, role="user", text=long_text, msg_id="m4"))
import sqlite3
conn = sqlite3.connect(DB)
length = conn.execute("SELECT length(text) FROM messages WHERE msg_id='m4'").fetchone()[0]
print("   存进去的长度:", length)

print("\n5) recall 仍然正常：")
print("  ", m.recall(base)["memory"][:120])
