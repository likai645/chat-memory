# -*- coding: utf-8 -*-
"""用户画像：独立的一份文件，只记“他是什么样的人”，不混在日常对话里。

为什么单独放：
  · 日档是按天记的流水，画像是跨天的结论
  · 流水越写越多，结论应该越写越准、越写越短
  · 聊天时想找话题，翻这个文件就够了，不用翻几十天流水

文件：data/profile/<user>.md
  - 明确说过的偏好（我喜欢/我讨厌…）：可信
  - 我推断的偏好：标“可能”，用户否认就改或删
  - 每条带日期，方便判断“还作数吗”

用法：
  python profile.py show --user xiaolin
  python profile.py add  --user xiaolin --kind like --text "猫 · 煤球" --day 2026-09-23
  python profile.py learn --user xiaolin --day 2026-09-23   # 从那天原文里抽
  python profile.py prune --user xiaolin --max 60
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PROFILE_DIR = DATA / "likes"
DAYS = DATA / "days"
MONTHS = DATA / "months"

LIKE_PATTERNS = [
    (r"我(?:很|最|特别)?喜欢([^\n，。！？]{1,18})", "like"),
    (r"我(?:超|真的)?爱([^\n，。！？]{1,18})", "like"),
    (r"我(?:最|很|特别)?讨厌([^\n，。！？]{1,18})", "dislike"),
    (r"我(?:不|不太)喜欢([^\n，。！？]{1,18})", "dislike"),
    (r"我(?:最)?怕([^\n，。！？]{1,14})", "dislike"),
    (r"我(?:最近)?迷上了?([^\n，。！？]{1,18})", "like"),
    (r"(?:特别|最|很)喜欢([^\n，。！？]{1,14})", "like"),
    (r"([^\n，。！？]{2,12})[，,。]? *(?:我)?(?:特别|最|很)喜欢", "like"),
]

MAX_ITEMS = 60


def path_of(user: str) -> Path:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILE_DIR / f"{user}.md"


def load(user: str) -> dict:
    """返回 {explicit: [(kind, text, day)], inferred: [(kind, text, days)]}"""
    path = path_of(user)
    if not path.exists():
        return {"explicit": [], "inferred": []}
    explicit, inferred = [], []
    section = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = "explicit" if "说过" in line else ("inferred" if "猜" in line else None)
            continue
        m = re.match(r"- \[(喜欢|不喜欢|可能喜欢)\]\s*(.+?)\s*（(.+?)）\s*$", line)
        if not m or section is None:
            continue
        kind, text, meta = m.group(1), m.group(2), m.group(3)
        if section == "explicit":
            explicit.append((kind, text, meta))
        else:
            inferred.append((kind, text, meta))
    return {"explicit": explicit, "inferred": inferred}


def render(user: str, data: dict | None = None) -> str:
    data = data if data is not None else load(user)
    lines = [f"# 他喜欢的东西 · {user}", f"最后更新：{time.strftime('%Y-%m-%d %H:%M')}", "",
             "## 他明确说过的（可信）", ""]
    if not data["explicit"]:
        lines.append("- （还没有）")
    for kind, text, day in data["explicit"]:
        lines.append(f"- [{kind}] {text}（{day}）")
    lines += ["", "## 我猜的（可能不对，他否认就删）", ""]
    if not data["inferred"]:
        lines.append("- （暂时没有）")
    for kind, text, meta in data["inferred"]:
        lines.append(f"- [{kind}] {text}（{meta}）")
    lines.append("")
    return "\n".join(lines)


def save(user: str, data: dict | None = None) -> Path:
    data = data if data is not None else load(user)
    path = path_of(user)
    path.write_text(render(user, data), encoding="utf-8")
    return path


def add(user: str, kind: str, text: str, day: str, inferred: bool = False, evidence: str = "") -> dict:
    data = load(user)
    bucket = data["inferred"] if inferred else data["explicit"]
    label = "可能喜欢" if inferred else ("喜欢" if kind == "like" else "不喜欢")
    for i, (k, t, meta) in enumerate(bucket):
        if t == text:
            new_meta = meta if day in meta else f"{meta}、{day}"
            bucket[i] = (k, t, new_meta)
            save(user, data)
            return {"ok": True, "action": "updated", "text": text}
    bucket.append((label, text, f"{day}{('：' + evidence) if evidence else ''}"))
    save(user, data)
    return {"ok": True, "action": "added", "text": text}


def day_text(day: str) -> str:
    candidates = [DAYS / f"{day}.md", *MONTHS.glob(f"*/{day}.md")]
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8")
    return ""


LEAD_NOISE = ("我今天", "我昨天", "我今天买了", "我买了", "我最近", "今天", "昨天", "最近", "刚才",
              "买了一台", "买了一个", "买了一本", "一台", "一个", "一本", "一只", "养了只", "养了一只", "我养了只", "我养了一只", "真的", "特别", "很", "最")


def tidy(text: str) -> str:
    """把抽出来的句子削成“一个名字”。"""
    out = text.strip(" ，。！？、：")
    changed = True
    while changed:
        changed = False
        for prefix in LEAD_NOISE:
            if out.startswith(prefix) and len(out) > len(prefix) + 1:
                out = out[len(prefix):].strip(" ，。！？、：")
                changed = True
    return out[:12].strip()


def learn(user: str, day: str) -> dict:
    """从某天原文里抽“明确表达的偏好”，写进画像。"""
    text = day_text(day)
    if not text:
        return {"ok": False, "error": f"没有 {day} 的记录"}
    spoken = []
    for line in text.splitlines():
        if "：" in line:
            spoken.append(line.split("：", 1)[1])
    text = "\n".join(spoken) if spoken else text
    added = []
    for pattern, kind in LIKE_PATTERNS:
        for m in re.finditer(pattern, text):
            item = tidy(m.group(1))
            if len(item) < 2 or len(item) > 18:
                continue
            result = add(user, kind, item, day)
            if result["action"] == "added":
                added.append(f"{kind}:{item}")
    return {"ok": True, "day": day, "added": added}


def infer(user: str) -> dict:
    """跨天找反复出现的东西，标成“可能喜欢”（推断，不确定）。

    只看用户自己说的话，取 2–3 字片段，要求出现在 ≥2 天且累计 ≥3 次；
    已经明确写过的就不再重复推断。
    """
    days_seen: dict[str, set[str]] = {}
    counts: Counter = Counter()
    # 只挡掉无意义的词，不按单字过滤——否则“下雨天”“胶片”这种会被误杀
    stop_words = {"我们", "你们", "他们", "什么", "怎么", "这个", "那个", "今天", "时候",
                  "一下", "一个", "没有", "不是", "还是", "就是", "可以", "已经", "觉得",
                  "喜欢", "讨厌", "真的", "特别", "最近", "现在", "以后", "昨天", "明天"}

    for path in list(DAYS.glob("*.md")) + list(MONTHS.glob("*/*.md")):
        day = path.name.split(".")[0]
        if len(day) != 10:
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if "用户：" not in line:
                continue
            body = re.sub(r"[^\u4e00-\u9fa5]", " ", line.split("用户：", 1)[1])
            for n in (2, 3):
                for i in range(len(body) - n + 1):
                    gram = body[i:i + n]
                    if " " in gram or gram in stop_words or any(ch in "喜欢讨厌觉得想要" for ch in gram):
                        continue
                    counts[gram] += 1
                    days_seen.setdefault(gram, set()).add(day)

    known = {t for _k, t, _d in load(user)["explicit"]}
    picked = []
    for gram, count in counts.most_common(80):
        days = sorted(days_seen[gram])
        if len(days) < 2 or count < 3:
            continue
        # 与明确条目重复、或与已推断的近义，都跳过，别写一堆“下雨/雨天/下雨天”
        if any(gram in k for k in known):
            continue
        if any(gram in p or p in gram for p in picked):
            continue
        add(user, "like", gram, days[-1], inferred=True, evidence="、".join(days[-3:]))
        picked.append(gram)
        if len(picked) >= 8:
            break
    return {"ok": True, "inferred": picked}


def forget(user: str, text: str, deny: bool = False) -> dict:
    """他说“我不喜欢这个 / 你说错了”时：删掉这条；deny=True 则反过来记成“不喜欢”。"""
    data = load(user)
    hit = []
    for bucket in ("explicit", "inferred"):
        kept = []
        for kind, item, meta in data[bucket]:
            if text in item or item in text:
                hit.append(item)
                continue
            kept.append((kind, item, meta))
        data[bucket] = kept
    if not hit:
        return {"ok": False, "error": f"没找到“{text}”"}
    if deny:
        data["explicit"].append(("不喜欢", text, time.strftime("%Y-%m-%d")))
    save(user, data)
    return {"ok": True, "removed": hit, "denied": deny}


def prune(user: str, keep: int = MAX_ITEMS) -> dict:
    data = load(user)
    total = len(data["explicit"]) + len(data["inferred"])
    if total <= keep:
        return {"ok": True, "pruned": 0, "total": total}
    data["explicit"] = data["explicit"][-keep:]
    save(user)
    return {"ok": True, "pruned": total - keep, "total": keep}


def hints(user: str, n: int = 4) -> list[str]:
    """给“找话题”用的短清单：优先明确喜欢的，其次可能喜欢的。"""
    data = load(user)
    out = [t for k, t, _d in data["explicit"] if k == "喜欢"][:n]
    if len(out) < n:
        out += [t for k, t, _d in data["inferred"] if k == "可能喜欢"][: n - len(out)]
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["show", "add", "learn", "infer", "prune", "hints", "forget", "deny"])
    parser.add_argument("--user", default="someone")
    parser.add_argument("--kind", default="like", choices=["like", "dislike"])
    parser.add_argument("--text", default="")
    parser.add_argument("--day", default=time.strftime("%Y-%m-%d"))
    parser.add_argument("--max", type=int, default=MAX_ITEMS)
    args = parser.parse_args()
    if args.cmd == "show":
        print(render(args.user))
    elif args.cmd == "add":
        print(json.dumps(add(args.user, args.kind, args.text, args.day), ensure_ascii=False))
    elif args.cmd == "learn":
        print(json.dumps(learn(args.user, args.day), ensure_ascii=False))
    elif args.cmd == "infer":
        print(json.dumps(infer(args.user), ensure_ascii=False))
    elif args.cmd in ("forget", "deny"):
        print(json.dumps(forget(args.user, args.text, deny=args.cmd == "deny"), ensure_ascii=False))
    elif args.cmd == "prune":
        print(json.dumps(prune(args.user, args.max), ensure_ascii=False))
    else:
        print(json.dumps(hints(args.user), ensure_ascii=False))













