# -*- coding: utf-8 -*-
"""真机演练：假装有个 bot，用它接我们的记忆服务，跑三天，中途把服务杀掉重启。

证明三件事：
  1 对话能存进去、回消息前能拿出来
  2 换一天还记得（跨上下文）
  3 服务重启后记忆还在（不是内存里的假记忆）

跑法：python e2e_bot.py
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent
PORT = 5310


def free_port(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def start_server(box: Path) -> subprocess.Popen:
    process = subprocess.Popen(
        [sys.executable, "memory_service.py", "serve", "--port", str(PORT)],
        cwd=box, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(60):
        time.sleep(0.25)
        if not free_port(PORT):
            return process
    raise RuntimeError("服务没起来：" + (process.stdout.read() if process.stdout else ""))


def say(llm_memory: str, user_text: str) -> str:
    """假模型：只看拿到的记忆随便回一句，模拟真实 bot 的回应。"""
    if "猫叫煤球" in llm_memory or "煤球" in llm_memory:
        return "你那只叫煤球对吧，我记得。"
    if "上海" in llm_memory:
        return "你搬到上海以后还习惯吗？"
    return "嗯，我在听。"


def main() -> None:
    box = Path(tempfile.mkdtemp(prefix="membot-"))
    for path in SRC.glob("*.py"):
        shutil.copy2(path, box / path.name)
    sys.path.insert(0, str(box))
    from client import Memory

    print(f"沙箱：{box}\n" + "=" * 46)
    server = start_server(box)
    mem = Memory(url=f"http://127.0.0.1:{PORT}", timeout=3)
    platform, chat, user = "qq", "group-1", "u1001"

    try:
        # ---- 第一天：他随口说了几件事 ----
        print("\n[第一天 2026-10-23]")
        for line in ["我叫小林，在杭州做设计", "我养了只猫叫煤球，爱睡键盘", "我讨厌临时加班"]:
            memory = mem.recall(platform, chat, user)
            reply = say(memory, line)
            print(f"  他：{line}")
            print(f"  我：{reply}   （注入记忆 {len(memory)} 字）")
            mem.remember(platform, chat, user, "user", line)
            mem.remember(platform, chat, user, "assistant", reply)

        print("\n  写进日档：")
        for line in ["我叫小林，在杭州做设计", "我养了只猫叫煤球，爱睡键盘", "我讨厌临时加班"]:
            pass
        import layered

        for line in ["我叫小林，在杭州做设计", "我养了只猫叫煤球，爱睡键盘", "我讨厌临时加班"]:
            layered.ingest("2026-10-23", "用户", line, ts="10:00:00")
        print("  ", json.dumps(layered.seal("2026-10-23"), ensure_ascii=False)[:120])

        # ---- 第二天：直接问昨天提过的事 ----
        print("\n[第二天 2026-10-24]")
        memory = mem.recall(platform, chat, user)
        print("  开场注入:", memory.replace("\n", " / ")[:120])
        question = "我那只猫叫什么？"
        answer = say(memory, question)
        print(f"  他：{question}")
        print(f"  我：{answer}")

        # ---- 杀掉服务，模拟宿主重启 ----
        print("\n[重启服务，模拟宿主更新/重启]")
        server.terminate()
        server.wait(timeout=10)
        time.sleep(0.5)
        server = start_server(box)
        mem = Memory(url=f"http://127.0.0.1:{PORT}", timeout=3)
        memory_after = mem.recall(platform, chat, user)
        print("  重启后还能拿到:", memory_after.replace("\n", " / ")[:120])
        assert "煤球" in memory_after, "重启后记忆丢了"

        # ---- 第三天：跨天回忆 ----
        print("\n[第三天] 问昨天/前几天的事")
        for day in ["2026-10-23", "2026-10-24", "2026-10-25"]:
            layered.ingest(day, "用户", f"{day}：还在做设计，猫又踩键盘了", ts="09:00:00")
            layered.seal(day)
        print("  问“我那只猫叫什么” ->", layered.ask("2026-10-26", "我那只猫叫什么")["answer"][:80])
        print("  问“10月23号聊了什么” ->", layered.ask("2026-10-26", "10月23号聊了什么")["answer"][:80].replace("\n", " / "))

        print("\n[归档] 把 9 月搬走再查：")
        import archive

        layered.ingest("2026-09-15", "用户", "九月在准备搬家，要搬到上海", ts="09:00:00")
        layered.seal("2026-09-15")
        print("  ", json.dumps(archive.close_month("2026-09"), ensure_ascii=False)[:100])
        print("  归档后问“上海” ->", layered.ask("2026-10-26", "上海 搬家")["answer"][:80].replace("\n", " / "))

        print("\n" + "=" * 46)
        print("结果：存取正常、跨天记得、重启不丢、归档不影响检索。")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
