# -*- coding: utf-8 -*-
"""回归测试：改完代码跑一遍，确认没把别的地方弄坏。

跑法：python tests.py     （全部在临时目录里跑，不碰真实数据）

覆盖：
  1  日志落盘 + 封存 + 定位表
  2  消息去重（同一 msg_id 推两次）
  3  批量导入
  4  超长消息截断
  5  事实抽取 + 新旧说法作废
  6  口语时间换算
  7  三种问法（那天 / 目录 / 下钻原文 / 月）
  8  月归档：清单、冲突即停、归档后仍可查
  9  他喜欢的东西：抽取、找话题、否认
  10 HTTP 服务 + 客户端（含 token 与容错）
  11 自检
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

SRC = Path(__file__).resolve().parent
PASS, FAIL = [], []


def sandbox() -> Path:
    box = Path(tempfile.mkdtemp(prefix="memtest-"))
    for path in SRC.glob("*.py"):
        shutil.copy2(path, box / path.name)
    return box


def check(name: str, fn) -> None:
    try:
        fn()
        PASS.append(name)
        print(f"  ✓ {name}")
    except Exception as error:  # noqa: BLE001
        FAIL.append((name, f"{type(error).__name__}: {error}"))
        print(f"  ✗ {name} -> {type(error).__name__}: {error}")
        traceback.print_exc(limit=2)


def main() -> int:
    box = sandbox()
    sys.path.insert(0, str(box))
    print(f"沙箱：{box}\n")

    import archive
    import assoc
    import catalog
    import layered
    import memory_service
    import profile
    import selfcheck
    import when
    from client import Memory

    # ---------- 1. 落盘与封存 ----------
    def t_ingest():
        layered.ingest("2026-10-10", "用户", "我叫小林，在杭州", ts="09:00:00")
        layered.ingest("2026-10-10", "用户", "我养了只猫叫煤球", ts="09:05:00")
        result = layered.seal("2026-10-10")
        assert result["ok"], result
        assert layered.find_raw("2026-10-10") is not None
        assert layered.find_index("2026-10-10") is not None
        assert catalog.stats()["days"] >= 1

    # ---------- 2. 去重 ----------
    def t_dedupe():
        base = {"platform": "qq", "chat": "c1", "user": "u1", "role": "user",
                "text": "你好", "msg_id": "m-1"}
        first = memory_service.remember(base)
        second = memory_service.remember(base)
        assert first.get("ok") and not first.get("duplicate"), first
        assert second.get("duplicate"), second

    # ---------- 3. 批量导入 ----------
    def t_batch():
        batch = [{"platform": "douyin", "chat": "live", "user": "v1", "role": "user",
                  "text": f"弹幕{i}", "msg_id": f"d{i}"} for i in range(500)]
        result = memory_service.remember_batch({"messages": batch})
        assert result["stored"] == 500, result
        again = memory_service.remember_batch({"messages": batch})
        assert again["duplicate"] == 500, again

    # ---------- 4. 截断 ----------
    def t_truncate():
        memory_service.remember({"platform": "qq", "chat": "c1", "user": "u1",
                                 "role": "user", "text": "啊" * 9000, "msg_id": "long-1"})
        import sqlite3

        conn = sqlite3.connect(memory_service.DB)
        length = conn.execute("SELECT length(text) FROM messages WHERE msg_id='long-1'").fetchone()[0]
        conn.close()
        assert length == 4000, length

    # ---------- 5. 事实作废 ----------
    def t_supersede():
        base = {"platform": "qq", "chat": "c2", "user": "u2", "role": "user"}
        memory_service.remember(dict(base, text="我住在杭州", msg_id="f1"))
        memory_service.remember(dict(base, text="我搬到上海了", msg_id="f2"))
        memory = memory_service.recall({"platform": "qq", "chat": "c2", "user": "u2"})["memory"]
        facts_line = next((line for line in memory.splitlines() if line.startswith("【我记得")), "")
        assert "上海" in facts_line, facts_line
        # “最近几句”里保留原话是正确的，只有事实区必须作废旧说法
        assert "住在杭州" not in facts_line, facts_line

    # ---------- 6. 时间换算 ----------
    def t_when():
        assert when.parse_when("昨天的事", "2026-10-26")["day"] == "2026-10-25"
        assert when.parse_when("三天前", "2026-10-26")["day"] == "2026-10-23"
        assert when.parse_when("上周三", "2026-10-26")["day"] == "2026-10-21"
        assert when.parse_when("9月23号", "2026-10-26")["day"] == "2026-09-23"
        assert when.parse_when("上个月", "2026-10-26")["month"] == "2026-09"
        assert when.parse_when("随便聊聊", "2026-10-26") == {}

    # ---------- 7. 三种问法 ----------
    def t_ask():
        layered.ingest("2026-10-20", "用户", "我在读《百年孤独》，读到一半", ts="10:00:00")
        layered.seal("2026-10-20")
        layered.ingest("2026-10-21", "用户", "今天去西湖，人很多", ts="10:00:00")
        layered.seal("2026-10-21")

        by_date = layered.ask("2026-10-26", "10月20号那天聊了什么")
        assert by_date["level"] == "day" and "百年孤独" in by_date["answer"], by_date

        by_index = layered.ask("2026-10-26", "我那只猫叫什么")
        assert by_index["level"] in ("index", "raw"), by_index
        assert "煤球" in by_index["answer"], by_index

        yesterday = layered.ask("2026-10-22", "昨天聊了什么")
        assert yesterday["level"] == "day", yesterday

    # ---------- 8. 月归档 ----------
    def t_archive():
        for day in ("2026-09-10", "2026-09-11", "2026-09-12"):
            layered.ingest(day, "用户", f"{day} 的事", ts="09:00:00")
            layered.seal(day)
        result = archive.close_month("2026-09")
        assert result["ok"] and result["days_moved"] >= 3, result
        assert (layered.MONTHS / "2026-09" / "MANIFEST.json").exists()
        # 归档后仍可定位
        assert layered.find_raw("2026-09-10") is not None
        # 重复归档同一个月：目标已存在 -> 必须停下，不覆盖
        again = archive.close_month("2026-09")
        assert again["ok"] is False, again

    # ---------- 9. 喜欢的东西 ----------
    def t_profile():
        layered.ingest("2026-10-15", "用户", "我很喜欢下雨天，安静", ts="10:00:00")
        layered.seal("2026-10-15")
        result = profile.learn("tester", "2026-10-15")
        assert result["ok"], result
        text = (profile.path_of("tester")).read_text(encoding="utf-8")
        assert "下雨天" in text, text
        assert profile.hints("tester"), "找话题应返回内容"
        profile.forget("tester", "下雨天", deny=True)
        text = (profile.path_of("tester")).read_text(encoding="utf-8")
        assert "不喜欢] 下雨天" in text, text

    # ---------- 10. HTTP + 客户端 ----------
    def t_http():
        from http.server import ThreadingHTTPServer

        server = ThreadingHTTPServer(("127.0.0.1", 5401), memory_service.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.3)
        try:
            mem = Memory(url="http://127.0.0.1:5401", timeout=3)
            assert mem.remember("wechat", "dm", "阿杰", "user", "我养了只狗叫旺财")
            memory = mem.recall("wechat", "dm", "阿杰")
            assert "旺财" in memory, memory
            assert mem.remember_batch([{"platform": "wechat", "chat": "dm", "user": "阿杰",
                                        "role": "user", "text": f"第{i}句"} for i in range(20)])
            broken = Memory(url="http://127.0.0.1:5999", timeout=0.5)
            assert broken.recall("wechat", "dm", "阿杰") == ""      # 服务不存在也不抛异常
        finally:
            server.shutdown()
            server.server_close()

    # ---------- 11. 自检 ----------
    def t_selfcheck():
        report = selfcheck.selfcheck(box)
        assert report["ok"], report

    # ---------- 12. 联想检索 ----------
    def t_assoc():
        layered.ingest("2026-08-01", "用户", "我养了只猫叫煤球，爱睡键盘", ts="09:00:00")
        layered.seal("2026-08-01")
        built = assoc.build()
        assert built["entities"] > 0, built
        result = assoc.ask("猫", depth=2)
        assert result["days"], result
        assert any(day == "2026-08-01" for day in result["days"]), result["days"]

    print("跑测试：")
    check("1 落盘 / 封存 / 定位表", t_ingest)
    check("2 同一消息去重", t_dedupe)
    check("3 批量导入 500 条", t_batch)
    check("4 超长消息截断", t_truncate)
    check("5 新旧事实作废", t_supersede)
    check("6 口语时间换算", t_when)
    check("7 按天 / 目录 / 下钻", t_ask)
    check("8 月归档 + 冲突即停", t_archive)
    check("9 喜欢的东西 + 否认", t_profile)
    check("10 HTTP 服务 + 客户端容错", t_http)
    check("11 自检", t_selfcheck)
    check("12 联想检索（旧事能翻出来）", t_assoc)

    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    for name, error in FAIL:
        print(f"  - {name}: {error}")
    shutil.rmtree(box, ignore_errors=True)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())


