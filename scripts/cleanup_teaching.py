import sqlite3
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(ROOT_DIR, 'data', 'r6ax.db')
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    # 断开 nodes -> concepts 的引用（保留图谱节点，避免孤儿外键）
    cursor.execute("UPDATE nodes SET concept_id = NULL WHERE concept_id IS NOT NULL")
    print('Cleared concept_id references in nodes')

    # 按外键依赖逆序删除 teaching 相关数据（子表在前，父表在后）
    delete_order = [
        'review_records',                # -> review_schedules
        'review_schedules',              # -> questions
        'questions',                     # -> concepts
        'messages',                      # -> teaching_sessions
        'concepts',                      # -> teaching_sessions
        'misconceptions',                # -> teaching_sessions
        'virtual_graph_edges',           # -> virtual_graph_nodes
        'virtual_graph_nodes',           # -> virtual_graphs
        'virtual_graph_to_node_edges',   # -> virtual_graphs
        'virtual_graph_embeddings',      # -> virtual_graphs
        'virtual_graphs',                # -> teaching_sessions
        'teaching_sessions',
    ]
    for table in delete_order:
        cursor.execute(f"DELETE FROM {table}")
        print(f'Deleted from table: {table}')

    conn.commit()
    conn.close()
    print('Done')
else:
    print('DB file not found')
