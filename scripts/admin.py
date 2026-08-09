#!/usr/bin/env python3
"""
管理员用户管理工具

使用方法:
    python scripts/admin.py create_user <username> <password>
    python scripts/admin.py list_users
    python scripts/admin.py delete_user <username>
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.core.database import get_db, init_db
from app.core.security import get_password_hash
from app.models.user import User


async def create_user(username: str, password: str):
    """创建新用户"""
    await init_db()
    async for db in get_db():
        existing = await db.execute(select(User).where(User.username == username))
        if existing.first():
            print(f"错误：用户 '{username}' 已存在")
            return
        
        hashed_password = get_password_hash(password)
        new_user = User(
            id=username,
            username=username,
            password_hash=hashed_password
        )
        db.add(new_user)
        await db.commit()
        print(f"用户 '{username}' 创建成功")


async def list_users():
    """列出所有用户"""
    await init_db()
    async for db in get_db():
        users = await db.execute(select(User))
        users = users.fetchall()
        
        print("用户列表:")
        print("-" * 40)
        for user in users:
            print(f"用户名: {user.username}")
        print("-" * 40)
        print(f"共 {len(users)} 个用户")


async def delete_user(username: str):
    """删除用户"""
    await init_db()
    async for db in get_db():
        user = await db.execute(select(User).where(User.username == username))
        user = user.first()
        
        if not user:
            print(f"错误：用户 '{username}' 不存在")
            return
        
        await db.delete(user)
        await db.commit()
        print(f"用户 '{username}' 删除成功")


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    command = sys.argv[1]
    
    if command == "create_user":
        if len(sys.argv) != 4:
            print("用法: python admin.py create_user <username> <password>")
            return
        await create_user(sys.argv[2], sys.argv[3])
    
    elif command == "list_users":
        await list_users()
    
    elif command == "delete_user":
        if len(sys.argv) != 3:
            print("用法: python admin.py delete_user <username>")
            return
        await delete_user(sys.argv[2])
    
    else:
        print(f"未知命令: {command}")
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())
