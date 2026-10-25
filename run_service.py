# -*- coding: utf-8 -*-
"""打包成 exe 的入口：双击就起服务。

顺序：
  1 自检（缺文件/数据目录不可写/库结构不对，直接报出来）
  2 起 HTTP 服务（默认 5299，可用 PORT 环境变量改）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def app_dir() -> Path:
    """exe 所在目录（打包后 sys.executable 指向 exe 本身）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main() -> int:
    # Windows 控制台默认 GBK，中文会变乱码；统一改成 UTF-8
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if sys.platform == "win32":
        os.system("chcp 65001 >nul")
    base = app_dir()
    os.chdir(base)
    sys.path.insert(0, str(base))

    try:
        import selfcheck

        report = selfcheck.selfcheck(base)
        print(f"self-check: {'OK' if report['ok'] else 'FAILED'}  v{report['version']} schema{report['schema']}")
        if not report["ok"]:
            print(json.dumps(report["checks"], ensure_ascii=False, indent=1))
            input("按回车退出…")
            return 1
        selfcheck.stamp(base)
    except Exception as error:  # noqa: BLE001
        print(f"self-check skipped: {error}")

    import memory_service

    port = int(os.environ.get("PORT", "5299"))
    print(f"\n记忆服务已启动：http://127.0.0.1:{port}")
    print("数据目录：", base / "data")
    print("关掉这个窗口就停止。\n")
    memory_service.serve(port)
    return 0


def cli() -> int:
    """pip 安装后的命令入口：chat-memory"""
    return main()


if __name__ == "__main__":
    sys.exit(main())


