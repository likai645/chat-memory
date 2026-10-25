# -*- coding: utf-8 -*-
"""把口语里的时间说法换成具体日期。

聊天里没人会说“2026-09-23”，说的是“昨天”“上周三”“上个月那本”。
不做这层转换，检索就只能靠关键词硬碰，经常碰不到。
"""

from __future__ import annotations

import re
from datetime import date, timedelta

WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
            "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6}


CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def cn_to_int(text: str) -> int | None:
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if "十" in text:
        head, _, tail = text.partition("十")
        tens = CN_NUM.get(head, 1) if head else 1
        ones = CN_NUM.get(tail, 0) if tail else 0
        return tens * 10 + ones
    return CN_NUM.get(text)


def parse_when(text: str, now: str) -> dict:
    """返回 {day: 'YYYY-MM-DD', span: 'day'|'range', label: 原词}，识别不了返回 {}。"""
    d0 = date.fromisoformat(now)
    text = text.strip()

    # 昨天 / 前天 / 大前天
    fixed = {"今天": 0, "昨天": 1, "前一天": 1, "前天": 2, "大前天": 3, "明日": -1, "明天": -1}
    for word, back in fixed.items():
        if word in text:
            return {"day": (d0 - timedelta(days=back)).isoformat(), "span": "day", "label": word}

    # N 天前 / N 天后
    m = re.search(r"([\d一二两三四十]+)\s*天[前以]前", text) or re.search(r"([\d一二两三四十]+)\s*天前", text)
    if m:
        n = cn_to_int(m.group(1))
        if n:
            return {"day": (d0 - timedelta(days=n)).isoformat(), "span": "day", "label": m.group(0)}
    m = re.search(r"(\d+)\s*天[之以]?[后前]", text)
    if m and "前" in m.group(0):
        return {"day": (d0 - timedelta(days=int(m.group(1)))).isoformat(), "span": "day", "label": m.group(0)}

    # 上周三 / 这周三 / 周三
    m = re.search(r"(上|这|本)?(?:个)?(?:周|星期)([一二三四五六日天1-7])", text)
    if m:
        prefix, ch = m.group(1) or "", m.group(2)
        target = WEEKDAYS.get(ch)
        if target is not None:
            delta = (d0.weekday() - target) % 7
            if prefix in ("上",):
                delta = delta + 7 if delta == 0 else delta
            day = d0 - timedelta(days=delta)
            return {"day": day.isoformat(), "span": "day", "label": m.group(0)}

    # 上个月 / 这个月 / 上上个月
    m = re.search(r"(上上|上|这|本)(?:个)?月", text)
    if m:
        prefix = m.group(1)
        offset = 2 if prefix == "上上" else (1 if prefix == "上" else 0)
        y, mo = d0.year, d0.month - offset
        while mo <= 0:
            y -= 1
            mo += 12
        return {"day": f"{y:04d}-{mo:02d}-01", "span": "range", "label": m.group(0),
                "month": f"{y:04d}-{mo:02d}"}

    # 9月23号 / 9月23日
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[号日]", text)
    if m:
        mo, dd = int(m.group(1)), int(m.group(2))
        year = d0.year
        try:
            candidate = date(year, mo, dd)
        except ValueError:
            return {}
        if candidate > d0:                      # 说未来，那就是去年
            candidate = date(year - 1, mo, dd)
        return {"day": candidate.isoformat(), "span": "day", "label": m.group(0)}

    # 2026-09-23 / 2026/9/23
    m = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if m:
        return {"day": f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
                "span": "day", "label": m.group(0)}
    return {}


if __name__ == "__main__":
    import json
    import sys

    now = sys.argv[1] if len(sys.argv) > 1 else "2026-10-26"
    for q in ["昨天说的", "前天那本书", "上周三聊的", "上个月的事", "9月23号",
              "三天前", "2026-09-12", "这个月"]:
        print(f"{q:12s} -> {json.dumps(parse_when(q, now), ensure_ascii=False)}")

