# -*- coding: utf-8 -*-
"""测联想检索：把旧事埋进月份文件夹，再问一个词，看能不能翻出来。"""
import json
import shutil
import sys
from pathlib import Path

WS = Path(r"C:\Users\douco\Documents\deepseek-harness\default-workspace")
sys.path.insert(0, str(WS / "chat-memory"))
import archive  # noqa: E402
import assoc  # noqa: E402
import layered  # noqa: E402

data = WS / "chat-memory" / "data"
if data.exists():
    shutil.rmtree(data)

rows = {
    "2026-09-15": ["我叫小林，在杭州做设计", "我养了只猫叫煤球，特别爱睡键盘"],
    "2026-09-16": ["下雨天在家画画最舒服", "煤球一直趴在我腿上"],
    "2026-10-20": ["今天买了台二手胶片机，去西湖边拍猫"],
    "2026-10-21": ["客户又改需求，累"],
}
for day, lines in rows.items():
    for text in lines:
        layered.ingest(day, "用户", text, ts="10:00:00")
    layered.seal(day)

print("归档 9 月:", json.dumps(archive.close_month("2026-09"), ensure_ascii=False)[:80])
print("建索引  :", json.dumps(assoc.build(), ensure_ascii=False))
print()
for query in ["猫", "煤球", "胶片", "杭州"]:
    result = assoc.ask(query, depth=2)
    print(f"问「{query}」[{result['level']}]")
    print("  " + result["answer"].replace("\n", "\n  "))
    print()
