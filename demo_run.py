# -*- coding: utf-8 -*-
"""一键演示：从空目录跑到“能记住、能翻旧账、能写喜欢的东西”。

跑法：
    python demo_run.py

它会在 data/ 下造 6 天的假对话，然后依次做：
    1) 每天落档 + 封存（规则目录）
    2) 用“模型口吻”的摘要覆盖其中一天（示意人工/模型摘要怎么写）
    3) 查三类问题：昨天、三天前、上个月
    4) 生成「他喜欢的东西」
    5) 把上个月归档成月份文件夹，再查一次
最后打印目录结构和每次查询的结果。
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import archive  # noqa: E402
import catalog  # noqa: E402
import layered  # noqa: E402
import profile  # noqa: E402


def fake_days() -> dict[str, list[str]]:
    return {
        "2026-09-23": ["我叫小林，在杭州做设计", "我喜欢下雨天，安静", "我养了只猫叫煤球"],
        "2026-09-24": ["今天排队排了四十分钟，讨厌", "晚上读了会儿《百年孤独》"],
        "2026-10-20": ["最近在改分镜，眼睛疼", "我特别喜欢吃辣"],
        "2026-10-21": ["客户又改需求了", "我讨厌临时加班"],
        "2026-10-22": ["下雨天在家画画最舒服"],
        "2026-10-23": ["买了一台二手胶片机，特别喜欢"],
    }


def main() -> None:
    data = ROOT / "data"
    if data.exists():
        shutil.rmtree(data)
    for folder in ("days", "months", "likes"):
        (data / folder).mkdir(parents=True, exist_ok=True)

    days = fake_days()
    for day, lines in days.items():
        for line in lines:
            layered.ingest(day, "用户", line, ts="10:00:00")
        layered.seal(day)
    print(f"[1] 落档 {len(days)} 天：", json.dumps(catalog.stats(), ensure_ascii=False))

    model_summary = ("- 小林，杭州的设计师。喜欢下雨天，讨厌排队和临时加班。\n"
                     "- 养了只猫叫煤球。在读《百年孤独》。\n"
                     "- 买了一台二手胶片机，最近在改分镜。")
    layered.seal("2026-09-23", model_summary)
    print("[2] 写了模型摘要：2026-09-23")

    print("\n[3] 三种问法：")
    for query, now in [("昨天聊了什么", "2026-10-24"),
                       ("三天前聊了什么", "2026-10-26"),
                       ("上个月聊了什么", "2026-10-26"),
                       ("我那只猫叫什么", "2026-10-26")]:
        result = layered.ask(now, query)
        print(f"  {query:14s} -> [{result['level']}] {result['answer'][:90].replace(chr(10), ' / ')}")

    print("\n[4] 他喜欢的东西：")
    for day in days:
        profile.learn("xiaolin", day)
    print((data / "likes" / "xiaolin.md").read_text(encoding="utf-8"))

    print("[5] 归档 9 月并复查：", json.dumps(archive.close_month("2026-09"), ensure_ascii=False))
    print("  目录表：", json.dumps(catalog.stats(), ensure_ascii=False))
    print("  再查 9-23：", layered.ask("2026-10-26", "我那只猫叫什么")["answer"])
    print("\n[6] 待补模型摘要的天：", json.dumps(
        [d for d in layered.all_index_days()
         if (layered.load_index(d) or {}).get("summary_source") != "model"], ensure_ascii=False))


if __name__ == "__main__":
    main()
