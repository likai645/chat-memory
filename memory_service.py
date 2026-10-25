# -*- coding: utf-8 -*-
"""跨上下文记忆服务（MVP，标准库实现，不依赖任何平台）。

给任何聊天 bot 用：发消息前调 /recall 拿一段“该注入的记忆”，收到消息后调 /remember 存，
定时调 /compact 把旧对话压成摘要和事实。

启动：  python memory_service.py serve   [--port 5299]
演示：  python memory_service.py demo
查库：  python memory_service.py facts  --user alice
清库：  python memory_service.py forget --user alice
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "memory.db"
TOKEN_BUDGET = 700          # 单次注入的字符上限（约 500 token）
RECENT_DAYS = 7
MONTHLY_DAYS = 56

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT, chat_id TEXT, user_id TEXT, role TEXT, text TEXT, ts INTEGER,
  msg_id TEXT, name TEXT, kind TEXT DEFAULT 'text');
CREATE TABLE IF NOT EXISTS summaries(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT, chat_id TEXT, user_id TEXT, level TEXT, period TEXT, text TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS facts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT, chat_id TEXT, user_id TEXT, fact TEXT, ts INTEGER,
  UNIQUE(platform, chat_id, user_id, fact));
CREATE INDEX IF NOT EXISTS idx_msg ON messages(platform, chat_id, user_id, ts);
CREATE UNIQUE INDEX IF NOT EXISTS idx_msgid ON messages(platform, chat_id, msg_id) WHERE msg_id IS NOT NULL AND msg_id<>'';
CREATE INDEX IF NOT EXISTS idx_chat ON messages(platform, chat_id, ts);
"""

FACT_PATTERNS = [
    r"我(?:叫|是)\s*[\u4e00-\u9fa5A-Za-z0-9]{1,12}",
    r"我(?:喜欢|爱|讨厌|怕|想要|想买|住在|来自|搬到|搬去|换了)[^\n，。！？]{1,16}",
    r"我(?:的)?(?:生日|生天)是?[^\n，。！？]{1,12}",
    r"(?:猫|狗|宠物|孩子|宝宝)[^\n，。]{0,6}叫[^\s，。！？]{1,8}",
    r"(?:记住|别忘了)[:：]?\s*[^\n，。]{2,30}",
]

_lock = threading.Lock()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=10)
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(facts)").fetchall()}
    msg_cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
    for name, decl in (("msg_id", "TEXT"), ("name", "TEXT"), ("kind", "TEXT DEFAULT 'text'")):
        if name not in msg_cols:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {name} {decl}")
    for name, decl in (("topic", "TEXT"), ("status", "TEXT DEFAULT 'active'"), ("superseded_at", "INTEGER")):
        if name not in cols:
            conn.execute(f"ALTER TABLE facts ADD COLUMN {name} {decl}")
    conn.commit()
    return conn


# 同一话题的不同说法要互相作废：住所在哪、偏好什么、叫什么
TOPIC_GROUPS = {
    "地点": ("住在", "来自", "搬到", "搬去", "换了"),
    "喜欢": ("喜欢", "爱", "想要", "想买"),
    "讨厌": ("讨厌", "怕"),
    "称呼": ("叫", "是"),
}


def topic_of(fact: str) -> str:
    for topic, words in TOPIC_GROUPS.items():
        if any(word in fact for word in words):
            return topic
    return fact[:3]


def remember(payload: dict) -> dict:
    platform = str(payload.get("platform") or "unknown")
    chat_id = str(payload.get("chat") or "dm")
    user_id = str(payload.get("user") or "someone")
    role = str(payload.get("role") or "user")
    text = str(payload.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    now = int(payload.get("ts") or time.time())
    msg_id = str(payload.get("msg_id") or "") or None
    name = str(payload.get("name") or "")
    kind = str(payload.get("kind") or "text")
    text = text[:4000]                      # 长文本截断，别把库撑爆
    with _lock, connect() as conn:
        try:
            conn.execute(
                "INSERT INTO messages(platform,chat_id,user_id,role,text,ts,msg_id,name,kind) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (platform, chat_id, user_id, role, text, now, msg_id, name, kind))
        except sqlite3.IntegrityError:
            return {"ok": True, "duplicate": True}      # 同一条消息重复推送，丢掉就行
        added = []
        if role == "user":
            found = []
            for pattern in FACT_PATTERNS:
                for match in re.finditer(pattern, text):
                    fact = match.group(0).strip().strip("，。！？、 ")
                    fact = re.sub(r"^(?:记住|别忘了)[:：]?\s*", "", fact).strip()
                    if len(fact) < 3:
                        continue
                    found.append(fact)
            # 同一段话里抽出的多条，长的优先，短的若是长的子串就丢掉
            found = sorted(set(found), key=len, reverse=True)
            keep = []
            for fact in found:
                if not any(fact in longer for longer in keep):
                    keep.append(fact)
            for fact in reversed(keep):
                topic = topic_of(fact)
                # 同一话题的新说法，把旧事实标成作废（不删，留着可追溯）
                conn.execute(
                    "UPDATE facts SET status='superseded', superseded_at=? "
                    "WHERE platform=? AND chat_id=? AND user_id=? AND topic=? "
                    "AND status='active' AND fact<>?",
                    (now, platform, chat_id, user_id, topic, fact))
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO facts(platform,chat_id,user_id,fact,ts,topic,status,superseded_at) "
                        "VALUES(?,?,?,?,?,?,'active',NULL)",
                        (platform, chat_id, user_id, fact, now, topic))
                    added.append(fact)
                except sqlite3.Error:
                    pass

            # 抽到的事实同时喂给信念层：反复确认会变成“我确信的事”
            if added:
                try:
                    import beliefs as beliefs_mod

                    stamp = time.strftime("%Y-%m-%d", time.localtime(now))
                    for fact in added:
                        beliefs_mod.tell(user_id, fact, stamp)
                except Exception:  # noqa: BLE001 - 信念层坏了不影响存记忆
                    pass
    return {"ok": True, "facts_added": added}


def remember_batch(payload: dict) -> dict:
    """导入历史对话：{"messages":[{...}, ...]}"""
    items = payload.get("messages") or []
    ok = dup = bad = 0
    for item in items:
        try:
            result = remember(item)
            if result.get("duplicate"):
                dup += 1
            elif result.get("ok"):
                ok += 1
            else:
                bad += 1
        except Exception:  # noqa: BLE001 - 一条坏消息不影响整批
            bad += 1
    return {"ok": True, "stored": ok, "duplicate": dup, "failed": bad, "total": len(items)}


def recent_messages(conn, platform, chat_id, user_id, limit=8):
    rows = conn.execute(
        "SELECT role, text, ts FROM messages WHERE platform=? AND chat_id=? AND user_id=? "
        "ORDER BY ts DESC LIMIT ?", (platform, chat_id, user_id, limit)).fetchall()
    return list(reversed(rows))


def recall(payload: dict) -> dict:
    platform = str(payload.get("platform") or "unknown")
    chat_id = str(payload.get("chat") or "dm")
    user_id = str(payload.get("user") or "someone")
    with _lock, connect() as conn:
        facts = [r[0] for r in conn.execute(
            "SELECT fact FROM facts WHERE platform=? AND chat_id=? AND user_id=? AND status='active' ORDER BY ts DESC LIMIT 12",
            (platform, chat_id, user_id)).fetchall()]
        summaries = [r[0] for r in conn.execute(
            "SELECT text FROM summaries WHERE platform=? AND chat_id=? AND user_id=? ORDER BY ts DESC LIMIT 3",
            (platform, chat_id, user_id)).fetchall()]
        msgs = recent_messages(conn, platform, chat_id, user_id)

    lines = []
    # 信念层：比“事实”更强的一层，只有反复被确认的才进来
    try:
        import beliefs as beliefs_mod

        top = beliefs_mod.beliefs_of(user_id)[:3]
        if top:
            lines.append("【我确信的】" + "；".join(item["statement"] for item in top))
    except Exception:  # noqa: BLE001 - 没有信念层也要能跑
        pass
    if facts:
        lines.append("【我记得的他/她】" + "；".join(facts))
    if summaries:
        lines.append("【之前聊过的】" + " / ".join(summaries))
    if msgs:
        tail = " | ".join(("我" if r[0] == "assistant" else "对方") + "：" + r[1] for r in msgs[-6:])
        lines.append("【最近几句】" + tail)
    block = "\n".join(lines).strip()
    if len(block) > TOKEN_BUDGET:
        block = block[-TOKEN_BUDGET:]
    return {"ok": True, "memory": block, "chars": len(block)}


def compact(payload: dict) -> dict:
    """把 7 天前的对话压成摘要；超过 56 天的摘要压成一条事实。"""
    platform = str(payload.get("platform") or "unknown")
    chat_id = str(payload.get("chat") or "dm")
    user_id = str(payload.get("user") or "someone")
    now = int(time.time())
    cutoff = now - RECENT_DAYS * 86400
    with _lock, connect() as conn:
        rows = conn.execute(
            "SELECT role, text FROM messages WHERE platform=? AND chat_id=? AND user_id=? AND ts<? ORDER BY ts",
            (platform, chat_id, user_id, cutoff)).fetchall()
        if not rows:
            return {"ok": True, "compacted": 0}
        spoken = [t for role, t in rows if role == "user"]
        picked = spoken[:6] if spoken else [t for _r, t in rows[:6]]
        summary = "；".join(x.strip()[:24] for x in picked if x.strip())
        period = datetime.fromtimestamp(cutoff).strftime("%Y-%m-%d")
        conn.execute("INSERT INTO summaries(platform,chat_id,user_id,level,period,text,ts) VALUES(?,?,?,?,?,?,?)",
                     (platform, chat_id, user_id, "monthly", period, summary[:300], now))
    return {"ok": True, "compacted": len(rows), "summary": summary[:120]}


def facts_of(payload: dict) -> dict:
    platform = str(payload.get("platform") or "unknown")
    chat_id = str(payload.get("chat") or "dm")
    user_id = str(payload.get("user") or "someone")
    with _lock, connect() as conn:
        facts = [r[0] for r in conn.execute(
            "SELECT fact FROM facts WHERE platform=? AND chat_id=? AND user_id=? ORDER BY ts",
            (platform, chat_id, user_id)).fetchall()]
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE platform=? AND chat_id=? AND user_id=?",
            (platform, chat_id, user_id)).fetchone()[0]
    return {"ok": True, "facts": facts, "messages": count}


def forget(payload: dict) -> dict:
    platform = str(payload.get("platform") or "unknown")
    chat_id = str(payload.get("chat") or "dm")
    user_id = str(payload.get("user") or "someone")
    where = "platform=? AND chat_id=? AND user_id=?"
    args = (platform, chat_id, user_id)
    with _lock, connect() as conn:
        removed = 0
        for table in ("messages", "summaries", "facts"):
            cur = conn.execute(f"DELETE FROM {table} WHERE {where}", args)
            removed += cur.rowcount
    return {"ok": True, "removed": removed}


class Handler(BaseHTTPRequestHandler):
    routes = {"recall": recall, "remember": remember, "remember_batch": remember_batch,
              "compact": compact, "facts": facts_of, "forget": forget}

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        name = self.path.strip("/").split("?")[0]
        if name in ("", "health"):
            return self._send(200, {"ok": True, "db": str(DB)})
        self._send(404, {"ok": False, "error": f"no GET /{name}"})

    def _authorized(self) -> bool:
        import os
        expected = os.environ.get("DSH_MEM_TOKEN")
        if not expected:
            return True
        header = self.headers.get("Authorization") or ""
        return header.strip() == f"Bearer {expected}"

    def do_POST(self) -> None:
        if not self._authorized():
            return self._send(401, {"ok": False, "error": "unauthorized"})
        name = self.path.strip("/").split("?")[0]
        fn = self.routes.get(name)
        if not fn:
            return self._send(404, {"ok": False, "error": f"no POST /{name}"})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"ok": False, "error": "bad json"})
        try:
            self._send(200, fn(payload))
        except Exception as error:  # noqa: BLE001 - report, keep serving
            self._send(500, {"ok": False, "error": f"{type(error).__name__}: {error}"})

    def log_message(self, fmt: str, *args) -> None:  # keep console quiet
        return


def serve(port: int) -> None:
    try:
        import selfcheck

        report = selfcheck.selfcheck()
        selfcheck.stamp()
        print(f"self-check: {'OK' if report['ok'] else 'FAILED'}  v{report['version']} schema{report['schema']}", flush=True)
        if not report["ok"]:
            print(json.dumps(report["checks"], ensure_ascii=False), flush=True)
    except Exception as error:  # noqa: BLE001 - 自检失败也要能起服务
        print(f"self-check skipped: {error}", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"memory service on http://127.0.0.1:{port}  db={DB}", flush=True)
    server.serve_forever()


def demo() -> None:
    """喂一段假对话，看它记得什么、忘什么、翻不翻得出旧账。"""
    if DB.exists():
        DB.unlink()
    convo = [
        ("user", "我叫小林，住杭州"),
        ("assistant", "记住啦，小林，杭州。"),
        ("user", "我养了一只猫叫煤球，特别爱睡键盘上"),
        ("assistant", "煤球这名字真到位。"),
        ("user", "我讨厌加班，最近项目拖到十一点"),
        ("assistant", "听着就累。"),
        ("user", "记住：我生日是3月14"),
        ("assistant", "记下了。"),
        ("user", "今天心情还行，就是有点困"),
        ("assistant", "那就早点睡。"),
    ]
    for role, text in convo:
        remember({"platform": "demo", "chat": "dm", "user": "xiaolin", "role": role, "text": text})
    print("== 存完之后 recall ==")
    print(json.dumps(recall({"platform": "demo", "chat": "dm", "user": "xiaolin"}),
                     ensure_ascii=False, indent=1))
    print("== 事实清单 ==")
    print(json.dumps(facts_of({"platform": "demo", "chat": "dm", "user": "xiaolin"}),
                     ensure_ascii=False, indent=1))
    # 造一条 10 天前的旧消息，测试压缩
    old = int(time.time()) - 10 * 86400
    with _lock, connect() as conn:
        conn.execute("INSERT INTO messages(platform,chat_id,user_id,role,text,ts) VALUES(?,?,?,?,?,?)",
                     ("demo", "dm", "xiaolin", "user", "上次说的那个相机我想买二手，预算五千", old))
    print("== 压缩 ==")
    print(json.dumps(compact({"platform": "demo", "chat": "dm", "user": "xiaolin"}),
                     ensure_ascii=False, indent=1))
    print("== 压缩后再 recall（摘要应该出现）==")
    print(json.dumps(recall({"platform": "demo", "chat": "dm", "user": "xiaolin"}),
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["serve", "demo", "facts", "forget"])
    parser.add_argument("--port", type=int, default=5299)
    parser.add_argument("--user", default="someone")
    parser.add_argument("--chat", default="dm")
    parser.add_argument("--platform", default="cli")
    args = parser.parse_args()
    if args.cmd == "serve":
        serve(args.port)
    elif args.cmd == "demo":
        demo()
    elif args.cmd == "facts":
        print(json.dumps(facts_of({"platform": args.platform, "chat": args.chat, "user": args.user}),
                         ensure_ascii=False, indent=1))
    else:
        print(json.dumps(forget({"platform": args.platform, "chat": args.chat, "user": args.user}),
                         ensure_ascii=False, indent=1))








