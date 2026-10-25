# -*- coding: utf-8 -*-
"""信念层：把“说过的事实”熬成“我确信的事”。

为什么需要：
  记忆只是“他说过什么”，信念是“我相信什么、有多信”。
  同一种说法被确认多次 → 置信度上升；
  出现矛盾 → 不立刻推翻，而是降置信度、标记 challenged，等更多证据。

表结构（data/beliefs.db）：
  beliefs(user, topic, statement, confidence, evidence_count, evidence_days,
          status, created, updated)

status:
  active      正常
  challenged  被矛盾过（置信度打折，还留着）
  retracted   被推翻（记录下来，供解释“我以前以为…”）

用法：
  python beliefs.py add    --user u1 --text "他养了只猫叫煤球" --day 2026-09-23
  python beliefs.py show   --user u1
  python beliefs.py doubt  --user u1 --text "他其实没有猫"
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "beliefs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS beliefs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user TEXT, topic TEXT, statement TEXT,
  confidence REAL, evidence_count INTEGER, evidence_days TEXT,
  status TEXT DEFAULT 'active', created INTEGER, updated INTEGER,
  UNIQUE(user, topic, statement));
CREATE INDEX IF NOT EXISTS idx_belief_user ON beliefs(user, status);
"""

GAIN = 0.12          # 每确认一次，置信度加多少
DECAY_ON_CONFLICT = 0.75   # 一次否认不足以推翻多次确认


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=10)
    conn.executescript(SCHEMA)
    return conn


def topic_of(statement: str) -> str:
    """粗略归题：同一件事的不同说法要能对上。"""
    groups = {
        "猫": ("猫", "煤球", "喵"),
        "狗": ("狗", "旺财", "汪"),
        "住处": ("住", "搬", "杭州", "上海", "老家"),
        "工作": ("工作", "上班", "加班", "客户", "公司", "设计"),
        "喜好": ("喜欢", "爱", "讨厌", "怕"),
        "作息": ("睡", "早起", "熬夜", "困"),
    }
    for topic, words in groups.items():
        if any(word in statement for word in words):
            return topic
    return re.sub(r"\W+", "", statement)[:4] or "杂事"


def tell(user: str, statement: str, day: str) -> dict:
    """他说了一句关于自己/世界的话，记成信念或加强已有信念。"""
    statement = statement.strip()
    if len(statement) < 2:
        return {"ok": False, "error": "太短了"}
    topic = topic_of(statement)
    now = int(time.time())
    conn = connect()
    try:
        with conn:
            row = conn.execute(
                "SELECT id, existence FROM (SELECT id, 1 AS existence FROM beliefs "
                "WHERE user=? AND topic=? AND statement=? AND status<>'retracted')",
                (user, topic, statement)).fetchone()
            if row:
                conn.execute(
                    "UPDATE beliefs SET confidence=MIN(1.0, confidence+?), "
                    "evidence_count=evidence_count+1, "
                    "evidence_days=CASE WHEN instr(evidence_days, ?)=0 "
                    "THEN evidence_days || ',' || ? ELSE evidence_days END, updated=? "
                    "WHERE id=?",
                    (GAIN, day, day, now, row[0]))
                return {"ok": True, "action": "reinforced", "topic": topic, "statement": statement}

            # 同话题有别的说法：老信念打折、标 challenged（不删，留作“我以前以为”）
            others = conn.execute(
                "SELECT id, statement, confidence FROM beliefs "
                "WHERE user=? AND topic=? AND status='active' AND statement<>?",
                (user, topic, statement)).fetchall()
            for oid, otext, oconf in others:
                conn.execute("UPDATE beliefs SET status='challenged', confidence=? WHERE id=?",
                             (max(0.1, oconf * DECAY_ON_CONFLICT), oid))

            conn.execute(
                "INSERT INTO beliefs(user, topic, statement, confidence, evidence_count, "
                "evidence_days, status, created, updated) VALUES(?,?,?,?,?,?, 'active', ?, ?) "
                "ON CONFLICT(user, topic, statement) DO UPDATE SET "
                "confidence=MIN(1.0, confidence+?), evidence_count=evidence_count+1, updated=?",
                (user, topic, statement, 0.4 if others else 0.55, 1, day, now, now, GAIN, now))
        return {"ok": True, "action": "added", "topic": topic, "statement": statement,
                "challenged": len(others)}
    finally:
        conn.close()


def beliefs_of(user: str, include_weak: bool = False) -> list[dict]:
    conn = connect()
    rows = conn.execute(
        "SELECT topic, statement, confidence, evidence_count, evidence_days, status "
        "FROM beliefs WHERE user=? AND status<>'retracted' ORDER BY confidence DESC",
        (user,)).fetchall()
    conn.close()
    out = []
    for topic, statement, conf, count, days, status in rows:
        if not include_weak and conf < 0.3:
            continue
        out.append({"topic": topic, "statement": statement, "confidence": round(conf, 2),
                    "evidence": count, "days": days, "status": status})
    return out


def doubt(user: str, statement: str) -> dict:
    """他说“不是这样”——把相关信念标受挑战，置信度打折。"""
    topic = topic_of(statement)
    conn = connect()
    changed = 0
    with conn:
        for bid, conf in conn.execute(
                "SELECT id, confidence FROM beliefs WHERE user=? AND topic=? AND status='active'",
                (user, topic)).fetchall():
            conn.execute("UPDATE beliefs SET status='challenged', confidence=? WHERE id=?",
                         (max(0.1, conf * DECAY_ON_CONFLICT), bid))
            changed += 1
    conn.close()
    return {"ok": True, "topic": topic, "challenged": changed}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["add", "show", "doubt"])
    parser.add_argument("--user", default="someone")
    parser.add_argument("--text", default="")
    parser.add_argument("--day", default=time.strftime("%Y-%m-%d"))
    args = parser.parse_args()
    if args.cmd == "add":
        print(json.dumps(tell(args.user, args.text, args.day), ensure_ascii=False))
    elif args.cmd == "doubt":
        print(json.dumps(doubt(args.user, args.text), ensure_ascii=False))
    else:
        print(json.dumps(beliefs_of(args.user, True), ensure_ascii=False, indent=1))

