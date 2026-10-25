# -*- coding: utf-8 -*-
"""给 bot 用的客户端：一行接入，出错绝不拖垮宿主程序。

    from client import Memory
    mem = Memory()                      # 默认 127.0.0.1:5299
    memory = mem.recall("qq", chat="g1", user="u1")     # 回消息前拿记忆
    mem.remember("qq", chat="g1", user="u1", role="user", text="我养了只猫")

原则：
  · 任何网络错误都吞掉，返回空/False —— 记忆服务挂了，聊天照样能聊
  · 超时短（默认 2 秒），别让宿主等
  · 同一条消息重复推送不会重复入库（靠 msg_id）
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class Memory:
    def __init__(self, url: str = "http://127.0.0.1:5299", token: str | None = None,
                 timeout: float = 2.0, retries: int = 1):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.retries = max(0, retries)

    # ---------- 底层 ----------
    def _post(self, path: str, payload: dict) -> dict | None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        for attempt in range(self.retries + 1):
            try:
                request = urllib.request.Request(f"{self.url}/{path}", data=body, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read())
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
                if attempt < self.retries:
                    time.sleep(0.15)
                    continue
                return None

    # ---------- 对外 ----------
    def recall(self, platform: str, chat: str, user: str, token_budget: int = 700) -> str:
        """返回一段可以直接拼进 system prompt 的记忆文本；失败返回空字符串。"""
        data = self._post("recall", {"platform": platform, "chat": chat, "user": user,
                                     "budget": token_budget})
        return (data or {}).get("memory", "") if data else ""

    def remember(self, platform: str, chat: str, user: str, role: str, text: str,
                 name: str = "", msg_id: str = "", kind: str = "text") -> bool:
        if not text:
            return False
        data = self._post("remember", {"platform": platform, "chat": chat, "user": user,
                                       "role": role, "text": text, "name": name,
                                       "msg_id": msg_id, "kind": kind})
        return bool((data or {}).get("ok"))

    def remember_batch(self, messages: list[dict]) -> bool:
        """导入历史记录：[{platform,chat,user,role,text,ts,msg_id,name,kind}, ...]"""
        if not messages:
            return False
        data = self._post("remember_batch", {"messages": messages})
        return bool((data or {}).get("ok"))

    def compact(self, platform: str, chat: str, user: str) -> dict:
        return self._post("compact", {"platform": platform, "chat": chat, "user": user}) or {}

    def forget(self, platform: str, chat: str, user: str) -> bool:
        data = self._post("forget", {"platform": platform, "chat": chat, "user": user})
        return bool((data or {}).get("ok"))


def chat_hook(mem: Memory, platform: str, chat: str, user: str, incoming: str,
              llm_call) -> str:
    """最省事的接线方式：给你自己的模型调用函数，返回回复文本。

    llm_call(system_prompt, user_text) -> reply
    """
    memory = mem.recall(platform, chat, user)
    system = "你是聊天助手。" + ("\n\n以下是相关记忆：\n" + memory if memory else "")
    reply = llm_call(system, incoming)
    mem.remember(platform, chat, user, "user", incoming)
    mem.remember(platform, chat, user, "assistant", reply)
    return reply
