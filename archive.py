# -*- coding: utf-8 -*-
"""周档 / 月档归档（7 天一周，4 周一月）。

目录长这样：
  data/
    live/2026-10-27.md                 当期（还没满 7 天）按天写
    weeks/2026-10-20_2026-10-26/       满 7 天封一个周档
        days/2026-10-20.md ...         当天原文
        days/index/2026-10-20.json     当天目录
        WEEK-INDEX.md                  周目录（7 天目录合并）
    months/2026-10/                    4 个周档凑够就归档成月
        weeks/2026-10-06_2026-10-12/ ...
        MONTH-INDEX.md                 月目录

用法：
  python archive.py seal-week  --start 2026-10-20
  python archive.py rollup     --month 2026-10
  python archive.py tree
  python archive.py demo
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import date, timedelta
from pathlib import Path

import catalog

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LIVE = DATA / "live"
WEEKS = DATA / "weeks"
MONTHS = DATA / "months"


def ensure() -> None:
    for path in (LIVE, WEEKS, MONTHS):
        path.mkdir(parents=True, exist_ok=True)


def daterange(start: date, days: int = 7) -> list[str]:
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


def close_month(month: str) -> dict:
    """自然月结束时，把整月的日档一次性搬进 months/YYYY-MM/。

    三条保险：
      1. 先写清单（MANIFEST.json），搬的时候照清单走
      2. 目标已存在同名文件就报错停下，绝不覆盖
      3. 搬完核对数量，对不上就报告
    """
    ensure()
    days_dir = DATA / "days"
    idx_dir = days_dir / "index"
    target = MONTHS / month

    day_files = sorted(days_dir.glob(f"{month}-*.md"))
    if not day_files:
        return {"ok": False, "error": f"{month} 没有可归档的日档"}

    conflicts = [p.name for p in day_files if (target / p.name).exists()]
    if conflicts:
        return {"ok": False, "error": "目标已存在，停止归档（不覆盖）", "conflicts": conflicts[:5]}

    target.mkdir(parents=True, exist_ok=True)
    manifest = {
        "month": month,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "items": [{"day": p.stem,
                   "raw": p.name,
                   "idx": f"{p.stem}.index.json" if (idx_dir / f"{p.stem}.json").exists() else None}
                  for p in day_files],
    }
    (target / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    moved, missing = [], []
    for item in manifest["items"]:
        src_raw = days_dir / item["raw"]
        if not src_raw.exists():
            missing.append(item["raw"])
            continue
        shutil.move(str(src_raw), str(target / item["raw"]))
        idx_dst = None
        if item["idx"]:
            src_idx = idx_dir / f"{item['day']}.json"
            if src_idx.exists():
                shutil.move(str(src_idx), str(target / item["idx"]))
                idx_dst = target / item["idx"]
        catalog.register(item["day"], target / item["raw"], idx_dst, month)
        moved.append(item["day"])

    landed = len(list(target.glob(f"{month}-*.md")))
    if landed != len(manifest["items"]):
        return {"ok": False, "error": "搬完数量对不上", "expected": len(manifest["items"]),
                "landed": landed, "missing": missing[:5]}

    lines = [f"# {month} 月目录", "", f"共 {len(moved)} 天（已归入 months/{month}/）", ""]
    for day in moved:
        idx_path = target / f"{day}.index.json"
        if not idx_path.exists():
            lines.append(f"## {day}\n- （无目录）\n")
            continue
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
        lines.append(f"## {day}")
        if idx.get("facts"):
            lines.append("- 事实：" + "；".join(idx["facts"]))
        if idx.get("keywords"):
            lines.append("- 关键词：" + "、".join(idx["keywords"][:6]))
        summary = (idx.get("summary") or "").replace("\n", " ")[:150]
        if summary:
            lines.append("- 摘要：" + summary)
        lines.append("")
    (target / "MONTH-INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    return {"ok": True, "month": month, "days_moved": len(moved), "dir": str(target)}


def autocheck(today: str | None = None) -> dict:
    """每天跑一次：上个自然月还有日档留在 days/ 里，就自动归档。"""
    from datetime import date

    today = today or date.today().isoformat()
    first = date.fromisoformat(today).replace(day=1)
    prev = (first.replace(day=1) - timedelta(days=1))
    month = prev.strftime("%Y-%m")
    leftover = [p.name for p in (DATA / "days").glob(f"{month}-*.md")]
    if not leftover:
        return {"ok": True, "month": month, "action": "无需归档"}
    return close_month(month)


def month_index(month: str) -> dict:
    """按**自然月**生成月索引，但**不动任何文件**。

    文件永远平铺在 data/days/ 里，按日期命名；月索引只是一个“视图”，
    让检索更快，也让归档看起来有月份。
    """
    ensure()
    days_dir = DATA / "days"
    idx_dir = days_dir / "index"
    out_dir = DATA / "index" / "month"
    out_dir.mkdir(parents=True, exist_ok=True)

    days = sorted(p.stem for p in days_dir.glob(f"{month}-*.md"))
    if not days:
        return {"ok": False, "error": f"{month} 没有记录"}

    lines = [f"# {month} 月索引", "", f"共 {len(days)} 天记录（文件仍在 data/days/，没有移动）", ""]
    facts_all, words_all = [], []
    for day in days:
        idx_path = idx_dir / f"{day}.json"
        if not idx_path.exists():
            lines.append(f"## {day}\n- （没有目录，只有原文）\n")
            continue
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
        facts = idx.get("facts", [])
        words = idx.get("keywords", [])[:6]
        facts_all.extend(facts)
        words_all.extend(words)
        lines.append(f"## {day}")
        if facts:
            lines.append("- 事实：" + "；".join(facts))
        if words:
            lines.append("- 关键词：" + "、".join(words))
        summary = (idx.get("summary") or "").replace("\n", " ")[:150]
        if summary:
            lines.append("- 摘要：" + summary)
        lines.append("")

    path = out_dir / f"{month}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return {"ok": True, "month": month, "days": len(days),
            "facts": len(facts_all), "index": str(path)}






def tree() -> str:
    out = []
    for base in (LIVE, WEEKS, MONTHS):
        if not base.exists():
            continue
        out.append(f"{base.relative_to(DATA)}/")
        for p in sorted(base.rglob("*")):
            if p.is_dir():
                out.append("  " * (len(p.relative_to(base).parts)) + p.name + "/")
            elif p.suffix in (".md", ".json"):
                out.append("  " * (len(p.relative_to(base).parts) + 1) + p.name)
    return "\n".join(out)


def demo() -> None:
    """造两个月的日档：演示「日档平铺 → 整月归档」。"""
    if DATA.exists():
        shutil.rmtree(DATA)
    ensure()
    days_dir = DATA / "days"
    idx_dir = days_dir / "index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    start = date(2026, 9, 20)
    for i in range(40):
        d = (start + timedelta(days=i)).isoformat()
        (days_dir / f"{d}.md").write_text(
            f"# {d}\n\n- [09:00:00] 用户：第 {i + 1} 天，今天做了点事\n", encoding="utf-8")
        (idx_dir / f"{d}.json").write_text(json.dumps({
            "day": d, "facts": [f"第{i + 1}天做了点事"], "keywords": ["做事"],
            "summary": f"第 {i + 1} 天，做了点事。"}, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(close_month("2026-09"), ensure_ascii=False))
    print(json.dumps(month_index("2026-10"), ensure_ascii=False))
    print("\n===== 归档后的目录结构 =====")
    print(tree())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["month-index", "close-month", "autocheck", "tree", "demo"])
    parser.add_argument("--start", default="")
    parser.add_argument("--month", default=time.strftime("%Y-%m"))
    args = parser.parse_args()
    if args.cmd == "demo":
        demo()
    elif args.cmd == "tree":
        print(tree())
    elif args.cmd == "month-index":
        print(json.dumps(month_index(args.month), ensure_ascii=False))
    elif args.cmd == "autocheck":
        print(json.dumps(autocheck(), ensure_ascii=False))
    elif args.cmd == "close-month":
        print(json.dumps(close_month(args.month), ensure_ascii=False))



