"""
Migration: 为现有目录创建对应的图谱
"""
import sqlite3
import os
from uuid import uuid4

db_path = os.path.join(os.path.dirname(__file__), 'data', 'r6ax.db')

def migrate():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 获取所有没有关联图谱的目录
    cursor.execute("""
        SELECT d.id, d.project_id, d.name
        FROM directories d
        WHERE NOT EXISTS (SELECT 1 FROM graphs g WHERE g.directory_id = d.id)
    """)
    directories = cursor.fetchall()

    print(f"Found {len(directories)} directories without graphs")

    for dir_id, project_id, name in directories:
        graph_id = str(uuid4())
        cursor.execute("""
            INSERT INTO graphs (id, project_id, directory_id, name, created_at, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (graph_id, project_id, dir_id, name))
        print(f"Created graph '{name}' for directory {dir_id}")

    conn.commit()
    conn.close()
    print("Migration completed!")

if __name__ == "__main__":
    migrate()