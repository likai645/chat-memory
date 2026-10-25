# -*- coding: utf-8 -*-
"""测 MCP server：像真实客户端一样发 JSON-RPC，看工具能不能调通。"""
import json
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

SRC = Path(__file__).resolve().parent
box = Path(tempfile.mkdtemp(prefix="mcptest-"))
for path in SRC.glob("*.py"):
    shutil.copy2(path, box / path.name)

proc = subprocess.Popen([sys.executable, "mcp_server.py"], cwd=box,
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, encoding="utf-8")


def rpc(payload: dict) -> dict:
    proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line)


try:
    print("1) initialize:", rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                 "params": {"protocolVersion": "2024-11-05"}})["result"]["serverInfo"])
    print("2) tools/list:", len(rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]), "个工具")

    def call(name, args, rid):
        out = rpc({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                   "params": {"name": name, "arguments": args}})
        return json.loads(out["result"]["content"][0]["text"])

    print("3) remember:", call("memory_remember", {
        "platform": "qq", "chat": "dm", "user": "u1", "role": "user",
        "text": "我养了只猫叫煤球，讨厌早起", "msg_id": "m1"}, 3))
    print("4) recall  :", call("memory_recall", {"platform": "qq", "chat": "dm", "user": "u1"}, 4)["memory"][:80])
    print("5) batch   :", call("memory_batch", {"messages": [
        {"platform": "qq", "chat": "dm", "user": "u2", "role": "user", "text": f"第{i}句"} for i in range(50)]}, 5))
    print("6) facts   :", call("memory_facts", {"platform": "qq", "chat": "dm", "user": "u1"}, 6))
    print("7) hints   :", call("memory_hints", {"user": "u1"}, 7))
finally:
    proc.terminate()
    shutil.rmtree(box, ignore_errors=True)
