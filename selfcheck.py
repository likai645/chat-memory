# -*- coding: utf-8 -*-
"""版本与自检：升级前后都能确认“没坏”。

三个概念分开：
  VERSION         插件版本（人看的）
  SCHEMA_VERSION  数据结构版本（决定了能不能读旧数据）
  数据目录        和程序完全分开，程序删了数据还在

升级时的规矩：
  · 新版本只能“加列/加表”，绝不删列、不重命名 —— 老数据永远可读
  · connect() 每次都会自动补齐缺的列（幂等），所以升级不用手动迁移
  · 启动时跑 selfcheck，任何一项失败就明确报出来，不装死
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

VERSION = "0.1.0"
SCHEMA_VERSION = 2

REQUIRED_TABLES = {
    "messages": {"id", "platform", "chat_id", "user_id", "role", "text", "ts", "msg_id", "name", "kind"},
    "facts": {"id", "platform", "chat_id", "user_id", "fact", "ts", "topic", "status", "superseded_at"},
    "summaries": {"id", "platform", "chat_id", "user_id", "level", "period", "text", "ts"},
}


def check_db(db_path: Path) -> dict:
    problems = []
    if not db_path.exists():
        return {"ok": True, "note": "数据库还没建（首次运行会自己建）"}
    conn = sqlite3.connect(db_path)
    try:
        for table, required in REQUIRED_TABLES.items():
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            existing = {row[1] for row in rows}
            if not existing:
                problems.append(f"缺表 {table}")
                continue
            missing = required - existing
            if missing:
                problems.append(f"{table} 缺列 {sorted(missing)}")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version and version > SCHEMA_VERSION:
            problems.append(f"数据版本 {version} 比程序支持的新（{SCHEMA_VERSION}），请升级插件")
    finally:
        conn.close()
    return {"ok": not problems, "problems": problems}


def selfcheck(root: Path | None = None) -> dict:
    root = root or Path(__file__).resolve().parent
    result = {"version": VERSION, "schema": SCHEMA_VERSION,
              "python": sys.version.split()[0], "checks": {}}

    frozen = getattr(sys, "frozen", False)
    # 1) 用到的模块都在（打包成 exe 时文件在包里，跳过这项）
    missing = [] if frozen else [name for name in
                                 ("layered", "archive", "catalog", "profile", "when", "client")
                                 if not (root / f"{name}.py").exists()]
    result["checks"]["files"] = {"ok": not missing, "missing": missing,
                                 **({"note": "打包运行，代码在 exe 内"} if frozen else {})}

    # 2) 数据目录可写
    data = root / "data"
    try:
        data.mkdir(parents=True, exist_ok=True)
        probe = data / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        result["checks"]["writable"] = {"ok": True}
    except Exception as error:  # noqa: BLE001
        result["checks"]["writable"] = {"ok": False, "error": str(error)}

    # 3) 数据库结构对得上
    result["checks"]["schema"] = check_db(root / "memory.db")

    # 4) 核心模块能导入
    try:
        sys.path.insert(0, str(root))
        import layered  # noqa: F401
        import profile  # noqa: F401
        result["checks"]["imports"] = {"ok": True}
    except Exception as error:  # noqa: BLE001
        result["checks"]["imports"] = {"ok": False, "error": str(error)}

    result["ok"] = all(check.get("ok") for check in result["checks"].values())
    return result


def stamp(root: Path | None = None) -> None:
    """启动时把版本写进数据目录，方便以后排查“这台机器跑的是哪版”。"""
    root = root or Path(__file__).resolve().parent
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "version.json").write_text(json.dumps({
        "plugin": VERSION, "schema": SCHEMA_VERSION,
        "written": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    report = selfcheck()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    sys.exit(0 if report["ok"] else 1)

