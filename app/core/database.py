from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.base import Base

from app.models import user, input, teaching, practice, integration

async_engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 添加缺失的字段（迁移）
    async with AsyncSessionLocal() as session:
        # 检查 teaching_sessions 表是否有 source_note_id 字段
        try:
            await session.execute(text("SELECT source_note_id FROM teaching_sessions LIMIT 1"))
        except Exception:
            # 字段不存在，添加它
            await session.execute(text("ALTER TABLE teaching_sessions ADD COLUMN source_note_id VARCHAR"))
            await session.commit()
            print("Added source_note_id column to teaching_sessions table")

        # 检查 notes 表的 directory_id 是否有 NOT NULL 约束
        try:
            # SQLite 不支持直接修改约束，需要重建表
            result = await session.execute(text("PRAGMA table_info(notes)"))
            columns = result.fetchall()
            for col in columns:
                if col[1] == 'directory_id' and col[3] == 1:  # notnull = 1
                    # 需要重建表来移除 NOT NULL 约束
                    await session.execute(text("""
                        CREATE TABLE notes_new (
                            id VARCHAR PRIMARY KEY,
                            directory_id VARCHAR,
                            title VARCHAR NOT NULL,
                            content TEXT,
                            created_at DATETIME,
                            updated_at DATETIME
                        )
                    """))
                    await session.execute(text("""
                        INSERT INTO notes_new SELECT id, directory_id, title, content, created_at, updated_at FROM notes
                    """))
                    await session.execute(text("DROP TABLE notes"))
                    await session.execute(text("ALTER TABLE notes_new RENAME TO notes"))
                    await session.commit()
                    print("Modified notes table: directory_id now nullable")
                    break
        except Exception as e:
            print(f"Migration check for notes table: {e}")

        # 检查 teaching_sessions 表是否有 trigger_concept_id 字段（F-16：错题触发 Teaching 的标记）
        try:
            await session.execute(text("SELECT trigger_concept_id FROM teaching_sessions LIMIT 1"))
        except Exception:
            await session.execute(text("ALTER TABLE teaching_sessions ADD COLUMN trigger_concept_id VARCHAR"))
            await session.commit()
            print("Added trigger_concept_id column to teaching_sessions table")

        # 检查 messages 表是否有 parent_id, branch_id, is_active, extra_data 字段
        try:
            await session.execute(text("SELECT parent_id FROM messages LIMIT 1"))
        except Exception:
            # 字段不存在，添加它们
            await session.execute(text("ALTER TABLE messages ADD COLUMN parent_id VARCHAR"))
            await session.execute(text("ALTER TABLE messages ADD COLUMN branch_id VARCHAR"))
            await session.execute(text("ALTER TABLE messages ADD COLUMN is_active BOOLEAN DEFAULT 1"))
            await session.execute(text("ALTER TABLE messages ADD COLUMN extra_data TEXT DEFAULT '{}'"))
            await session.commit()
            print("Added parent_id, branch_id, is_active, extra_data columns to messages table")
        
        # 检查 messages 表是否有 extra_data 字段（单独检查，避免已添加其他字段但缺少这个）
        try:
            await session.execute(text("SELECT extra_data FROM messages LIMIT 1"))
        except Exception:
            await session.execute(text("ALTER TABLE messages ADD COLUMN extra_data TEXT DEFAULT '{}'"))
            await session.commit()
            print("Added extra_data column to messages table")

        # ===== Practice Level 迁移（F-12~F-15）=====
        # questions 表：新增 is_extension / knowledge_points / rationale
        try:
            await session.execute(text("SELECT is_extension FROM questions LIMIT 1"))
        except Exception:
            await session.execute(text("ALTER TABLE questions ADD COLUMN is_extension BOOLEAN DEFAULT 0"))
            await session.execute(text("ALTER TABLE questions ADD COLUMN knowledge_points TEXT"))
            await session.execute(text("ALTER TABLE questions ADD COLUMN rationale TEXT"))
            await session.commit()
            print("Added is_extension, knowledge_points, rationale columns to questions table")

        # review_records 表：新增 score
        try:
            await session.execute(text("SELECT score FROM review_records LIMIT 1"))
        except Exception:
            await session.execute(text("ALTER TABLE review_records ADD COLUMN score FLOAT DEFAULT 0.0"))
            await session.commit()
            print("Added score column to review_records table")

        # ===== 虚拟图相关表迁移 =====
        # 检查 virtual_graphs 表是否存在
        try:
            await session.execute(text("SELECT id FROM virtual_graphs LIMIT 1"))
        except Exception:
            # 创建 virtual_graphs 表
            await session.execute(text("""
                CREATE TABLE virtual_graphs (
                    id VARCHAR PRIMARY KEY,
                    session_id VARCHAR,
                    graph_id VARCHAR,
                    name VARCHAR NOT NULL,
                    description TEXT,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY (session_id) REFERENCES teaching_sessions(id),
                    FOREIGN KEY (graph_id) REFERENCES graphs(id)
                )
            """))
            await session.commit()
            print("Created virtual_graphs table")

        # 检查 virtual_graph_nodes 表是否存在
        try:
            await session.execute(text("SELECT id FROM virtual_graph_nodes LIMIT 1"))
        except Exception:
            await session.execute(text("""
                CREATE TABLE virtual_graph_nodes (
                    id VARCHAR PRIMARY KEY,
                    virtual_graph_id VARCHAR,
                    node_id VARCHAR,
                    label VARCHAR NOT NULL,
                    description TEXT,
                    content TEXT,
                    order_index INTEGER DEFAULT 0,
                    mastery_score FLOAT DEFAULT 0.0,
                    FOREIGN KEY (virtual_graph_id) REFERENCES virtual_graphs(id),
                    FOREIGN KEY (node_id) REFERENCES nodes(id)
                )
            """))
            await session.commit()
            print("Created virtual_graph_nodes table")

        # 检查 virtual_graph_edges 表是否存在
        try:
            await session.execute(text("SELECT id FROM virtual_graph_edges LIMIT 1"))
        except Exception:
            await session.execute(text("""
                CREATE TABLE virtual_graph_edges (
                    id VARCHAR PRIMARY KEY,
                    virtual_graph_id VARCHAR,
                    source_vnode_id VARCHAR,
                    target_vnode_id VARCHAR,
                    relation VARCHAR NOT NULL,
                    label VARCHAR,
                    FOREIGN KEY (virtual_graph_id) REFERENCES virtual_graphs(id),
                    FOREIGN KEY (source_vnode_id) REFERENCES virtual_graph_nodes(id),
                    FOREIGN KEY (target_vnode_id) REFERENCES virtual_graph_nodes(id)
                )
            """))
            await session.commit()
            print("Created virtual_graph_edges table")

        # 检查 virtual_graph_to_node_edges 表是否存在
        try:
            await session.execute(text("SELECT id FROM virtual_graph_to_node_edges LIMIT 1"))
        except Exception:
            await session.execute(text("""
                CREATE TABLE virtual_graph_to_node_edges (
                    id VARCHAR PRIMARY KEY,
                    virtual_graph_id VARCHAR,
                    node_id VARCHAR,
                    relation_type VARCHAR NOT NULL,
                    FOREIGN KEY (virtual_graph_id) REFERENCES virtual_graphs(id),
                    FOREIGN KEY (node_id) REFERENCES nodes(id)
                )
            """))
            await session.commit()
            print("Created virtual_graph_to_node_edges table")

        # 检查 virtual_graph_embeddings 表是否存在
        try:
            await session.execute(text("SELECT id FROM virtual_graph_embeddings LIMIT 1"))
        except Exception:
            await session.execute(text("""
                CREATE TABLE virtual_graph_embeddings (
                    id VARCHAR PRIMARY KEY,
                    virtual_graph_id VARCHAR,
                    embedding TEXT,
                    FOREIGN KEY (virtual_graph_id) REFERENCES virtual_graphs(id)
                )
            """))
            await session.commit()
            print("Created virtual_graph_embeddings table")

    from sqlalchemy import select
    from app.models.user import User
    from app.core.security import get_password_hash

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        admin = result.first()

        if not admin:
            hashed_password = get_password_hash("admin")
            admin_user = User(
                id="admin",
                username="admin",
                password_hash=hashed_password
            )
            session.add(admin_user)
            await session.commit()
            print("Default admin user created: username=admin, password=admin")

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
