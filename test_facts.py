# -*- coding: utf-8 -*-
"""验证事实有效期：旧说法被标作废，不再出现在召回里。"""
import json
import sqlite3
import sys
from pathlib import Path

WS = Path(r"C:\Users\douco\Documents\deepseek-harness\default-workspace")
sys.path.insert(0, str(WS / "chat-memory"))
import memory_service as m  # noqa: E402

DB = WS / "chat-memory" / "memory.db"
if DB.exists():
    DB.unlink()

base = {"platform": "qq", "chat": "dm", "user": "u1"}
for text in ["我住在杭州", "我喜欢喝美式", "我讨厌下雨", "我搬到上海了", "我喜欢喝茶"]:
    print(m.remember(dict(base, role="user", text=text)))

print("\n--- recall（应只剩新说法 + 其他话题）---")
print(m.recall(base)["memory"])

print("\n--- 库里事实全貌 ---")
conn = sqlite3.connect(DB)
rows = conn.execute("SELECT fact, topic, status FROM facts ORDER BY ts").fetchall()
for fact, topic, status in rows:
    print(f"  {fact:12s} topic={topic:6s} {status}")
