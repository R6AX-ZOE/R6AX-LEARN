"""
Migration: Multi-Graph Support
- Remove unique constraint from graphs.project_id
- Add directory_id column to graphs
- Add name column to graphs (if not exists)
"""
import sqlite3
import os

db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'r6ax.db')

def migrate():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check current graphs table structure
    cursor.execute("PRAGMA table_info(graphs)")
    columns = cursor.fetchall()
    column_names = [col[1] for col in columns]

    print(f"Current graphs columns: {column_names}")

    # Check if directory_id column exists
    if 'directory_id' not in column_names:
        print("Adding directory_id column...")
        cursor.execute("ALTER TABLE graphs ADD COLUMN directory_id VARCHAR")
    else:
        print("directory_id column already exists")

    # Check if name column exists
    if 'name' not in column_names:
        print("Adding name column...")
        cursor.execute("ALTER TABLE graphs ADD COLUMN name VARCHAR DEFAULT '知识图谱'")
    else:
        print("name column already exists")

    # SQLite doesn't support DROP CONSTRAINT, need to recreate table
    # Check if unique constraint exists on project_id
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='graphs'")
    create_sql = cursor.fetchone()
    if create_sql and 'UNIQUE' in create_sql[0]:
        print("Recreating graphs table to remove unique constraint...")

        # Create new table without unique constraint
        cursor.execute("""
            CREATE TABLE graphs_new (
                id VARCHAR PRIMARY KEY,
                project_id VARCHAR NOT NULL,
                directory_id VARCHAR,
                name VARCHAR DEFAULT '知识图谱',
                created_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY (project_id) REFERENCES projects(id),
                FOREIGN KEY (directory_id) REFERENCES directories(id)
            )
        """)

        # Copy data
        cursor.execute("""
            INSERT INTO graphs_new (id, project_id, directory_id, name, created_at, updated_at)
            SELECT id, project_id, NULL, '知识图谱', created_at, updated_at FROM graphs
        """)

        # Drop old table and rename
        cursor.execute("DROP TABLE graphs")
        cursor.execute("ALTER TABLE graphs_new RENAME TO graphs")

        print("graphs table recreated successfully")

    conn.commit()
    conn.close()
    print("Migration completed!")

if __name__ == "__main__":
    migrate()