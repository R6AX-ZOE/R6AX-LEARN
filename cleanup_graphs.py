"""
Delete all graph-related data (graphs / nodes / edges / node_embeddings)
Keep this script for future reuse.
"""

import asyncio
from sqlalchemy import text
from app.core.database import async_engine


async def cleanup_graphs():
    tables = ["node_embeddings", "edges", "nodes", "graphs"]
    async with async_engine.begin() as conn:
        for table in tables:
            result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
            await conn.execute(text(f"DELETE FROM {table}"))
            print(f"  {table}: deleted {count} rows")
    print("Graph data cleanup done.")


if __name__ == "__main__":
    asyncio.run(cleanup_graphs())
