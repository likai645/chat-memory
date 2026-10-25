# -*- coding: utf-8 -*-
"""三层日程记忆（按 douco 2026-10-26 定的规则实现）。

规则：
  第三层 raw/     每天一份完整整理文档（原始、详细、不删）
  第二层 index/   对当天 raw 的精细目录：摘要 + 关键词 + 事实 + 可回答问题
  第一层 hot      当前对话直接加载的内容

读取规则：
  · 第 N 天：直接读第 N-1 天（前一天）的全部文档
  · 第 N-2 天及更早：平时不读；用户问到才先查目录
      - 目录能答 → 直接用目录回答
      - 目录不够 → 下钻该天 raw 原文找片段
  · 每 7 天为一个存档块（archive），块内按天存

用法：
  python layered.py demo
  python layered.py ingest --day 2026-10-26 --who 用户 --text "..." 
  python layered.py seal --day 2026-10-26
  python layered.py context --now 2026-10-27
  python layered.py ask --now 2026-10-27 --q "前天说的那本书叫什么"
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path

import catalog
from when import parse_when

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "days"                 # 一天一个文件，**永不移动、永不删除**
INDEX = DATA / "days" / "index"     # 当天目录
MOVE_SRC_RAW = DATA / "raw"         # 旧版路径（兼容）
MOVE_SRC_INDEX = DATA / "index"
WEEKS = DATA / "weeks"
MONTHS = DATA / "months"
HOT = DATA / "hot.md"
ARCHIVE_DAYS = 7          # 每 7 天一个存档块
DIRECT_LOOKBACK = 1       # 只直接读“前一天”
HOT_LIMIT = 3500          # 注入上限（字符）

STOP = set("的了是在我你他她它就和与也都很有没不这那个吗呢啊吧呀么什么怎么一下一个我们你们他们".split())


def ensure_dirs() -> None:
    for path in (RAW, INDEX):
        path.mkdir(parents=True, exist_ok=True)


def find_raw(day: str) -> Path | None:
    """先查目录表（O(1)），查不到再按 days → months 猜，猜到了顺手登记。"""
    raw, idx = catalog.lookup(day)
    if raw is not None:
        return raw
    for candidate in (RAW / f"{day}.md",):
        if candidate.exists():
            catalog.register(day, candidate, find_index_fallback(day))
            return candidate
    for candidate in MONTHS.glob(f"*/{day}.md"):
        catalog.register(day, candidate, find_index_fallback(day), candidate.parent.name)
        return candidate
    for candidate in WEEKS.glob(f"*/days/{day}.md"):
        catalog.register(day, candidate, find_index_fallback(day))
        return candidate
    for candidate in MONTHS.glob(f"*/days/{day}.md"):
        catalog.register(day, candidate, find_index_fallback(day), candidate.parent.parent.name)
        return candidate
    for candidate in MONTHS.glob(f"*/weeks/*/days/{day}.md"):
        return candidate
    return None


def find_index_fallback(day: str) -> Path | None:
    """不查目录表，纯按目录结构找（给登记时用，避免递归）。"""
    for candidate in (INDEX / f"{day}.json",):
        if candidate.exists():
            return candidate
    for candidate in MONTHS.glob(f"*/{day}.index.json"):
        return candidate
    for candidate in WEEKS.glob(f"*/days/index/{day}.json"):
        return candidate
    for candidate in MONTHS.glob(f"*/days/index/{day}.json"):
        return candidate
    for candidate in MONTHS.glob(f"*/weeks/*/days/index/{day}.json"):
        return candidate
    return None


def find_index(day: str) -> Path | None:
    raw, idx = catalog.lookup(day)
    if idx is not None:
        return idx
    found = find_index_fallback(day)
    if found is not None:
        catalog.register(day, find_raw(day), found)
    return found


def all_index_days() -> list[str]:
    seen: set[str] = set()
    for base in (INDEX, WEEKS, MONTHS):
        if not base.exists():
            continue
        for path in base.rglob("*.json"):
            stem = path.name.split(".")[0]          # 兼容 2026-09-23.json 和 2026-09-23.index.json
            if len(stem) == 10 and stem[4] == "-" and stem[7] == "-":
                seen.add(stem)
    return sorted(seen)


def archiveof(day: str) -> str:
    """7 天为一个块：用该块第一天作为块名。"""
    from datetime import date, timedelta

    d = date.fromisoformat(day)
    start = d - timedelta(days=d.weekday() if ARCHIVE_DAYS != 7 else 0)
    # 按 ISO 周一为块起点，正好 7 天一块
    return start.isoformat()


def ingest(day: str, who: str, text: str, ts: str | None = None) -> dict:
    ensure_dirs()
    H = time.strftime("%H:%M:%S") if ts is None else ts
    path = RAW / f"{day}.md"
    header = f"# {day}\n\n" if not path.exists() else ""
    with path.open("a", encoding="utf-8") as f:
        if header:
            f.write(header)
        f.write(f"- [{H}] {who}：{text.strip()}\n")
    return {"ok": True, "day": day, "file": str(path)}


def keywords(text: str, limit: int = 12) -> list[str]:
    words = re.findall(r"[\u4e00-\u9fa5]{2,6}|[A-Za-z][A-Za-z0-9\-]{2,}", text)
    cleaned = []
    for w in words:
        if w in STOP or w in ("用户", "我", "对方"):
            continue
        if w.endswith(("了", "的", "着", "一下")):
            continue
        cleaned.append(w)
    counts = Counter(cleaned)
    return [w for w, _c in counts.most_common(limit)]


def query_tokens(query: str) -> dict[str, int]:
    """把问句拆成可检索碎片，二元组权重 2、单字权重 1。"""
    q = re.sub(r"[\s，。！？、,.!?]+", "", query)
    weights: dict[str, int] = {}
    for i in range(len(q) - 1):
        gram = q[i:i + 2]
        if not any(ch in STOP for ch in gram):
            weights[gram] = 2
    for ch in q:
        if ch not in STOP and "\u4e00" <= ch <= "\u9fa5":
            weights[ch] = max(weights.get(ch, 0), 1)
    for word in re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", query):
        weights[word] = 3
    return weights


def score_text(text: str, weights: dict[str, int]) -> int:
    return sum(w for token, w in weights.items() if token in text)


FACT_PATTERNS = [
    r"我(?:叫|是)[\u4e00-\u9fa5A-Za-z0-9]{1,12}",
    r"我(?:喜欢|爱|讨厌|怕|想要|想买|住在|来自)[^\n，。！？]{1,16}",
    r"我(?:的)?(?:生日|生天)是?[^\n，。！？]{1,12}",
    r"(?:猫|狗|宠物|孩子|宝宝)[^\n，。]{0,6}叫[^\s，。！？]{1,8}",
    r"(?:记住|别忘了)[:：]?\s*[^\n，。]{2,30}",
]


def facts_of(text: str) -> list[str]:
    out = []
    for pattern in FACT_PATTERNS:
        for m in re.finditer(pattern, text):
            fact = re.sub(r"^(?:记住|别忘了)[:：]?\s*", "", m.group(0).strip()).strip("，。！？、 ")
            if len(fact) >= 3 and not any(fact in o for o in out):
                out.append(fact)
    return out


def llm_summary(raw_text: str) -> str | None:
    """有模型就用模型写目录；没有就返回 None，退回抽取式。

    需要设置两个环境变量：
      DSH_MEM_LLM_URL  例如 https://api.deepseek.com/v1/chat/completions
      DSH_MEM_LLM_KEY  你的 key
      DSH_MEM_LLM_MODEL 可选，默认 deepseek-chat
    """
    import os
    import urllib.request

    url = os.environ.get("DSH_MEM_LLM_URL")
    key = os.environ.get("DSH_MEM_LLM_KEY")
    if not url or not key:
        return None
    model = os.environ.get("DSH_MEM_LLM_MODEL", "deepseek-chat")
    prompt = (
        "把下面这一天的聊天记录整理成记忆条目，给将来的自己看。要求：\n"
        "1) 只写事实，不写废话；2) 每个人物/喜好/约定都要留；3) 不超过 5 条，每条一行；\n"
        "4) 用中文；5) 不要编造记录里没有的内容。\n\n" + raw_text[:6000]
    )
    body = json.dumps({"model": model, "temperature": 0.2,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    request = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read())
        return data["choices"][0]["message"]["content"].strip()
    except Exception as error:  # noqa: BLE001 - 网络/额度问题就退回抽取式
        print(f">> LLM 摘要失败，退回抽取式：{error}", flush=True)
        return None


def seal(day: str, summary_override: str | None = None) -> dict:
    """把当天的 raw 整理成“第三层文档”，并生成“第二层精细目录”。"""
    ensure_dirs()
    raw_path = RAW / f"{day}.md"
    if not raw_path.exists():
        return {"ok": False, "error": f"没有 {day} 的记录"}
    raw = raw_path.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if ln.startswith("- [")]
    if not lines:
        return {"ok": False, "error": "当天没有内容可整理"}

    who_count = Counter()
    for ln in lines:
        m = re.match(r"- \[[^\]]+\] ([^：]+)：", ln)
        if m:
            who_count[m.group(1)] += 1

    facts = facts_of(raw)
    kws = keywords(raw)
    # 摘要：按时间顺序挑“信息量最大的前几句”（含事实或较长的发言）
    scored = sorted(lines, key=lambda ln: (any(f in ln for f in facts), len(ln)), reverse=True)
    summary_lines = [ln for ln in scored[:8]]
    summary_lines.sort(key=lambda ln: lines.index(ln))
    summary = "\n".join(summary_lines)
    generated = summary_override or llm_summary(raw)
    if generated:
        summary = generated
        summary_lines = generated.splitlines()

    index = {
        "day": day,
        "archive": archiveof(day),
        "speakers": dict(who_count),
        "lines": len(lines),
        "keywords": kws,
        "facts": facts,
        "summary": summary,
        # 目录里预生成“能直接回答的问题”，检索命中就免下钻
        "answers": {fact: fact for fact in facts},
        "summary_source": "model" if generated else "rule",
        "raw_path": str(raw_path),
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    index_path = INDEX / f"{day}.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    catalog.register(day, raw_path, index_path)
    return {"ok": True, "day": day, "lines": len(lines), "facts": len(facts),
            "keywords": kws[:8], "index": str(index_path)}


def load_index(day: str) -> dict | None:
    path = find_index(day)
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def context(now: str) -> dict:
    """返回第 N 天开场该注入的内容：前一天全文 + 更早各天的目录行。"""
    from datetime import date, timedelta

    d0 = date.fromisoformat(now)
    yesterday = (d0 - timedelta(days=DIRECT_LOOKBACK)).isoformat()

    parts = []
    yesterday_raw = find_raw(yesterday)
    if yesterday_raw is not None:
        parts.append(f"== 昨天（{yesterday}）全部内容 ==\n" + yesterday_raw.read_text(encoding="utf-8"))
    else:
        parts.append(f"== 昨天（{yesterday}）没有记录 ==")

    older = [d for d in all_index_days() if d < yesterday]
    if older:
        lines = ["== 更早的（只给目录，用户问到再翻） =="]
        for day in older[-7:]:
            idx = load_index(day) or {}
            lines.append(f"· {day}：{'；'.join(idx.get('facts', [])) or '（无明确事实）'}"
                         f"  关键词：{'、'.join(idx.get('keywords', [])[:6])}")
        parts.append("\n".join(lines))

    block = "\n\n".join(parts)
    if len(block) > HOT_LIMIT:
        block = block[:HOT_LIMIT] + "\n…（已截断）"
    return {"ok": True, "now": now, "chars": len(block), "memory": block}


def ask(now: str, query: str) -> dict:
    """用户问到过去：先查目录；目录答不上来再下钻原文。"""
    from datetime import date, timedelta

    d0 = date.fromisoformat(now)
    yesterday = (d0 - timedelta(days=DIRECT_LOOKBACK)).isoformat()
    weights = query_tokens(query)

    # 昨天的事本来就在上下文里，直接指回原文即可（要求真的提到相关词，别乱命中）
    y_raw = find_raw(yesterday)
    if y_raw is not None and weights:
        hits = sorted(((score_text(ln, weights), ln) for ln in y_raw.read_text(encoding="utf-8").splitlines()
                       if ln.startswith("- [")), reverse=True)
        hits = [ln for s, ln in hits if s >= 4][:4]
        if hits:
            return {"ok": True, "level": "yesterday", "day": yesterday,
                    "answer": "（这些是昨天的，已经在我上下文中）\n" + "\n".join(hits)}

    cutoff = yesterday
    candidates = [d for d in all_index_days() if d < cutoff]

    # 口语时间说法（昨天/上周三/上个月/9月23号）直接定位，不用关键词硬碰
    when = parse_when(query, now)
    if when:
        if when.get("span") == "range" and when.get("month"):
            month = when["month"]
            index_path = DATA / "index" / "month" / f"{month}.md"
            files = sorted(d for d in all_index_days() if d.startswith(month))
            if index_path.exists():
                body = index_path.read_text(encoding="utf-8")[:1200]
                return {"ok": True, "level": "month-index", "month": month,
                        "answer": f"（{month} 的月目录）\n" + body}
            if files:
                return {"ok": True, "level": "month", "month": month,
                        "answer": f"（{month} 有这些天的记录）" + "、".join(files)}
            return {"ok": True, "level": "none", "answer": f"{month} 没有记录。"}
        day = when.get("day")
        if day:
            raw = find_raw(day)
            if raw is not None:
                lines = [ln for ln in raw.read_text(encoding="utf-8").splitlines() if ln.startswith("- [")]
                hits = [ln for ln in lines if score_text(ln, weights) >= 4] if weights else []
                body = "\n".join(hits[:6]) if hits else "\n".join(lines[:8])
                return {"ok": True, "level": "day", "day": day,
                        "answer": f"（{day}{'，' + when['label'] if when.get('label') else ''}）\n" + body[:900]}
            # 那天没有记录就继续往下走：可能问的其实是别的事，交给目录和联想

    if not candidates:
        return {"ok": True, "level": "none", "answer": "没有更早的记录可查。"}

    best, best_score = None, 0
    for day in candidates:
        idx = load_index(day) or {}
        hay = " ".join(idx.get("facts", []) + idx.get("keywords", []) + [idx.get("summary", "")])
        score = score_text(hay, weights)
        if score > best_score:
            best, best_score = day, score

    if not best or best_score < 4:
        # 目录没命中，交给联想检索：一个词牵出一串旧日子（哪怕已归档到最底层）
        try:
            import assoc

            linked = assoc.ask(query, depth=2)
            if linked.get("days"):
                return {"ok": True, "level": "assoc", "answer": linked["answer"],
                        "entities": linked.get("entities", []), "related": linked.get("related", []),
                        "days": linked.get("days", [])}
        except Exception:  # noqa: BLE001 - 联想是加分项，坏了不影响主流程
            pass
        return {"ok": True, "level": "none", "answer": "目录里没有相关记录。"}

    idx = load_index(best) or {}
    hit_facts = [f for f in idx.get("facts", []) if score_text(f, weights) >= 2]
    if hit_facts:
        return {"ok": True, "level": "index", "day": best,
                "answer": f"（{best} 的目录）" + "；".join(hit_facts)}

    # 目录不够，下钻原文（归档后路径会变，用 find_raw 兜底）
    raw_path = Path(idx.get("raw_path", ""))
    if not raw_path.exists():
        found = find_raw(best)
        raw_path = found if found is not None else Path("")
    if not raw_path or not raw_path.exists():
        return {"ok": True, "level": "index", "day": best,
                "answer": f"（{best} 的目录）" + "；".join(idx.get("facts", []))[:200]}
    hits = []
    for ln in raw_path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("- [") and score_text(ln, weights) >= 4:
            hits.append(ln)
    if hits:
        return {"ok": True, "level": "raw", "day": best,
                "answer": f"（翻到 {best} 的原文）" + "\n".join(hits[:6])}
    return {"ok": True, "level": "index", "day": best,
            "answer": f"（{best} 的目录）" + "；".join(idx.get("facts", []))[:200]}


def demo() -> None:
    """模拟三天对话，演示：昨天全读、前天走目录、问不到再下钻。"""
    import shutil

    if DATA.exists():
        shutil.rmtree(DATA)
    ensure_dirs()

    days = {
        "2026-10-24": [
            ("用户", "我叫小林，在杭州做平面设计"),
            ("我", "记下了，小林，杭州的设计师。"),
            ("用户", "我最近在读《百年孤独》，读到一半"),
            ("我", "那本书后半段才是狠的。"),
            ("用户", "我养了一只猫叫煤球，特别爱睡键盘"),
            ("我", "煤球这名字很到位。"),
        ],
        "2026-10-25": [
            ("用户", "今天去了西湖边，人特别多"),
            ("我", "周末的西湖一向如此。"),
            ("用户", "我讨厌排队，排了四十分钟才吃上饭"),
            ("我", "下次早点去。"),
        ],
        "2026-10-26": [
            ("用户", "画完了一版分镜，眼睛要瞎了"),
            ("我", "先歇会儿眼睛。"),
            ("用户", "记住：我下周三要交稿"),
            ("我", "记下周三交稿。"),
        ],
    }
    for day, rows in days.items():
        for i, (who, text) in enumerate(rows):
            ingest(day, who, text, ts=f"{9 + i:02d}:00:00")
    for day in days:
        print(f"[封存 {day}]", json.dumps(seal(day), ensure_ascii=False))

    print("\n===== 第三天（10-26）开场，实际注入的内容 =====")
    ctx = context("2026-10-26")
    print(ctx["memory"][:1200])
    print(f"\n（注入字符数：{ctx['chars']}）")

    print("\n===== 用户问：\"我那只猫叫什么？\"（10-24 的事，走目录）=====")
    print(json.dumps(ask("2026-10-26", "我那只猫叫什么"), ensure_ascii=False, indent=1))

    print("\n===== 用户问：\"我读到一半那本书后半段讲了啥？\"（目录没有，下钻原文）=====")
    print(json.dumps(ask("2026-10-26", "读到一半那本书后半段"), ensure_ascii=False, indent=1))

    print("\n===== 用户问：\"昨天西湖边怎么样？\"（昨天，本来就在上下文里）=====")
    print(json.dumps(ask("2026-10-26", "昨天西湖边"), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cmd", choices=["demo", "ingest", "seal", "day", "context", "ask", "list", "pending"])
    parser.add_argument("--day", default=time.strftime("%Y-%m-%d"))
    parser.add_argument("--now", default=time.strftime("%Y-%m-%d"))
    parser.add_argument("--who", default="用户")
    parser.add_argument("--text", default="")
    parser.add_argument("--q", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--summary-file", default="")
    args = parser.parse_args()
    if args.cmd == "demo":
        demo()
    elif args.cmd == "ingest":
        print(json.dumps(ingest(args.day, args.who, args.text), ensure_ascii=False))
    elif args.cmd == "seal":
        override = args.summary
        if args.summary_file:
            override = Path(args.summary_file).read_text(encoding="utf-8")
        print(json.dumps(seal(args.day, override or None), ensure_ascii=False))
    elif args.cmd == "pending":
        need = []
        for day in all_index_days():
            idx = load_index(day) or {}
            if idx.get("summary_source") != "model":
                need.append(day)
        print(json.dumps({"need_model_summary": need}, ensure_ascii=False))
    elif args.cmd == "day":
        found = find_raw(args.day)
        print(found.read_text(encoding="utf-8") if found else f"没有 {args.day} 的记录")
    elif args.cmd == "context":
        print(context(args.now)["memory"])
    elif args.cmd == "ask":
        print(json.dumps(ask(args.now, args.q), ensure_ascii=False, indent=1))
    else:
        print(json.dumps({"index_days": all_index_days()}, ensure_ascii=False))








