# -*- coding: utf-8 -*-
"""对已经跑起来的服务做一次真实读写（用来验证 exe）。"""
import json
import sys
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5299
BASE = f"http://127.0.0.1:{PORT}"


def call(path, payload):
    request = urllib.request.Request(f"{BASE}/{path}", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


if __name__ == "__main__":
    base = {"platform": "qq", "chat": "g", "user": "u"}
    print("health :", json.loads(urllib.request.urlopen(f"{BASE}/health", timeout=5).read()))
    print("写入   :", call("remember", dict(base, role="user", text="我养了只猫叫煤球")))
    print("记忆   :", call("recall", base)["memory"])
