# -*- coding: utf-8 -*-
"""联想式检索：一个词，牵出一串日子。

为什么需要：
  日档按月归档以后，“猫”这件事可能沉到 months/2026-09/ 里，
  按日期查得到，但按关键词硬碰会漏。联想检索解决的就是“提到 X，把相关旧事都翻出来”。

三层设计：
  1. 实体触发   实体表里存着“这个词出现在哪些天”，命中即拉齐
  2. 共现联想   同一天常一起出现的词，算相邻；从命中实体扩散一跳
  3. 语义联想   （未做）需要向量模型，成本高，留作后续

存储：data/assoc.db
  entities(name, days, hits)          实体 → 出现天数 / 次数
  mentions(entity, day, count, sample) 每个实体在某天的出现情况 + 例句
  links(a, b, weight)                 共现关系

用法：
  python assoc.py build
  python assoc.py ask --q "猫" --depth 2
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DAYS = DATA / "days"
MONTHS = DATA / "months"
DB = DATA / "assoc.db"

STOP_WORDS = {
    "我们", "你们", "他们", "什么", "怎么", "这个", "那个", "今天", "昨天", "明天",
    "时候", "一下", "一个", "没有", "不是", "还是", "就是", "可以", "已经", "觉得",
    "喜欢", "讨厌", "真的", "特别", "最近", "现在", "以后", "然后", "因为", "所以",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities(
  name TEXT PRIMARY KEY, days INTEGER, hits INTEGER, updated TEXT);
CREATE TABLE IF NOT EXISTS mentions(
  entity TEXT, day TEXT, count INTEGER, sample TEXT, PRIMARY KEY(entity, day));
CREATE TABLE IF NOT EXISTS links(
  a TEXT, b TEXT, weight INTEGER, PRIMARY KEY(a, b));
CREATE INDEX IF NOT EXISTS idx_mentions_day ON mentions(day);
CREATE INDEX IF NOT EXISTS idx_links_a ON links(a);
"""


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=10)
    conn.executescript(SCHEMA)
    return conn


def day_files() -> list[Path]:
    """所有日档：当月 + 已归档的月份。"""
    files = list(DAYS.glob("*.md"))
    files += [path for path in MONTHS.glob("*/*.md") if path.name.count("-") == 2]
    return sorted(files)


def grams(text: str) -> set[str]:
    """从一句中文里取 2–3 字候选词（去掉口水词和虚词开头）。"""
    clean = re.sub(r"[^\u4e00-\u9fa5]", " ", text)
    out: set[str] = set()
    bad_start = "了的在去买把被让给是有和跟就都也还又很太更最不没今这那昨明上下来去说看想做要会能该可能对错多少几"
    for chunk in clean.split():
        for size in (2, 3):
            for index in range(len(chunk) - size + 1):
                gram = chunk[index:index + size]
                if gram in STOP_WORDS or gram[0] in bad_start:
                    continue
                out.add(gram)
    return out


def build() -> dict:
    """重建实体表与共现关系（一天跑一次就够）。"""
    conn = connect()
    started = time.time()
    with conn:
        conn.execute("DELETE FROM entities")
        conn.execute("DELETE FROM mentions")
        conn.execute("DELETE FROM links")

        entity_days: dict[str, set[str]] = {}
        entity_hits: dict[str, int] = {}
        per_day: dict[str, set[str]] = {}

        for path in day_files():
            day = path.name.split(".")[0]
            if len(day) != 10:
                continue
            day_entities: dict[str, list[str]] = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                if "用户：" not in line:
                    continue
                body = line.split("用户：", 1)[1]
                for gram in grams(body):
                    day_entities.setdefault(gram, []).append(body.strip())
            for gram, samples in day_entities.items():
                entity_days.setdefault(gram, set()).add(day)
                entity_hits[gram] = entity_hits.get(gram, 0) + len(samples)
                conn.execute(
                    "INSERT OR REPLACE INTO mentions(entity, day, count, sample) VALUES(?,?,?,?)",
                    (gram, day, len(samples), samples[0][:120]))
            # 一天里最多取 8 个实体做共现，避免噪音爆炸
            top = sorted(day_entities, key=lambda g: len(day_entities[g]), reverse=True)[:8]
            per_day[day] = set(top)
            for i, first in enumerate(top):
                for second in top[i + 1:]:
                    a, b = sorted((first, second))
                    conn.execute(
                        "INSERT INTO links(a, b, weight) VALUES(?,?,1) "
                        "ON CONFLICT(a,b) DO UPDATE SET weight=weight+1", (a, b))

        for name, days in entity_days.items():
            conn.execute("INSERT INTO entities(name, days, hits, updated) VALUES(?,?,?,?)",
                         (name, len(days), entity_hits[name], time.strftime("%Y-%m-%d %H:%M")))
    conn.close()
    return {"ok": True, "entities": len(entity_days), "days": len(per_day),
            "seconds": round(time.time() - started, 2)}


def match_entities(query: str, limit: int = 8) -> list[tuple[str, int, int]]:
    """问句 → 命中的实体（按出现天数排序）。"""
    conn = connect()
    rows = conn.execute("SELECT name, days, hits FROM entities ORDER BY days DESC, hits DESC").fetchall()
    conn.close()
    picked = []
    single = len(query.strip()) == 1          # “猫”这种单字也要能触发
    for name, days, hits in rows:
        if len(name) < 2:
            continue
        if name in query or query in name:
            if single and name not in query and len(name) > 3:
                continue
            picked.append((name, days, hits))
        if len(picked) >= limit:
            break
    return picked


def expand(names: list[str], depth: int = 1) -> dict[str, int]:
    """从命中实体扩散：返回 {相关实体: 强度}。"""
    conn = connect()
    scores: dict[str, int] = {}
    frontier = set(names)
    for _ in range(max(0, depth)):
        next_frontier: set[str] = set()
        for name in frontier:
            for a, b, weight in conn.execute(
                    "SELECT a, b, weight FROM links WHERE a=? OR b=? ORDER BY weight DESC LIMIT 6",
                    (name, name)).fetchall():
                other = b if a == name else a
                if other in names:
                    continue
                scores[other] = scores.get(other, 0) + weight
                next_frontier.add(other)
        frontier = next_frontier
    conn.close()
    # 只留有分量的关联词：至少被两条不同的日子连过，且不是碎词
    dirty = "的了在把被给和跟就都也还又天这那上下"
    strong = {word: score for word, score in scores.items()
              if score >= 2 and len(word) >= 2 and not any(ch in word for ch in dirty)}
    return dict(sorted(strong.items(), key=lambda kv: kv[1], reverse=True)[:6])


def days_for(names: list[str], limit: int = 8, query: str = "") -> list[dict]:
    conn = connect()
    seen: dict[str, dict] = {}
    for name in names:
        for day, count, sample in conn.execute(
                "SELECT day, count, sample FROM mentions WHERE entity=? ORDER BY day DESC LIMIT ?",
                (name, limit)).fetchall():
            slot = seen.setdefault(day, {"day": day, "score": 0, "hits": [], "sample": sample})
            slot["score"] += count
            slot["hits"].append(name)
            # 这段原话里真的出现了问的那个词，优先级要高
            if query and query.strip() and query.strip() in sample:
                slot["score"] += 5
    conn.close()
    ordered = sorted(seen.values(), key=lambda item: (-item["score"], item["day"]))
    for item in ordered:
        item["hits"] = sorted(set(item["hits"]))
    return ordered


def ask(query: str, depth: int = 1, limit: int = 5) -> dict:
    direct = match_entities(query)
    if not direct:
        expanded_only = expand([], 0)
        return {"ok": True, "level": "none", "answer": "没有联想到相关内容。",
                "entities": [], "related": [], "days": []}

    names = [name for name, _days, _hits in direct]
    related = expand(names, depth)
    days = days_for(names + list(related), limit=limit, query=query)

    if not days:
        return {"ok": True, "level": "none", "answer": "命中了实体，但没有具体日子。",
                "entities": names, "related": list(related), "days": []}

    def tidy(item: dict) -> str:
        """展示时只显示最有用的那个词：优先问句里的词，其次原话里出现的实体。"""
        key = query.strip()
        sample = item["sample"]
        if key and key in sample:
            return key
        for word in item["hits"]:
            if word in sample:
                return word
        return item["hits"][0] if item["hits"] else ""

    lines = []
    for item in days[:limit]:
        lines.append(f"- {item['day']}（提到：{tidy(item)}）{item['sample'][:60]}")
    answer = "联想到这些日子：\n" + "\n".join(lines)
    if related:
        answer += "\n\n相关的其他线索：" + "、".join(list(related)[:4])
    return {"ok": True, "level": "assoc", "answer": answer,
            "entities": names, "related": list(related),
            "days": [item["day"] for item in days[:limit]]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["build", "ask", "stats"])
    parser.add_argument("--q", default="")
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if args.cmd == "build":
        print(json.dumps(build(), ensure_ascii=False))
    elif args.cmd == "ask":
        print(json.dumps(ask(args.q, args.depth, args.limit), ensure_ascii=False, indent=1))
    else:
        conn = connect()
        total = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        links = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        conn.close()
        print(json.dumps({"entities": total, "links": links}, ensure_ascii=False))



