#!/usr/bin/env python3
"""
初始化数据库：创建 data 目录与 data/r6ax.db（建表 + 迁移）。

用法:
    python scripts/init_db.py
"""

import asyncio
import os
import re
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WEAK_MARKERS = ("replace", "changeme", "your-secret", "example")


def ensure_jwt_secret():
    """若 .env 中 JWT_SECRET 缺失或为占位值，自动生成随机值（否则服务与 DB 初始化拒绝启动）。"""
    if not os.path.exists(".env"):
        return
    text = open(".env", encoding="utf-8").read()
    secret = next(
        (line.split("=", 1)[1] for line in text.splitlines() if line.startswith("JWT_SECRET=")),
        "",
    )
    if not secret or any(m in secret.lower() for m in WEAK_MARKERS):
        updated = re.sub(r"(?m)^JWT_SECRET=.*$", f"JWT_SECRET={secrets.token_urlsafe(48)}", text)
        open(".env", "w", encoding="utf-8").write(updated)
        print("JWT_SECRET in .env was a placeholder - generated a random one")


async def main():
    os.makedirs("data", exist_ok=True)
    ensure_jwt_secret()
    from app.core.database import init_db

    await init_db()
    print("Database initialized: data/r6ax.db")


if __name__ == "__main__":
    asyncio.run(main())
