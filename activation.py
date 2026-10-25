# -*- coding: utf-8 -*-
"""记忆激活：不是“命中就返回”，而是让几段记忆竞争，算出谁该浮上来。

参考那个视频里的思路（石海），落成可运行的公式：

    激活值 = 内容匹配 × 情绪关联 × 意义强度 × 身份相关性 × 时间衰减 × 回忆强化

参数都在 CONFIG 里，随时可调：
    half_life_days   半衰期：多久之后强度掉一半（默认 30 天）
    recall_boost     被想起一次的加成（默认 0.25）
    top_k            每次最多浮上来几条（默认 5）

三个派生的属性（建索引时算，存进 mentions 表）：
    emotion       情绪浓度：难过/开心/生气/累/怕…越多越高
    significance  意义强度：决定/第一次/搬家/生日/重要/最后一次…越高越重
    identity      身份相关性：我叫/我做/我喜欢/我的…越贴近“他是谁”越高
"""

from __future__ import annotations

import math
import time
from datetime import date

CONFIG = {
    "half_life_days": 30.0,
    "recall_boost": 0.25,
    "top_k": 5,
    "w_emotion": 1.0,
    "w_significance": 1.0,
    "w_identity": 1.0,
}

EMOTION_WORDS = ("难过", "难受", "开心", "高兴", "生气", "火大", "累", "烦", "怕", "焦虑",
                 "后悔", "失望", "孤独", "想哭", "哭", "笑", "喜欢", "讨厌", "爱", "恨",
                 "心疼", "委屈", "放心", "安心", "紧张", "兴奋")
SIGNIFICANCE_WORDS = ("决定", "第一次", "最后一次", "搬家", "生日", "重要", "答应", "承诺",
                      "再也不", "永远", "结婚", "分手", "辞职", "考试", "交稿", "签约",
                      "第一次", "必须", "一定要", "记住")
IDENTITY_WORDS = ("我叫", "我是", "我做", "我的", "我喜欢", "我讨厌", "我养", "我住", "我在")


def hit_ratio(text: str, words: tuple[str, ...]) -> float:
    """0–1：出现词的比例，饱和增长，避免一句里堆满情绪词就爆表。"""
    hits = sum(1 for word in words if word in text)
    return 1 - math.exp(-0.7 * hits)


def profile_scores(text: str) -> dict:
    return {
        "emotion": round(hit_ratio(text, EMOTION_WORDS), 3),
        "significance": round(hit_ratio(text, SIGNIFICANCE_WORDS), 3),
        "identity": round(hit_ratio(text, IDENTITY_WORDS), 3),
    }


FLOOR = 0.12          # 记忆不会彻底消失，只是变得很难想起


def decay(days_ago: float, half_life: float | None = None,
          significance: float = 0.0, emotion: float = 0.0) -> float:
    """指数衰减：半衰期后剩一半。

    重要的事、带情绪的事衰减更慢（这是人味所在）；再久也留一点底，不会彻底归零。
    """
    base = half_life or CONFIG["half_life_days"]
    effective = base * (1 + 2 * significance + emotion)
    if days_ago <= 0:
        return 1.0
    return max(math.pow(0.5, days_ago / effective), FLOOR)


def activation(match: float, days_ago: float, emotion: float, significance: float,
               identity: float, recalls: int, config: dict | None = None) -> float:
    config = {**CONFIG, **(config or {})}
    strengthen = 1 + config["recall_boost"] * math.log1p(max(0, recalls))
    return (match
            * (0.5 + config["w_emotion"] * emotion)
            * (0.5 + config["w_significance"] * significance)
            * (0.5 + config["w_identity"] * identity)
            * decay(days_ago, config["half_life_days"], significance, emotion)
            * strengthen)


def rank(candidates: list[dict], today: str | None = None, config: dict | None = None) -> list[dict]:
    """给候选记忆算激活值并排序。每个候选项要有 day/match/emotion/significance/identity/recalls。"""
    config = {**CONFIG, **(config or {})}
    now = date.fromisoformat(today) if today else date.today()
    for item in candidates:
        try:
            days_ago = (now - date.fromisoformat(item["day"])).days
        except (ValueError, KeyError):
            days_ago = 0
        item["activation"] = round(activation(
            float(item.get("match", 1)), max(0, days_ago),
            float(item.get("emotion", 0)), float(item.get("significance", 0)),
            float(item.get("identity", 0)), int(item.get("recalls", 0)), config), 3)
        item["days_ago"] = max(0, days_ago)
    ranked = sorted(candidates, key=lambda item: item["activation"], reverse=True)
    return ranked[:int(config["top_k"])]


if __name__ == "__main__":
    print("半衰期 30 天：", [(d, round(decay(d), 3)) for d in (0, 15, 30, 60, 180)])
    demo = [
        {"day": "2025-12-01", "match": 3, "emotion": 0.9, "significance": 0.8, "identity": 0.3, "recalls": 0},
        {"day": "2026-10-20", "match": 3, "emotion": 0.0, "significance": 0.0, "identity": 0.0, "recalls": 0},
        {"day": "2026-08-01", "match": 2, "emotion": 0.5, "significance": 0.2, "identity": 0.6, "recalls": 4},
    ]
    for row in rank(demo, today="2026-10-26"):
        print(f"  {row['day']}  天数差 {row['days_ago']:>4}  激活 {row['activation']}")

