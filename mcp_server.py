# -*- coding: utf-8 -*-
"""MCP server：让别人在任何支持 MCP 的客户端里直接调用这套记忆。

协议：MCP（stdio，换行分隔的 JSON-RPC 2.0），不依赖任何第三方库。

配置示例（Claude Desktop / Cursor / 任何 MCP 客户端）：

    {
      "mcpServers": {
        "chat-memory": {
          "command": "python",
          "args": ["D:/chat-memory/mcp_server.py"]
        }
      }
    }

对外暴露 7 个工具：
    memory_recall     回消息前取记忆
    memory_remember   存一条消息
    memory_batch      批量导入
    memory_facts      看记住了什么
    memory_forget     删掉某个人的记忆
    memory_ask        问过去的事（支持“昨天”“上周三”）
    memory_hints      找话题用的小清单
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

import memory_service  # noqa: E402

PROTOCOL = "2024-11-05"
SERVER = {"name": "chat-memory", "version": "0.1.0"}

TOOLS = [
    {
        "name": "memory_recall",
        "description": "取回某个人该注入的记忆（人设相关的事实 + 最近几句），拼进 prompt 用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "平台标识，如 qq / wechat / douyin"},
                "chat": {"type": "string", "description": "会话 id，私聊填 dm"},
                "user": {"type": "string", "description": "用户 id"},
            },
            "required": ["platform", "chat", "user"],
        },
    },
    {
        "name": "memory_remember",
        "description": "存一条消息。同一条消息带相同 msg_id 重复调用不会重复入库。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "platform": {"type": "string"},
                "chat": {"type": "string"},
                "user": {"type": "string"},
                "role": {"type": "string", "enum": ["user", "assistant"], "description": "谁说的"},
                "text": {"type": "string"},
                "msg_id": {"type": "string", "description": "平台消息 id，用于去重"},
                "kind": {"type": "string", "description": "text / image / voice 等"},
            },
            "required": ["platform", "chat", "user", "role", "text"],
        },
    },
    {
        "name": "memory_batch",
        "description": "批量导入历史消息（每条字段同 memory_remember）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["messages"],
        },
    },
    {
        "name": "memory_facts",
        "description": "查看这个用户被记住了哪些事实、一共多少条消息。",
        "inputSchema": {
            "type": "object",
            "properties": {"platform": {"type": "string"}, "chat": {"type": "string"},
                           "user": {"type": "string"}},
            "required": ["platform", "chat", "user"],
        },
    },
    {
        "name": "memory_forget",
        "description": "删除某个人的全部记忆（隐私要求时说一句就清干净）。",
        "inputSchema": {
            "type": "object",
            "properties": {"platform": {"type": "string"}, "chat": {"type": "string"},
                           "user": {"type": "string"}},
            "required": ["platform", "chat", "user"],
        },
    },
    {
        "name": "memory_ask",
        "description": "问过去的事。支持“昨天”“三天前”“上周三”“上个月”“9月23号”这类说法。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "问题，例如“我那只猫叫什么”"},
                "now": {"type": "string", "description": "今天的日期 YYYY-MM-DD，省略则用系统日期"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_hints",
        "description": "拿几条“他喜欢的东西”，用来自然找话题。",
        "inputSchema": {
            "type": "object",
            "properties": {"user": {"type": "string"}, "n": {"type": "integer", "default": 4}},
            "required": ["user"],
        },
    },
]


def call_tool(name: str, args: dict) -> dict:
    import time

    if name == "memory_recall":
        return memory_service.recall({"platform": args["platform"], "chat": args["chat"],
                                      "user": args["user"]})
    if name == "memory_remember":
        return memory_service.remember(dict(args))
    if name == "memory_batch":
        return memory_service.remember_batch({"messages": args.get("messages") or []})
    if name == "memory_facts":
        return memory_service.facts_of({"platform": args["platform"], "chat": args["chat"],
                                        "user": args["user"]})
    if name == "memory_forget":
        return memory_service.forget({"platform": args["platform"], "chat": args["chat"],
                                      "user": args["user"]})
    if name == "memory_ask":
        import layered

        return layered.ask(args.get("now") or time.strftime("%Y-%m-%d"), args["query"])
    if name == "memory_hints":
        import profile

        return {"ok": True, "hints": profile.hints(args["user"], int(args.get("n", 4)))}
    raise ValueError(f"未知工具：{name}")


def handle(request: dict) -> dict | None:
    method = request.get("method")
    rid = request.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER,
        }}
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            result = call_tool(name, arguments)
            text = json.dumps(result, ensure_ascii=False)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": text}],
                "isError": not result.get("ok", True),
            }}
        except Exception as error:  # noqa: BLE001 - 工具出错要回给客户端，不崩
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"{type(error).__name__}: {error}"}],
                "isError": True,
            }}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": f"不支持的方法：{method}"}}
    return None


def serve() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    serve()
