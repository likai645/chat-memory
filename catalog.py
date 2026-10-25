# -*- coding: utf-8 -*-
"""文件目录表：记住每一天的正文/目录在磁盘上的实际位置。

为什么需要：文件会从 days/ 搬进 months/YYYY-MM/，如果检索靠“猜路径”（逐个 glob），
月份多了会越来越慢，搬错了还查不到。这张表让定位永远是 O(1)。

表结构：
  files(day TEXT PRIMARY KEY, raw TEXT, idx TEXT, loc TEXT, updated TEXT)
  loc: days 或 2026-09 这类月份标记
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "files.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
  day TEXT PRIMARY KEY,
  raw TEXT,
  idx TEXT,
  loc TEXT,
  updated TEXT
);
"""


def _conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=10)
    conn.executescript(SCHEMA)
    return conn


def register(day: str, raw: Path | None, idx: Path | None, loc: str | None = None) -> None:
    if loc is None and raw is not None:
        loc = "days" if raw.parent.name == "days" else raw.parent.name
    with _conn() as conn:
        conn.execute(
            "INSERT INTO files(day,raw,idx,loc,updated) VALUES(?,?,?,?,?) "
            "ON CONFLICT(day) DO UPDATE SET raw=excluded.raw, idx=excluded.idx, loc=excluded.loc, updated=excluded.updated",
            (day, str(raw) if raw else "", str(idx) if idx else "", loc or "", time.strftime("%Y-%m-%d %H:%M:%S")))


def lookup(day: str) -> tuple[Path | None, Path | None]:
    """返回 (raw, idx) 两个真实存在的路径；表里没有就返回 (None, None)。"""
    if not DB.exists():
        return None, None
    with _conn() as conn:
        row = conn.execute("SELECT raw, idx FROM files WHERE day=?", (day,)).fetchone()
    if not row:
        return None, None
    raw = Path(row[0]) if row[0] else None
    idx = Path(row[1]) if row[1] else None
    if raw is not None and not raw.exists():
        raw = None
    if idx is not None and not idx.exists():
        idx = None
    return raw, idx


def move(day: str, raw: Path, idx: Path | None, loc: str) -> None:
    register(day, raw, idx, loc)


def days_in(loc: str) -> list[str]:
    if not DB.exists():
        return []
    with _conn() as conn:
        return [r[0] for r in conn.execute("SELECT day FROM files WHERE loc=? ORDER BY day", (loc,)).fetchall()]


def stats() -> dict:
    if not DB.exists():
        return {"days": 0}
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        by_loc = conn.execute("SELECT loc, COUNT(*) FROM files GROUP BY loc ORDER BY loc").fetchall()
    return {"days": total, "by_loc": dict(by_loc)}
