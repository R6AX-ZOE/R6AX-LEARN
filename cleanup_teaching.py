import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'data', 'r6ax.db')
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print('All tables:', tables)
    
    # Delete teaching related data
    for table in tables:
        table_name = table[0]
        if 'teaching' in table_name or 'message' in table_name:
            cursor.execute(f"DELETE FROM {table_name}")
            print(f'Deleted from table: {table_name}')
    
    conn.commit()
    conn.close()
    print('Done')
else:
    print('DB file not found')
