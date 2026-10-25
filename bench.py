# -*- coding: utf-8 -*-
"""压力测试：10 万条消息下，记忆查询有多快。"""
import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "bench.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT, chat_id TEXT, user_id TEXT, role TEXT, text TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS summaries(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT, chat_id TEXT, user_id TEXT, level TEXT, period TEXT, text TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT, chat_id TEXT, user_id TEXT, fact TEXT, ts INTEGER);
CREATE INDEX IF NOT EXISTS idx_msg ON messages(platform, chat_id, user_id, ts);
CREATE INDEX IF NOT EXISTS idx_facts ON facts(platform, chat_id, user_id, ts);
CREATE INDEX IF NOT EXISTS idx_sum ON summaries(platform, chat_id, user_id, ts);
"""

import os
N = int(os.environ.get('BENCH_N', '100000'))
USERS = 20


def main() -> None:
    if DB.exists():
        DB.unlink()
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    now = int(time.time())
    rows = []
    for i in range(N):
        u = f"user{i % USERS}"
        rows.append(("qq", "group-1", u, "user" if i % 2 == 0 else "assistant",
                     f"这是第{i}条消息，聊的是猫和相机", now - (N - i) * 30))
    t0 = time.time()
    conn.executemany("INSERT INTO messages(platform,chat_id,user_id,role,text,ts) VALUES(?,?,?,?,?,?)", rows)
    facts = [("qq", "group-1", f"user{i % USERS}", f"事实{i}", now - i * 60) for i in range(3000)]
    conn.executemany("INSERT INTO facts(platform,chat_id,user_id,fact,ts) VALUES(?,?,?,?,?)", facts)
    summs = [("qq", "group-1", f"user{i % USERS}", "monthly", "2026-09", f"九月摘要{i}", now - i * 3600) for i in range(300)]
    conn.executemany("INSERT INTO summaries(platform,chat_id,user_id,level,period,text,ts) VALUES(?,?,?,?,?,?,?)", summs)
    conn.commit()
    print(f"写入 {N} 条消息 + {len(facts)} 条事实 + {len(summs)} 条摘要：{time.time() - t0:.2f}s")

    def timed(label, sql, args, rounds=200):
        t = time.time()
        for _ in range(rounds):
            conn.execute(sql, args).fetchall()
        per = (time.time() - t) / rounds * 1000
        print(f"{label:26s} {per:7.3f} ms/次")
        return per

    print("\n== 单次查询耗时（20 用户、10 万条消息）==")
    timed("facts 取 12 条", "SELECT fact FROM facts WHERE platform=? AND chat_id=? AND user_id=? ORDER BY ts DESC LIMIT 12", ("qq", "group-1", "user3"))
    timed("summaries 取 3 条", "SELECT text FROM summaries WHERE platform=? AND chat_id=? AND user_id=? ORDER BY ts DESC LIMIT 3", ("qq", "group-1", "user3"))
    timed("最近 8 条消息", "SELECT role,text,ts FROM messages WHERE platform=? AND chat_id=? AND user_id=? ORDER BY ts DESC LIMIT 8", ("qq", "group-1", "user3"))
    timed("模糊搜关键词（LIKE）", "SELECT text FROM messages WHERE user_id=? AND text LIKE ? ORDER BY ts DESC LIMIT 5", ("user3", "%猫%"))
    timed("某个月的消息条数", "SELECT COUNT(*) FROM messages WHERE user_id=? AND ts BETWEEN ? AND ?", ("user3", now - 30 * 86400, now))

    size = DB.stat().st_size / 1024 / 1024
    print(f"\n数据库体积：{size:.1f} MB / 10 万条")
    conn.close()


if __name__ == "__main__":
    main()


