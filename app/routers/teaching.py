from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, HTMLResponse
from starlette.requests import Request
from jinja2 import Environment, FileSystemLoader
from uuid import uuid4
from datetime import datetime
import asyncio
import json

from sqlalchemy import text
from app.core.deps import get_current_user, get_db
from app.models.user import User
from app.models.teaching import TeachingSession, Message, Concept, Misconception
from app.schemas.teaching import TeachingSessionCreate, TeachingSessionResponse, MessageCreate, MessageResponse, ConceptResponse
from app.services.ai_service import chat_completion, stream_chat_completion
from app.services.teaching_agent import TeachingAgent
from app.services.graph_mount import merge_or_create_node, mount_node, sync_virtual_graph_to_real
from app.i18n.i18n import t

router = APIRouter()

jinja_env = Environment(
    loader=FileSystemLoader("app/templates"),
    autoescape=True,
    cache_size=0
)
jinja_env.globals['t'] = t

VIRTUAL_GRAPH_TOOLS = {
    'create_virtual_graph', 'get_virtual_graphs', 'get_virtual_graph',
    'update_virtual_graph', 'delete_virtual_graph',
    'search_virtual_graphs_rag', 'search_virtual_graph_nodes',
}

async def _get_project_graph_id(db, session_id: str):
    """获取session所属项目合适的图谱ID（优先 source_note -> directory -> graph 路径；
    fallback 时创建与目录同名的图谱）"""
    session_result = await db.execute(
        text("SELECT project_id, source_note_id FROM teaching_sessions WHERE id = :sid"),
        {"sid": session_id}
    )
    session_row = session_result.first()
    if not session_row:
        return None
    project_id = session_row[0]
    source_note_id = session_row[1]

    directory_id = None
    directory_name = None
    if source_note_id:
        note_result = await db.execute(
            text("SELECT directory_id FROM notes WHERE id = :note_id"),
            {"note_id": source_note_id}
        )
        note_row = note_result.first()
        if note_row and note_row[0]:
            directory_id = note_row[0]
            dir_result = await db.execute(
                text("SELECT name FROM directories WHERE id = :directory_id"),
                {"directory_id": directory_id}
            )
            dir_row = dir_result.first()
            directory_name = dir_row[0] if dir_row else None
            graph_result = await db.execute(
                text("SELECT id FROM graphs WHERE directory_id = :directory_id"),
                {"directory_id": directory_id}
            )
            graph_row = graph_result.first()
            if graph_row:
                return graph_row[0]

    # fallback：笔记有目录但目录还没有图谱 → 创建与目录同名的图谱
    if directory_id:
        new_graph_id = str(uuid4())
        await db.execute(
            text("""INSERT INTO graphs (id, project_id, directory_id, name, created_at, updated_at)
                   VALUES (:id, :pid, :did, :name, datetime('now'), datetime('now'))"""),
            {"id": new_graph_id, "pid": project_id, "did": directory_id,
             "name": directory_name or "知识图谱"}
        )
        await db.commit()
        return new_graph_id

    # 无目录上下文：fallback 到项目第一个图谱
    graph_result = await db.execute(
        text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
        {"pid": project_id}
    )
    graph_row = graph_result.first()
    if graph_row:
        return graph_row[0]

    return None

async def _insert_virtual_graph_nodes_and_edges(db, vg_id: str, nodes: list, edges: list):
    """插入虚拟图节点和内部边，返回 {label: vnode_id} 映射"""
    vnode_ids = {}
    for idx, node_data in enumerate(nodes):
        vnode_id = str(uuid4())
        label = node_data.get('label')
        properties_json = json.dumps(node_data.get('properties', []), ensure_ascii=False)
        content = node_data.get('content') or node_data.get('description') or ''
        mastery = node_data.get('mastery_score', 0)
        await db.execute(
            text("""INSERT INTO virtual_graph_nodes (id, virtual_graph_id, label, properties, content, order_index, mastery_score)
                   VALUES (:id, :vgid, :label, :props, :content, :idx, :ms)"""),
            {"id": vnode_id, "vgid": vg_id, "label": label, "props": properties_json,
             "content": content, "idx": idx, "ms": mastery}
        )
        vnode_ids[label] = vnode_id

    for edge_data in (edges or []):
        source_label = edge_data.get('source_label') or edge_data.get('source')
        target_label = edge_data.get('target_label') or edge_data.get('target')
        relation = edge_data.get('relation', 'related')
        label = edge_data.get('label', '')
        if source_label in vnode_ids and target_label in vnode_ids:
            edge_id = str(uuid4())
            await db.execute(
                text("""INSERT INTO virtual_graph_edges (id, virtual_graph_id, source_vnode_id, target_vnode_id, relation, label)
                       VALUES (:id, :vgid, :src, :tgt, :rel, :lbl)"""),
                {"id": edge_id, "vgid": vg_id, "src": vnode_ids[source_label],
                 "tgt": vnode_ids[target_label], "rel": relation, "lbl": label}
            )

    return vnode_ids

async def _execute_virtual_graph_tool(db, session_id: str, tool_name: str, arguments: dict) -> str:
    """执行虚拟图相关工具，返回JSON结果字符串。所有路由（流式/PUT）共用，避免结果被吞掉。"""
    if tool_name == 'create_virtual_graph':
        vg_name = arguments.get('name')
        vg_description = arguments.get('description', '')
        nodes = arguments.get('nodes', [])
        edges = arguments.get('edges', [])
        node_connections = arguments.get('node_connections') or arguments.get('connected_nodes', [])

        session_info = await db.execute(
            text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
            {"sid": session_id}
        )
        session_row = session_info.first()
        if not session_row:
            return json.dumps({"status": "error", "message": "Session not found"}, ensure_ascii=False)
        project_id = session_row[0]

        graph_id = await _get_project_graph_id(db, session_id)

        vg_result = await db.execute(
            text("SELECT id FROM virtual_graphs WHERE session_id = :sid AND name = :name"),
            {"sid": session_id, "name": vg_name}
        )
        existing_vg = vg_result.first()
        if existing_vg:
            return json.dumps({"status": "exists", "name": vg_name}, ensure_ascii=False)

        vg_id = str(uuid4())
        await db.execute(
            text("""INSERT INTO virtual_graphs (id, session_id, graph_id, name, description, created_at, updated_at)
                   VALUES (:id, :sid, :gid, :name, :desc, datetime('now'), datetime('now'))"""),
            {"id": vg_id, "sid": session_id, "gid": graph_id, "name": vg_name, "desc": vg_description}
        )

        vnode_ids = await _insert_virtual_graph_nodes_and_edges(db, vg_id, nodes, edges)

        if graph_id:
            for conn_data in node_connections:
                real_label = conn_data.get('real_node_label') or conn_data.get('node_label')
                connection_type = conn_data.get('connection_type') or conn_data.get('relation_type', 'contains')
                if not real_label:
                    continue
                node_result = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": real_label}
                )
                node_row = node_result.first()
                if node_row:
                    conn_id = str(uuid4())
                    await db.execute(
                        text("""INSERT INTO virtual_graph_to_node_edges (id, virtual_graph_id, node_id, relation_type)
                               VALUES (:id, :vgid, :nid, :rtype)"""),
                        {"id": conn_id, "vgid": vg_id, "nid": node_row[0], "rtype": connection_type}
                    )

        try:
            from app.services.embedding_service import get_embedding_service
            embedding_service = get_embedding_service()
            content_text = f"{vg_name}\n{vg_description}\n"
            for node_data in nodes:
                label = node_data.get('label')
                desc = node_data.get('description', '')
                content = node_data.get('content', '')
                content_text += f"{label}: {desc} {content}\n"
            embedding_vector = embedding_service.generate_embedding(content_text)
            embedding_json = json.dumps(embedding_vector)
            embedding_id = str(uuid4())
            await db.execute(
                text("INSERT INTO virtual_graph_embeddings (id, virtual_graph_id, embedding) VALUES (:id, :vgid, :emb)"),
                {"id": embedding_id, "vgid": vg_id, "emb": embedding_json}
            )
        except Exception as e:
            print(f"Error generating embedding for virtual graph: {e}")

        await db.commit()
        return json.dumps({"status": "success", "name": vg_name, "node_count": len(nodes)}, ensure_ascii=False)

    if tool_name == 'get_virtual_graphs':
        session_info = await db.execute(
            text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
            {"sid": session_id}
        )
        session_row = session_info.first()
        if not session_row:
            return json.dumps({"status": "error", "message": "Session not found"}, ensure_ascii=False)
        project_id = session_row[0]
        vg_result = await db.execute(
            text("""SELECT vg.*, ts.title as session_title
                   FROM virtual_graphs vg
                   LEFT JOIN teaching_sessions ts ON vg.session_id = ts.id
                   WHERE ts.project_id = :pid
                   ORDER BY vg.created_at DESC"""),
            {"pid": project_id}
        )
        vg_list = vg_result.fetchall()
        vg_data = [{"name": vg[3], "description": vg[4] or "", "session_title": vg[7] or ""} for vg in vg_list]
        return json.dumps({"status": "success", "virtual_graphs": vg_data}, ensure_ascii=False)

    if tool_name == 'get_virtual_graph':
        vg_name = arguments.get('name')
        vg_result = await db.execute(
            text("SELECT * FROM virtual_graphs WHERE session_id = :sid AND name = :name"),
            {"sid": session_id, "name": vg_name}
        )
        vg_row = vg_result.first()
        if not vg_row:
            return json.dumps({"status": "error", "message": "Not found"}, ensure_ascii=False)
        vg_id = vg_row[0]

        nodes_result = await db.execute(
            text("SELECT label, properties, content, mastery_score, order_index FROM virtual_graph_nodes WHERE virtual_graph_id = :vgid ORDER BY order_index"),
            {"vgid": vg_id}
        )
        node_list = []
        for n in nodes_result.fetchall():
            props = []
            try:
                props = json.loads(n[1]) if n[1] else []
            except Exception:
                props = []
            node_list.append({
                "label": n[0], "properties": props, "content": n[2] or "",
                "mastery_score": n[3], "order_index": n[4]
            })

        edges_result = await db.execute(
            text("""SELECT svn.label as source, tvn.label as target, vge.relation, vge.label
                   FROM virtual_graph_edges vge
                   JOIN virtual_graph_nodes svn ON vge.source_vnode_id = svn.id
                   JOIN virtual_graph_nodes tvn ON vge.target_vnode_id = tvn.id
                   WHERE vge.virtual_graph_id = :vgid"""),
            {"vgid": vg_id}
        )
        edge_list = [{"source": e[0], "target": e[1], "relation": e[2], "label": e[3] or ""} for e in edges_result.fetchall()]

        vg_data = {"name": vg_row[3], "description": vg_row[4] or "", "nodes": node_list, "edges": edge_list}
        return json.dumps({"status": "success", "virtual_graph": vg_data}, ensure_ascii=False)

    if tool_name == 'update_virtual_graph':
        vg_name = arguments.get('name')
        new_name = arguments.get('new_name')
        new_description = arguments.get('new_description') or arguments.get('description')
        nodes = arguments.get('nodes')
        edges = arguments.get('edges')

        vg_result = await db.execute(
            text("SELECT id FROM virtual_graphs WHERE session_id = :sid AND name = :name"),
            {"sid": session_id, "name": vg_name}
        )
        vg_row = vg_result.first()
        if not vg_row:
            return json.dumps({"status": "error", "message": "Virtual graph not found"}, ensure_ascii=False)
        vg_id = vg_row[0]

        updates = []
        params = {"vgid": vg_id}
        if new_name:
            updates.append("name = :new_name")
            params["new_name"] = new_name
        if new_description:
            updates.append("description = :new_desc")
            params["new_desc"] = new_description
        if updates:
            sql = f"UPDATE virtual_graphs SET {', '.join(updates)}, updated_at = datetime('now') WHERE id = :vgid"
            await db.execute(text(sql), params)

        if nodes is not None:
            await db.execute(text("DELETE FROM virtual_graph_edges WHERE virtual_graph_id = :vgid"), {"vgid": vg_id})
            await db.execute(text("DELETE FROM virtual_graph_nodes WHERE virtual_graph_id = :vgid"), {"vgid": vg_id})
            await _insert_virtual_graph_nodes_and_edges(db, vg_id, nodes, edges)

        await db.commit()
        return json.dumps({"status": "success", "name": new_name or vg_name}, ensure_ascii=False)

    if tool_name == 'delete_virtual_graph':
        vg_name = arguments.get('name')
        vg_result = await db.execute(
            text("SELECT id FROM virtual_graphs WHERE session_id = :sid AND name = :name"),
            {"sid": session_id, "name": vg_name}
        )
        vg_row = vg_result.first()
        if not vg_row:
            return json.dumps({"status": "error", "message": "Virtual graph not found"}, ensure_ascii=False)
        vg_id = vg_row[0]
        await db.execute(text("DELETE FROM virtual_graph_to_node_edges WHERE virtual_graph_id = :vgid"), {"vgid": vg_id})
        await db.execute(text("DELETE FROM virtual_graph_edges WHERE virtual_graph_id = :vgid"), {"vgid": vg_id})
        await db.execute(text("DELETE FROM virtual_graph_nodes WHERE virtual_graph_id = :vgid"), {"vgid": vg_id})
        await db.execute(text("DELETE FROM virtual_graph_embeddings WHERE virtual_graph_id = :vgid"), {"vgid": vg_id})
        await db.execute(text("DELETE FROM virtual_graphs WHERE id = :vgid"), {"vgid": vg_id})
        await db.commit()
        return json.dumps({"status": "success", "name": vg_name}, ensure_ascii=False)

    if tool_name == 'search_virtual_graphs_rag':
        query = arguments.get('query', '')
        top_k = arguments.get('top_k', 5)
        session_result = await db.execute(
            text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
            {"sid": session_id}
        )
        session_row = session_result.first()
        if not session_row:
            return json.dumps({"status": "error", "message": "Session not found"}, ensure_ascii=False)
        project_id = session_row[0]
        try:
            from app.services.embedding_service import get_embedding_service
            embedding_service = get_embedding_service()
            search_results = embedding_service.search_virtual_graphs(
                db_path="data/r6ax.db",
                query=query,
                project_id=project_id,
                top_k=top_k
            )
            return json.dumps({"status": "success", "results": search_results, "query": query}, ensure_ascii=False)
        except Exception as e:
            print(f"Error in RAG search: {e}")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

    if tool_name == 'search_virtual_graph_nodes':
        virtual_graph_name = arguments.get('virtual_graph_name')
        keyword = arguments.get('keyword')
        top_k = arguments.get('top_k', 5)

        session_result = await db.execute(
            text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
            {"sid": session_id}
        )
        session_row = session_result.first()
        if not session_row:
            return json.dumps({"status": "error", "message": "Session not found"}, ensure_ascii=False)
        project_id = session_row[0]

        vg_result = await db.execute(
            text("""SELECT vg.id FROM virtual_graphs vg
                   JOIN teaching_sessions ts ON vg.session_id = ts.id
                   WHERE ts.project_id = :pid AND vg.name = :name"""),
            {"pid": project_id, "name": virtual_graph_name}
        )
        vg_row = vg_result.first()
        if not vg_row:
            return json.dumps({"status": "error", "message": f"Virtual graph '{virtual_graph_name}' not found"}, ensure_ascii=False)
        vg_id = vg_row[0]

        nodes_result = await db.execute(
            text("""SELECT id, label, content, order_index
                   FROM virtual_graph_nodes
                   WHERE virtual_graph_id = :vg_id
                   AND (label LIKE :keyword OR content LIKE :keyword)
                   ORDER BY order_index
                   LIMIT :top_k"""),
            {"vg_id": vg_id, "keyword": f"%{keyword}%", "top_k": top_k}
        )
        results = [
            {"node_id": n[0], "label": n[1], "content": n[2] or "", "order_index": n[3]}
            for n in nodes_result.fetchall()
        ]
        return json.dumps({
            "status": "success",
            "virtual_graph_name": virtual_graph_name,
            "keyword": keyword,
            "results": results
        }, ensure_ascii=False)

    return json.dumps({"status": "error", "message": f"Unknown tool: {tool_name}"}, ensure_ascii=False)

@router.post("/sessions", response_model=TeachingSessionResponse)
async def create_session(session: TeachingSessionCreate, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    new_session = TeachingSession(
        id=str(uuid4()),
        project_id=session.project_id,
        title=session.title if session.title else f"Session {uuid4().hex[:8]}",
        status="active"
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)
    
    first_message = Message(
        id=str(uuid4()),
        session_id=new_session.id,
        role="assistant",
        content="请开始讲解这个概念，我会提出问题来帮助你加深理解。"
    )
    db.add(first_message)
    await db.commit()
    
    return new_session

@router.get("/sessions/{session_id}")
async def get_session_detail(request: Request, session_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    session_result = await db.execute(text("SELECT * FROM teaching_sessions WHERE id = :session_id"), {"session_id": session_id})
    session_row = session_result.fetchone()
    
    if not session_row:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = dict(session_row._mapping)
    
    # 查询所有消息（包括 inactive）用于计算分支信息
    all_messages_result = await db.execute(text("SELECT * FROM messages WHERE session_id = :session_id ORDER BY created_at"), {"session_id": session_id})
    all_messages = [dict(row._mapping) for row in all_messages_result.fetchall()]
    
    # 只保留 active 的消息进行显示
    messages = [m for m in all_messages if m.get('is_active', 1) == 1]
    
    # 为每条消息计算分支信息
    for msg in messages:
        msg['branch_index'] = 1
        msg['branch_count'] = 1
    
    for i, msg in enumerate(messages):
        if msg['role'] == 'user':
            parent_id = msg.get('parent_id')
            
            if parent_id is None:
                # 根消息（parent_id=None）各自独立计数
                # 因为新消息的parent_id总是None，每个根消息应该是独立的
                msg['branch_count'] = 1
                msg['branch_index'] = 1
            else:
                # 有parent_id的消息，按parent_id分组
                same_parent_messages = []
                for m in all_messages:
                    if m.get('role') == 'user' and m.get('parent_id') == parent_id:
                        same_parent_messages.append(m)
                
                msg['branch_count'] = len(same_parent_messages)
                
                # 按创建时间排序
                same_parent_messages.sort(key=lambda x: x['created_at'])
                
                # 计算当前消息在分支中的位置
                msg['branch_index'] = next((idx + 1 for idx, m in enumerate(same_parent_messages) if m['id'] == msg['id']), 1)
    
    concepts_result = await db.execute(text("SELECT * FROM concepts WHERE session_id = :session_id"), {"session_id": session_id})
    concepts = [dict(row._mapping) for row in concepts_result.fetchall()]
    
    misconceptions_result = await db.execute(text("SELECT * FROM misconceptions WHERE session_id = :session_id"), {"session_id": session_id})
    misconceptions = [dict(row._mapping) for row in misconceptions_result.fetchall()]
    
    project_result = await db.execute(text("SELECT name FROM projects WHERE id = :project_id"), {"project_id": session["project_id"]})
    project = project_result.fetchone()
    project_name = project.name if project else ""
    
    mastered_concepts = [c for c in concepts if c.get("status") == "mastered"]
    promoted_concepts = [c for c in concepts if c.get("status") == "promoted"]
    total_concepts = len(concepts) + len(misconceptions)
    completed_concepts = len(mastered_concepts) + len(promoted_concepts)  # promoted也算已完成
    progress_percent = int((completed_concepts / max(total_concepts, 1)) * 100)
    
    # 获取正确的图谱ID：优先使用 source_note -> directory -> graph 的路径
    graph_id = None
    if session.get("source_note_id"):
        # 通过 source_note 找到目录，再找到图谱
        note_result = await db.execute(
            text("SELECT directory_id FROM notes WHERE id = :note_id"),
            {"note_id": session["source_note_id"]}
        )
        note_row = note_result.first()
        if note_row and note_row[0]:
            graph_result = await db.execute(
                text("SELECT id FROM graphs WHERE directory_id = :directory_id"),
                {"directory_id": note_row[0]}
            )
            graph_row = graph_result.first()
            if graph_row:
                graph_id = graph_row[0]
    
    # 如果没有找到，使用项目的第一个图谱
    if not graph_id:
        graph_result = await db.execute(
            text("SELECT id FROM graphs WHERE project_id = :project_id ORDER BY created_at LIMIT 1"),
            {"project_id": session["project_id"]}
        )
        graph_row = graph_result.first()
        graph_id = graph_row[0] if graph_row else None
    
    return HTMLResponse(jinja_env.get_template("teaching/session.html").render({
        "request": request,
        "user": current_user,
        "session_id": session_id,
        "project_id": session["project_id"],
        "project_name": project_name,
        "graph_id": graph_id,
        "messages": messages,
        "concepts": concepts,
        "misconceptions": misconceptions,
        "mastered": mastered_concepts,  # 传递已掌握概念列表，供侧边栏渲染使用
        "completed_concepts": completed_concepts,
        "total_concepts": max(total_concepts, 1),
        "progress_percent": progress_percent,
        "concept_name": session["title"]
    }))

@router.post("/sessions/{session_id}/messages")
async def create_message(session_id: str, message: MessageCreate, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    session_result = await db.execute(text("SELECT * FROM teaching_sessions WHERE id = :session_id"), {"session_id": session_id})
    session = session_result.fetchone()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # 检查是否在短时间内有相同内容的消息（防重复提交）
    recent_messages = await db.execute(
        text("SELECT * FROM messages WHERE session_id = :session_id AND role = 'user' AND content = :content ORDER BY created_at DESC LIMIT 1"),
        {"session_id": session_id, "content": message.content}
    )
    recent_msg = recent_messages.first()
    
    if recent_msg:
        # 如果10秒内有相同内容，返回已存在的消息ID
        return {"status": "ok", "message_id": recent_msg[0]}
    
    new_message = Message(
        id=str(uuid4()),
        session_id=session_id,
        role="user",
        content=message.content
    )
    db.add(new_message)
    await db.commit()
    await db.refresh(new_message)
    
    return {"status": "ok", "message_id": new_message.id}

@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
async def list_messages(session_id: str, branch_id: str = None, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    if branch_id:
        result = await db.execute(text("SELECT * FROM messages WHERE session_id = :session_id AND branch_id = :branch_id AND is_active = 1 ORDER BY created_at"), {"session_id": session_id, "branch_id": branch_id})
    else:
        result = await db.execute(text("SELECT * FROM messages WHERE session_id = :session_id AND branch_id IS NULL AND is_active = 1 ORDER BY created_at"), {"session_id": session_id})
    messages = result.fetchall()
    return [dict(row._mapping) for row in messages]



@router.put("/sessions/{session_id}/messages/{message_id}")
async def update_message_and_create_branch(session_id: str, message_id: str, message: MessageCreate, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    message_result = await db.execute(text("SELECT * FROM messages WHERE id = :message_id AND session_id = :session_id"), {"message_id": message_id, "session_id": session_id})
    original_message = message_result.first()
    
    if not original_message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    original_msg = dict(original_message._mapping)
    original_created_at = original_msg.get('created_at')
    
    # 删除此消息之后的所有消息
    await db.execute(text("DELETE FROM messages WHERE session_id = :session_id AND created_at > :created_at"), {"session_id": session_id, "created_at": original_created_at})
    
    # 更新当前消息的内容
    await db.execute(text("UPDATE messages SET content = :content WHERE id = :message_id"), {"content": message.content, "message_id": message_id})
    
    # 重新生成AI响应
    from app.services.teaching_agent import TeachingAgent
    
    agent = TeachingAgent(db, session_id)
    
    # 收集完整的响应文本和工具调用
    response_text = ''
    tool_calls_buffer = {}
    tool_call_ids = {}  # 存储 tool_call_id
    tool_results = {}  # 存储工具执行结果
    reasoning_content = ""  # 存储reasoning_content（OpenAI thinking模式要求）
    tool_calls_text_parts = []  # 存储工具调用的文本片段,用于插入到响应文本中

    print(f"Starting to process AI response in update_message...")
    
    async for chunk in agent.process_user_input(message.content):
        # 调试输出已关闭
        # print(f"Received chunk in update_message: {chunk}")
        
        if chunk['type'] == 'text':
            response_text += chunk['content']
        elif chunk['type'] == 'reasoning':
            # 保存reasoning_content（必须传回给后续API调用）
            reasoning_content += chunk['content']
            print(f"Received reasoning content in update_message: {len(chunk['content'])} chars")
        elif chunk['type'] == 'tool_call':
            tool_name = chunk['name']
            tool_id = chunk.get('id', '')
            print(f"Received tool call in update_message: {tool_name}")
            if tool_name not in tool_calls_buffer:
                tool_calls_buffer[tool_name] = ''
                tool_call_ids[tool_name] = tool_id
            tool_calls_buffer[tool_name] += chunk['arguments']
    
    print(f"Finished processing AI response in update_message. Tool calls: {tool_calls_buffer}")

    # 创建新的AI响应消息（工具调用XML会在所有工具执行完后统一追加到消息内容中，见update_message_and_create_branch末尾）
    # parent_id 指向被编辑的user消息，保证SSE幂等检查能识别"已有回复"，避免与流式路径双写
    assistant_message = Message(
        id=str(uuid4()),
        session_id=session_id,
        parent_id=message_id,
        role="assistant",
        content=response_text,
        is_active=True
    )
    db.add(assistant_message)
    
    # 处理工具调用
    for tool_name, arguments_str in tool_calls_buffer.items():
        try:
            arguments = json.loads(arguments_str)
            print(f"Processing tool call in update_message: {tool_name}, arguments: {arguments}")

            if tool_name == 'task_complete':
                # 收到task_complete工具调用,标记任务已完成
                task_completed = True
                print(f"Task completed in update_message: {arguments.get('summary', '')}")
                # 将工具调用信息格式化为文本
                result_json = json.dumps({"status": "success", "summary": arguments.get("summary", "")}, ensure_ascii=False)
                tool_call_text = f'<tool_call iteration="0" timestamp="{datetime.utcnow().isoformat()}">\n  <name>{tool_name}</name>\n  <arguments>{json.dumps(arguments, ensure_ascii=False)}</arguments>\n  <result>{result_json}</result>\n</tool_call>\n'
                tool_calls_text_parts.append(tool_call_text)
                continue

            # 记录工具调用信息(在执行前),用于后续插入到文本中
            tool_call_text_start = f'<tool_call iteration="0" timestamp="{datetime.utcnow().isoformat()}">\n  <name>{tool_name}</name>\n  <arguments>{json.dumps(arguments, ensure_ascii=False)}</arguments>\n'

            if tool_name == 'mark_concepts_mastered':
                concepts = arguments.get('concepts', [])

                # 获取当前session的所有概念列表
                all_concepts_result = await db.execute(
                    text("SELECT name, status FROM concepts WHERE session_id = :session_id"),
                    {"session_id": session_id}
                )
                all_concepts = {row[0]: row[1] for row in all_concepts_result.fetchall()}
                unmastered_concepts = [name for name, status in all_concepts.items() if status != 'mastered']

                for concept_data in concepts:
                    concept_name = concept_data.get('concept_name')
                    summary = concept_data.get('summary')

                    # 检查概念是否存在于当前session
                    if concept_name not in all_concepts:
                        # 概念不存在，返回错误信息和未掌握概念列表
                        error_msg = f"错误：概念【{concept_name}】不存在于当前教学session中。"
                        if unmastered_concepts:
                            error_msg += f"\n当前未掌握的概念列表：{', '.join(unmastered_concepts)}"
                        else:
                            error_msg += "\n当前没有未掌握的概念。"
                        print(f"Concept not found in update_message: {concept_name}")
                        tool_results['mark_concepts_mastered'] = json.dumps({
                            "status": "error",
                            "message": error_msg,
                            "unmastered_concepts": unmastered_concepts
                        }, ensure_ascii=False)
                        continue

                    existing_concept = await db.execute(
                        text("SELECT * FROM concepts WHERE session_id = :session_id AND name = :name"),
                        {"session_id": session_id, "name": concept_name}
                    )
                    existing = existing_concept.first()
                    print(f"Existing concept in update_message: {existing}")

                    if existing:
                        # 更新现有概念的状态为mastered
                        await db.execute(
                            text("UPDATE concepts SET status = 'mastered', description = :description WHERE id = :id"),
                            {"description": summary, "id": existing[0]}
                        )
                        concept_id = existing[0]
                        print(f"Updated concept status to mastered in update_message: {concept_name}")

                        # 更新关联节点的掌握度为 30%
                        node_result = await db.execute(
                            text("SELECT id FROM nodes WHERE concept_id = :cid"),
                            {"cid": concept_id}
                        )
                        node_row = node_result.first()
                        if node_row:
                            await db.execute(
                                text("UPDATE nodes SET mastery_score = 0.3 WHERE id = :nid"),
                                {"nid": node_row[0]}
                            )
                            print(f"Updated node mastery_score to 0.3 for concept: {concept_name}")
            
            elif tool_name == 'mark_misconception':
                concept_name = arguments.get('concept_name')
                misconception = arguments.get('misconception')
                correction = arguments.get('correction')

                new_misconception = Misconception(
                    id=str(uuid4()),
                    session_id=session_id,
                    concept_name=concept_name,
                    user_claim=message.content,
                    ai_correction=correction,
                    resolved=False
                )
                db.add(new_misconception)
                print(f"Added new misconception in update_message: {concept_name}")

            # ====== Integration Level 工具 ======
            elif tool_name == 'create_graph_node':
                label = arguments.get('label')
                description = arguments.get('description', '')
                mastery_score = arguments.get('mastery_score', 0)

                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for create_graph_node")
                    continue
                project_id = session_row[0]

                # 获取或创建项目的第一个图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    # 创建默认图谱
                    graph_id = str(uuid4())
                    await db.execute(
                        text("INSERT INTO graphs (id, project_id, name, created_at, updated_at) VALUES (:id, :pid, '知识图谱', datetime('now'), datetime('now'))"),
                        {"id": graph_id, "pid": project_id}
                    )
                else:
                    graph_id = graph_row[0]

                # 创建节点
                node_id = str(uuid4())
                await db.execute(
                    text("INSERT INTO nodes (id, graph_id, label, mastery_score) VALUES (:id, :gid, :label, :ms)"),
                    {"id": node_id, "gid": graph_id, "label": label, "ms": mastery_score}
                )
                print(f"Created graph node: {label}")

            elif tool_name == 'create_graph_edge':
                source_label = arguments.get('source_label')
                target_label = arguments.get('target_label')
                relation = arguments.get('relation', 'related')
                edge_label = arguments.get('label', '')

                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for create_graph_edge")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for create_graph_edge")
                    continue
                graph_id = graph_row[0]

                # 查找源节点和目标节点
                source_node = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": source_label}
                )
                source_row = source_node.first()
                target_node = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": target_label}
                )
                target_row = target_node.first()

                if source_row and target_row:
                    edge_id = str(uuid4())
                    await db.execute(
                        text("INSERT INTO edges (id, graph_id, source_node_id, target_node_id, relation, label, weight) VALUES (:id, :gid, :src, :tgt, :rel, :lbl, 1.0)"),
                        {"id": edge_id, "gid": graph_id, "src": source_row[0], "tgt": target_row[0], "rel": relation, "lbl": edge_label}
                    )
                    print(f"Created graph edge: {source_label} -> {target_label} ({relation})")
                else:
                    print(f"Nodes not found for edge: {source_label} or {target_label}")

            elif tool_name == 'update_graph_node':
                label = arguments.get('label')
                new_description = arguments.get('description')
                new_mastery = arguments.get('mastery_score')

                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for update_graph_node")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for update_graph_node")
                    continue
                graph_id = graph_row[0]

                # 查找节点
                node_result = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": label}
                )
                node_row = node_result.first()
                if node_row:
                    updates = []
                    params = {"nid": node_row[0]}
                    if new_description is not None:
                        updates.append("description = :desc")
                        params["desc"] = new_description
                    if new_mastery is not None:
                        updates.append("mastery_score = :ms")
                        params["ms"] = new_mastery
                    if updates:
                        sql = f"UPDATE nodes SET {', '.join(updates)} WHERE id = :nid"
                        await db.execute(text(sql), params)
                        print(f"Updated graph node: {label}")
                else:
                    print(f"Node not found for update: {label}")

            elif tool_name == 'delete_graph_node':
                label = arguments.get('label')

                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for delete_graph_node")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for delete_graph_node")
                    continue
                graph_id = graph_row[0]

                # 查找节点
                node_result = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": label}
                )
                node_row = node_result.first()
                if node_row:
                    node_id = node_row[0]
                    # 删除关联的边
                    await db.execute(
                        text("DELETE FROM edges WHERE source_node_id = :nid OR target_node_id = :nid"),
                        {"nid": node_id}
                    )
                    # 删除节点
                    await db.execute(
                        text("DELETE FROM nodes WHERE id = :nid"),
                        {"nid": node_id}
                    )
                    print(f"Deleted graph node: {label}")
                else:
                    print(f"Node not found for delete: {label}")

            elif tool_name == 'delete_graph_edge':
                source_label = arguments.get('source_label')
                target_label = arguments.get('target_label')

                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for delete_graph_edge")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for delete_graph_edge")
                    continue
                graph_id = graph_row[0]

                # 查找源节点和目标节点
                source_node = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": source_label}
                )
                source_row = source_node.first()
                target_node = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": target_label}
                )
                target_row = target_node.first()

                if source_row and target_row:
                    await db.execute(
                        text("DELETE FROM edges WHERE graph_id = :gid AND source_node_id = :src AND target_node_id = :tgt"),
                        {"gid": graph_id, "src": source_row[0], "tgt": target_row[0]}
                    )
                    print(f"Deleted graph edge: {source_label} -> {target_label}")
                else:
                    print(f"Nodes not found for edge delete: {source_label} or {target_label}")

            elif tool_name == 'get_graph_nodes':
                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for get_graph_nodes")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for get_graph_nodes")
                    continue
                graph_id = graph_row[0]

                # 获取所有节点
                nodes_result = await db.execute(
                    text("SELECT label, description, mastery_score FROM nodes WHERE graph_id = :gid ORDER BY label"),
                    {"gid": graph_id}
                )
                nodes = nodes_result.fetchall()
                node_list = [{"label": n[0], "description": n[1] or "", "mastery_score": n[2]} for n in nodes]
                print(f"Retrieved {len(node_list)} nodes from graph")
                tool_results['get_graph_nodes'] = json.dumps(node_list, ensure_ascii=False)

            elif tool_name == 'get_graph_node':
                label = arguments.get('label')

                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for get_graph_node")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for get_graph_node")
                    continue
                graph_id = graph_row[0]

                # 查找节点
                node_result = await db.execute(
                    text("SELECT label, description, mastery_score FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": label}
                )
                node_row = node_result.first()
                if node_row:
                    node_info = {"label": node_row[0], "description": node_row[1] or "", "mastery_score": node_row[2]}
                    print(f"Retrieved node: {label}")
                else:
                    print(f"Node not found: {label}")

            elif tool_name == 'get_graph_edges':
                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for get_graph_edges")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for get_graph_edges")
                    continue
                graph_id = graph_row[0]

                # 获取所有边
                edges_result = await db.execute(
                    text("""SELECT sn.label as source_label, tn.label as target_label, e.relation, e.label
                           FROM edges e
                           JOIN nodes sn ON e.source_node_id = sn.id
                           JOIN nodes tn ON e.target_node_id = tn.id
                           WHERE e.graph_id = :gid ORDER BY e.relation"""),
                    {"gid": graph_id}
                )
                edges = edges_result.fetchall()
                edge_list = [{"source": e[0], "target": e[1], "relation": e[2], "label": e[3] or ""} for e in edges]
                print(f"Retrieved {len(edge_list)} edges from graph")

            elif tool_name == 'get_node_edges':
                label = arguments.get('label')

                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for get_node_edges")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for get_node_edges")
                    continue
                graph_id = graph_row[0]

                # 查找节点
                node_result = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": label}
                )
                node_row = node_result.first()
                if node_row:
                    node_id = node_row[0]
                    # 获取节点相关的边
                    edges_result = await db.execute(
                        text("""SELECT sn.label as source_label, tn.label as target_label, e.relation, e.label
                               FROM edges e
                               JOIN nodes sn ON e.source_node_id = sn.id
                               JOIN nodes tn ON e.target_node_id = tn.id
                               WHERE e.graph_id = :gid AND (e.source_node_id = :nid OR e.target_node_id = :nid)"""),
                        {"gid": graph_id, "nid": node_id}
                    )
                    edges = edges_result.fetchall()
                    edge_list = [{"source": e[0], "target": e[1], "relation": e[2], "label": e[3] or ""} for e in edges]
                    print(f"Retrieved {len(edge_list)} edges for node: {label}")
                else:
                    print(f"Node not found: {label}")

            # ====== 虚拟图工具 ======
            elif tool_name == 'create_virtual_graph':
                vg_name = arguments.get('name')
                vg_description = arguments.get('description', '')
                nodes = arguments.get('nodes', [])
                edges = arguments.get('edges', [])
                node_connections = arguments.get('node_connections') or arguments.get('connected_nodes', [])

                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for create_virtual_graph")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                graph_id = graph_row[0] if graph_row else None

                # 调用虚拟图创建API
                vg_result = await db.execute(
                    text("SELECT id FROM virtual_graphs WHERE session_id = :sid AND name = :name"),
                    {"sid": session_id, "name": vg_name}
                )
                existing_vg = vg_result.first()

                if existing_vg:
                    print(f"Virtual graph already exists: {vg_name}")
                    tool_results['create_virtual_graph'] = json.dumps({"status": "exists", "name": vg_name}, ensure_ascii=False)
                else:
                    # 创建虚拟图（复用integration.py的逻辑）
                    vg_id = str(uuid4())
                    await db.execute(
                        text("INSERT INTO virtual_graphs (id, session_id, graph_id, name, description, created_at, updated_at) VALUES (:id, :sid, :gid, :name, :desc, datetime('now'), datetime('now'))"),
                        {"id": vg_id, "sid": session_id, "gid": graph_id, "name": vg_name, "desc": vg_description}
                    )

                    # 创建虚拟图节点
                    vnode_ids = {}
                    for idx, node_data in enumerate(nodes):
                        vnode_id = str(uuid4())
                        label = node_data.get('label')
                        # properties字段：二元组列表 [[和node的关系, 名称], ...]
                        properties_json = json.dumps(node_data.get('properties', []), ensure_ascii=False)
                        content = node_data.get('content', '')
                        mastery = node_data.get('mastery_score', 0)

                        await db.execute(
                            text("""INSERT INTO virtual_graph_nodes (id, virtual_graph_id, label, properties, content, order_index, mastery_score)
                                   VALUES (:id, :vgid, :label, :props, :content, :idx, :ms)"""),
                            {"id": vnode_id, "vgid": vg_id, "label": label, "props": properties_json, "content": content, "idx": idx, "ms": mastery}
                        )
                        vnode_ids[label] = vnode_id

                    # 创建虚拟图内部边
                    for edge_data in edges:
                        source_label = edge_data.get('source')
                        target_label = edge_data.get('target')
                        relation = edge_data.get('relation', 'related')
                        label = edge_data.get('label', '')

                        if source_label in vnode_ids and target_label in vnode_ids:
                            edge_id = str(uuid4())
                            await db.execute(
                                text("""INSERT INTO virtual_graph_edges (id, virtual_graph_id, source_vnode_id, target_vnode_id, relation, label)
                                       VALUES (:id, :vgid, :src, :tgt, :rel, :lbl)"""),
                                {"id": edge_id, "vgid": vg_id, "src": vnode_ids[source_label], "tgt": vnode_ids[target_label], "rel": relation, "lbl": label}
                            )

                    # 创建虚拟图到真实节点的连接
                    if graph_id:
                        for conn_data in node_connections:
                            node_label = conn_data.get('node_label')
                            relation_type = conn_data.get('relation_type', 'contains')

                            # 查找真实节点
                            node_result = await db.execute(
                                text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                                {"gid": graph_id, "label": node_label}
                            )
                            node_row = node_result.first()
                            if node_row:
                                conn_id = str(uuid4())
                                await db.execute(
                                    text("""INSERT INTO virtual_graph_to_node_edges (id, virtual_graph_id, node_id, relation_type)
                                           VALUES (:id, :vgid, :nid, :rtype)"""),
                                    {"id": conn_id, "vgid": vg_id, "nid": node_row[0], "rtype": relation_type}
                                )

                    print(f"Created virtual graph: {vg_name} with {len(nodes)} nodes")
                    # 注意：这是一个PUT路由，不应该使用yield发送SSE消息

                    # 生成虚拟图的embedding（用于RAG搜索）
                    try:
                        from app.services.embedding_service import get_embedding_service
                        embedding_service = get_embedding_service()

                        # 组合虚拟图内容为文本（用于embedding）
                        content_text = f"{vg_name}\n{vg_description}\n"
                        for node_data in nodes:
                            label = node_data.get('label')
                            desc = node_data.get('description', '')
                            content = node_data.get('content', '')
                            content_text += f"{label}: {desc} {content}\n"

                        # 生成embedding向量
                        embedding_vector = embedding_service.generate_embedding(content_text)
                        embedding_json = json.dumps(embedding_vector)

                        # 存储embedding
                        embedding_id = str(uuid4())
                        await db.execute(
                            text("INSERT INTO virtual_graph_embeddings (id, virtual_graph_id, embedding) VALUES (:id, :vgid, :emb)"),
                            {"id": embedding_id, "vgid": vg_id, "emb": embedding_json}
                        )
                        await db.commit()

                        print(f"Generated embedding for virtual graph: {vg_name}")
                    except Exception as e:
                        print(f"Error generating embedding for virtual graph: {e}")
                        # 不影响主流程，继续执行

            elif tool_name == 'get_virtual_graphs':
                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for get_virtual_graphs")
                    continue
                project_id = session_row[0]

                # 获取虚拟图列表
                vg_result = await db.execute(
                    text("""SELECT vg.*, ts.title as session_title
                           FROM virtual_graphs vg
                           LEFT JOIN teaching_sessions ts ON vg.session_id = ts.id
                           WHERE ts.project_id = :pid
                           ORDER BY vg.created_at DESC"""),
                    {"pid": project_id}
                )
                vg_list = vg_result.fetchall()
                vg_data = [{"name": vg[3], "description": vg[4] or "", "session_title": vg[7] or ""} for vg in vg_list]
                print(f"Retrieved {len(vg_data)} virtual graphs")
                tool_results['get_virtual_graphs'] = json.dumps(vg_data, ensure_ascii=False)

            elif tool_name == 'get_virtual_graph':
                vg_name = arguments.get('name')

                # 查找虚拟图
                vg_result = await db.execute(
                    text("SELECT * FROM virtual_graphs WHERE session_id = :sid AND name = :name"),
                    {"sid": session_id, "name": vg_name}
                )
                vg_row = vg_result.first()
                if not vg_row:
                    print(f"Virtual graph not found: {vg_name}")
                    tool_results['get_virtual_graph'] = json.dumps({"error": "Not found"}, ensure_ascii=False)
                    continue

                vg_id = vg_row[0]

                # 获取节点
                nodes_result = await db.execute(
                    text("SELECT label, properties, content, mastery_score FROM virtual_graph_nodes WHERE virtual_graph_id = :vgid ORDER BY order_index"),
                    {"vgid": vg_id}
                )
                nodes = nodes_result.fetchall()
                node_list = []
                for n in nodes:
                    props = []
                    try:
                        props = json.loads(n[1]) if n[1] else []
                    except Exception:
                        props = []
                    node_list.append({"label": n[0], "properties": props, "content": n[2] or "", "mastery_score": n[3]})

                # 获取边
                edges_result = await db.execute(
                    text("""SELECT svn.label as source, tvn.label as target, vge.relation, vge.label
                           FROM virtual_graph_edges vge
                           JOIN virtual_graph_nodes svn ON vge.source_vnode_id = svn.id
                           JOIN virtual_graph_nodes tvn ON vge.target_vnode_id = tvn.id
                           WHERE vge.virtual_graph_id = :vgid"""),
                    {"vgid": vg_id}
                )
                edges = edges_result.fetchall()
                edge_list = [{"source": e[0], "target": e[1], "relation": e[2], "label": e[3] or ""} for e in edges]

                vg_data = {"name": vg_row[3], "description": vg_row[4] or "", "nodes": node_list, "edges": edge_list}
                print(f"Retrieved virtual graph: {vg_name}")
                tool_results['get_virtual_graph'] = json.dumps(vg_data, ensure_ascii=False)

            elif tool_name == 'update_virtual_graph':
                vg_name = arguments.get('name')
                new_name = arguments.get('new_name')
                new_description = arguments.get('new_description')

                # 查找虚拟图
                vg_result = await db.execute(
                    text("SELECT id FROM virtual_graphs WHERE session_id = :sid AND name = :name"),
                    {"sid": session_id, "name": vg_name}
                )
                vg_row = vg_result.first()
                if not vg_row:
                    print(f"Virtual graph not found for update: {vg_name}")
                    continue

                vg_id = vg_row[0]
                updates = []
                params = {"vgid": vg_id}
                if new_name:
                    updates.append("name = :new_name")
                    params["new_name"] = new_name
                if new_description:
                    updates.append("description = :new_desc")
                    params["new_desc"] = new_description

                if updates:
                    sql = f"UPDATE virtual_graphs SET {', '.join(updates)}, updated_at = datetime('now') WHERE id = :vgid"
                    await db.execute(text(sql), params)
                    print(f"Updated virtual graph: {vg_name}")
                    # 注意：这是一个PUT路由，不应该使用yield发送SSE消息

            elif tool_name == 'delete_virtual_graph':
                vg_name = arguments.get('name')

                # 查找虚拟图
                vg_result = await db.execute(
                    text("SELECT id FROM virtual_graphs WHERE session_id = :sid AND name = :name"),
                    {"sid": session_id, "name": vg_name}
                )
                vg_row = vg_result.first()
                if not vg_row:
                    print(f"Virtual graph not found for delete: {vg_name}")
                    continue

                vg_id = vg_row[0]
                # 删除相关数据
                await db.execute(text("DELETE FROM virtual_graph_to_node_edges WHERE virtual_graph_id = :vgid"), {"vgid": vg_id})
                await db.execute(text("DELETE FROM virtual_graph_edges WHERE virtual_graph_id = :vgid"), {"vgid": vg_id})
                await db.execute(text("DELETE FROM virtual_graph_nodes WHERE virtual_graph_id = :vgid"), {"vgid": vg_id})
                await db.execute(text("DELETE FROM virtual_graph_embeddings WHERE virtual_graph_id = :vgid"), {"vgid": vg_id})
                await db.execute(text("DELETE FROM virtual_graphs WHERE id = :vgid"), {"vgid": vg_id})
                print(f"Deleted virtual graph: {vg_name}")
                # 注意：这是一个PUT路由，不应该使用yield发送SSE消息

            elif tool_name == 'search_virtual_graphs_rag':
                # 使用RAG搜索虚拟图
                query = arguments.get('query')
                top_k = arguments.get('top_k', 5)
                
                print(f"Searching virtual graphs with RAG: query={query}, top_k={top_k}")
                
                # 获取project_id
                session_result = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_result.first()
                if session_row:
                    project_id = session_row[0]
                    
                    # 使用embedding_service进行RAG搜索
                    from app.services.embedding_service import get_embedding_service
                    embedding_service = get_embedding_service()
                    
                    # 调用search_virtual_graphs方法
                    db_path = "data/r6ax.db"  # 数据库路径
                    search_results = embedding_service.search_virtual_graphs(
                        db_path=db_path,
                        query=query,
                        project_id=project_id,
                        top_k=top_k
                    )
                    
                    print(f"RAG search found {len(search_results)} results")
                    # 将搜索结果返回给AI
                    tool_results['search_virtual_graphs_rag'] = json.dumps({
                        "status": "success",
                        "results": search_results,
                        "query": query
                    }, ensure_ascii=False)
                else:
                    print(f"Session not found: {session_id}")
                    tool_results['search_virtual_graphs_rag'] = json.dumps({
                        "status": "error",
                        "message": "Session not found"
                    }, ensure_ascii=False)

            elif tool_name == 'search_virtual_graph_nodes':
                # 按关键词搜索指定虚拟图中的节点
                virtual_graph_name = arguments.get('virtual_graph_name')
                keyword = arguments.get('keyword')
                top_k = arguments.get('top_k', 5)
                
                print(f"Searching virtual graph nodes: vg_name={virtual_graph_name}, keyword={keyword}, top_k={top_k}")
                
                # 获取project_id
                session_result = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_result.first()
                if session_row:
                    project_id = session_row[0]
                    
                    # 查找指定的虚拟图（virtual_graphs没有project_id列，需通过teaching_sessions关联）
                    vg_result = await db.execute(
                        text("""SELECT vg.id FROM virtual_graphs vg
                               JOIN teaching_sessions ts ON vg.session_id = ts.id
                               WHERE ts.project_id = :pid AND vg.name = :name"""),
                        {"pid": project_id, "name": virtual_graph_name}
                    )
                    vg_row = vg_result.first()
                    
                    if vg_row:
                        vg_id = vg_row[0]
                        
                        # 搜索虚拟图节点（按label、content搜索；virtual_graph_nodes没有description列）
                        nodes_result = await db.execute(
                            text("""SELECT id, label, content, order_index
                                   FROM virtual_graph_nodes
                                   WHERE virtual_graph_id = :vg_id
                                   AND (label LIKE :keyword OR content LIKE :keyword)
                                   ORDER BY order_index
                                   LIMIT :top_k"""),
                            {"vg_id": vg_id, "keyword": f"%{keyword}%", "top_k": top_k}
                        )
                        nodes = nodes_result.fetchall()
                        
                        # 构建结果列表
                        results = []
                        for node in nodes:
                            results.append({
                                "node_id": node[0],
                                "label": node[1],
                                "content": node[2] or "",
                                "order_index": node[3]
                            })
                        
                        print(f"Found {len(results)} nodes matching keyword '{keyword}' in virtual graph '{virtual_graph_name}'")
                        tool_results['search_virtual_graph_nodes'] = json.dumps({
                            "status": "success",
                            "virtual_graph_name": virtual_graph_name,
                            "keyword": keyword,
                            "results": results
                        }, ensure_ascii=False)
                    else:
                        print(f"Virtual graph not found: {virtual_graph_name}")
                        tool_results['search_virtual_graph_nodes'] = json.dumps({
                            "status": "error",
                            "message": f"Virtual graph '{virtual_graph_name}' not found"
                        }, ensure_ascii=False)
                else:
                    print(f"Session not found: {session_id}")
                    tool_results['search_virtual_graph_nodes'] = json.dumps({
                        "status": "error",
                        "message": "Session not found"
                    }, ensure_ascii=False)

        except Exception as e:
            print(f"Error processing tool call in update_message: {e}")
            # 将错误信息添加到工具调用文本中
            error_result = json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)
            tool_call_text = tool_call_text_start + f'  <result>{error_result}</result>\n</tool_call>\n'
            tool_calls_text_parts.append(tool_call_text)

    await db.commit()
    print(f"Database committed in update_message")

    # 处理工具调用的循环：AI可能需要多轮工具调用
    # max_iterations设置为一个较大的值,主要依赖task_complete工具来结束循环
    max_iterations = 50  # 设置为50次,防止真正的无限循环
    iteration = 0
    task_completed = False  # 跟踪是否收到task_complete工具调用

    while (tool_results or tool_calls_buffer) and iteration < max_iterations and not task_completed:
        iteration += 1
        print(f"Tool call iteration {iteration} in update_message")
        
        # 构建工具消息
        tool_messages = []
        
        # 添加读取工具的结果
        for tool_name, result in tool_results.items():
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_ids.get(tool_name, f"call_{tool_name}"),
                "name": tool_name,
                "content": result
            })
        
        # 对于非读取工具，添加成功结果
        read_tools = ['get_graph_nodes', 'get_graph_node', 'get_graph_edges', 'get_node_edges']
        for tool_name in tool_calls_buffer.keys():
            if tool_name not in tool_results and tool_name not in read_tools:
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_ids.get(tool_name, f"call_{tool_name}"),
                    "name": tool_name,
                    "content": json.dumps({"status": "success"}, ensure_ascii=False)
                })
        
        if not tool_messages:
            break
        
        print(f"Sending tool results to AI: {len(tool_messages)} messages")
        
        # 重置变量
        tool_calls_buffer = {}
        tool_call_ids = {}
        tool_results = {}
        continuation_response = ''
        
        async for chunk in agent.process_tool_results(tool_messages, reasoning_content):
            if chunk['type'] == 'text':
                continuation_response += chunk['content']
            elif chunk['type'] == 'reasoning':
                # 更新reasoning_content（如果有新的）
                reasoning_content += chunk['content']
                print(f"Received new reasoning content in continuation: {len(chunk['content'])} chars")
            elif chunk['type'] == 'tool_call':
                tool_name = chunk['name']
                tool_id = chunk.get('id', '')
                if tool_name not in tool_calls_buffer:
                    tool_calls_buffer[tool_name] = ''
                    tool_call_ids[tool_name] = tool_id
                tool_calls_buffer[tool_name] += chunk['arguments']
                print(f"Received tool call in continuation: {tool_name}")
        
        # 更新AI消息内容
        if continuation_response:
            await db.execute(
                text("UPDATE messages SET content = content || :extra WHERE id = :mid"),
                {"extra": continuation_response, "mid": assistant_message.id}
            )
            response_text += continuation_response
        
        # 处理新一轮的工具调用（需要实际执行数据库操作）
        for tool_name, arguments_str in tool_calls_buffer.items():
            try:
                arguments = json.loads(arguments_str)
                print(f"Processing continuation tool call: {tool_name}")

                # 记录工具调用信息(在执行前)
                tool_call_text_start = f'<tool_call iteration="{iteration}" timestamp="{datetime.utcnow().isoformat()}">\n  <name>{tool_name}</name>\n  <arguments>{json.dumps(arguments, ensure_ascii=False)}</arguments>\n'

                if tool_name == 'task_complete':
                    # 收到task_complete工具调用,标记任务已完成
                    task_completed = True
                    print(f"Task completed in continuation of update_message: {arguments.get('summary', '')}")
                    # 将工具调用信息格式化为文本
                    result_json = json.dumps({"status": "success", "summary": arguments.get("summary", "")}, ensure_ascii=False)
                    tool_call_text = tool_call_text_start + f'  <result>{result_json}</result>\n</tool_call>\n'
                    tool_calls_text_parts.append(tool_call_text)
                    continue

                if tool_name == 'create_graph_node':
                    label = arguments.get('label')
                    description = arguments.get('description', '')
                    mastery_score = arguments.get('mastery_score', 0)
                    
                    # 获取正确的图谱ID：优先使用 source_note -> directory -> graph 的路径
                    session_info = await db.execute(
                        text("SELECT project_id, source_note_id FROM teaching_sessions WHERE id = :sid"),
                        {"sid": session_id}
                    )
                    session_row = session_info.first()
                    if session_row:
                        project_id = session_row[0]
                        source_note_id = session_row[1]
                        print(f"Found project_id: {project_id}, source_note_id: {source_note_id}")

                        # 优先使用 source_note -> directory -> graph 的路径
                        graph_id = None
                        if source_note_id:
                            # 通过 source_note 找到目录，再找到图谱
                            note_result = await db.execute(
                                text("SELECT directory_id FROM notes WHERE id = :note_id"),
                                {"note_id": source_note_id}
                            )
                            note_row = note_result.first()
                            if note_row and note_row[0]:
                                graph_result = await db.execute(
                                    text("SELECT id FROM graphs WHERE directory_id = :directory_id"),
                                    {"directory_id": note_row[0]}
                                )
                                graph_row = graph_result.first()
                                if graph_row:
                                    graph_id = graph_row[0]
                                    print(f"Found graph_id from source_note: {graph_id}")

                        # 如果没有找到，使用项目的第一个图谱
                        if not graph_id:
                            graph_result = await db.execute(
                                text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                                {"pid": project_id}
                            )
                            graph_row = graph_result.first()
                            if graph_row:
                                graph_id = graph_row[0]
                                print(f"Found graph_id from project: {graph_id}")

                        if graph_id:
                            node_id = str(uuid4())
                            await db.execute(
                                text("INSERT INTO nodes (id, graph_id, label, description, mastery_score) VALUES (:id, :gid, :label, :desc, :ms)"),
                                {"id": node_id, "gid": graph_id, "label": label, "desc": description, "ms": float(mastery_score)}
                            )
                            print(f"Created node in continuation: {label} with id {node_id} in graph {graph_id}")
                            tool_results['create_graph_node'] = json.dumps({"status": "success", "label": label, "node_id": node_id}, ensure_ascii=False)
                            # 注意：这是一个PUT路由处理函数中的continuation处理，不应该使用yield发送SSE消息
                            # SSE通知只在generate_streaming_response函数中发送
                        else:
                            print(f"No graph found for project {project_id}")
                            tool_results['create_graph_node'] = json.dumps({"status": "error", "message": "No graph found"}, ensure_ascii=False)
                    else:
                        print(f"No session found for session_id {session_id}")
                
                elif tool_name == 'update_graph_node':
                    label = arguments.get('label')
                    mastery_score = arguments.get('mastery_score')
                    
                    session_info = await db.execute(text("SELECT project_id FROM teaching_sessions WHERE id = :sid"), {"sid": session_id})
                    session_row = session_info.first()
                    if session_row:
                        project_id = session_row[0]
                        graph_result = await db.execute(text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"), {"pid": project_id})
                        graph_row = graph_result.first()
                        if graph_row:
                            graph_id = graph_row[0]
                            if mastery_score:
                                await db.execute(
                                    text("UPDATE nodes SET mastery_score = :ms WHERE graph_id = :gid AND label = :label"),
                                    {"ms": float(mastery_score), "gid": graph_id, "label": label}
                                )
                                print(f"Updated node mastery in continuation: {label} -> {mastery_score}")
                            tool_results['update_graph_node'] = json.dumps({"status": "success"}, ensure_ascii=False)
                
                elif tool_name == 'delete_graph_node':
                    label = arguments.get('label')
                    
                    session_info = await db.execute(text("SELECT project_id FROM teaching_sessions WHERE id = :sid"), {"sid": session_id})
                    session_row = session_info.first()
                    if session_row:
                        project_id = session_row[0]
                        graph_result = await db.execute(text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"), {"pid": project_id})
                        graph_row = graph_result.first()
                        if graph_row:
                            graph_id = graph_row[0]
                            node_result = await db.execute(text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"), {"gid": graph_id, "label": label})
                            node_row = node_result.first()
                            if node_row:
                                node_id = node_row[0]
                                await db.execute(text("DELETE FROM edges WHERE source_node_id = :nid OR target_node_id = :nid"), {"nid": node_id})
                                await db.execute(text("DELETE FROM nodes WHERE id = :nid"), {"nid": node_id})
                                print(f"Deleted node in continuation: {label}")
                            tool_results['delete_graph_node'] = json.dumps({"status": "success"}, ensure_ascii=False)
                
                elif tool_name == 'mark_concepts_mastered':
                    # 处理概念标记
                    concepts = arguments.get('concepts', [])

                    # 获取当前session的所有概念列表
                    all_concepts_result = await db.execute(
                        text("SELECT name, status FROM concepts WHERE session_id = :session_id"),
                        {"session_id": session_id}
                    )
                    all_concepts = {row[0]: row[1] for row in all_concepts_result.fetchall()}
                    unmastered_concepts = [name for name, status in all_concepts.items() if status != 'mastered']

                    has_error = False
                    for concept_data in concepts:
                        concept_name = concept_data.get('concept_name')
                        summary = concept_data.get('summary')

                        # 检查概念是否存在于当前session
                        if concept_name not in all_concepts:
                            # 概念不存在，返回错误信息
                            error_msg = f"错误：概念【{concept_name}】不存在于当前教学session中。"
                            if unmastered_concepts:
                                error_msg += f"\n当前未掌握的概念列表：{', '.join(unmastered_concepts)}"
                            else:
                                error_msg += "\n当前没有未掌握的概念。"
                            print(f"Concept not found in continuation: {concept_name}")
                            tool_results['mark_concepts_mastered'] = json.dumps({
                                "status": "error",
                                "message": error_msg,
                                "unmastered_concepts": unmastered_concepts
                            }, ensure_ascii=False)
                            has_error = True
                            continue

                        existing_concept = await db.execute(
                            text("SELECT * FROM concepts WHERE session_id = :session_id AND name = :name"),
                            {"session_id": session_id, "name": concept_name}
                        )
                        existing = existing_concept.first()
                        if existing:
                            await db.execute(
                                text("UPDATE concepts SET status = 'mastered', description = :description WHERE id = :id"),
                                {"description": summary, "id": existing[0]}
                            )
                            print(f"Marked concept as mastered in continuation: {concept_name}")

                    if not has_error:
                        tool_results['mark_concepts_mastered'] = json.dumps({"status": "success"}, ensure_ascii=False)
                
                elif tool_name in VIRTUAL_GRAPH_TOOLS:
                    # 虚拟图工具：必须真正执行并返回真实结果，否则AI会误以为参数没传对
                    tool_results[tool_name] = await _execute_virtual_graph_tool(db, session_id, tool_name, arguments)
                    result_text = tool_results[tool_name]
                    print(f"Executed virtual graph tool in continuation: {tool_name}, result: {result_text}")
                elif tool_name in read_tools:
                    # 读取工具返回结果
                    tool_results[tool_name] = json.dumps({"result": "processed"}, ensure_ascii=False)
                    result_text = tool_results[tool_name]
                else:
                    tool_results[tool_name] = json.dumps({"status": "success"}, ensure_ascii=False)
                    result_text = '{"status": "success"}'

                # 将工具调用信息格式化为文本
                tool_call_text = tool_call_text_start + f'  <result>{result_text}</result>\n</tool_call>\n'
                tool_calls_text_parts.append(tool_call_text)

            except Exception as e:
                print(f"Error in continuation: {e}")
                # 将错误信息添加到工具调用文本中
                error_result = json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)
                tool_call_text = tool_call_text_start + f'  <result>{error_result}</result>\n</tool_call>\n'
                tool_calls_text_parts.append(tool_call_text)

        await db.commit()

    # 输出任务完成状态
    if task_completed:
        print(f"Task completed successfully in update_message with task_complete tool")
    else:
        print(f"Task ended in update_message after {iteration} iterations (max_iterations={max_iterations})")

    # 将工具调用XML追加到消息内容中，刷新页面后仍能以artifact形式显示
    if tool_calls_text_parts:
        extra_content = "\n\n" + "".join(tool_calls_text_parts)
        await db.execute(
            text("UPDATE messages SET content = content || :extra WHERE id = :mid"),
            {"extra": extra_content, "mid": assistant_message.id}
        )
        await db.commit()

    return {
        "status": "ok",
        "message": "消息已更新，AI响应已重新生成"
    }

async def generate_streaming_response(session_id: str, project_id: str, db):
    agent = TeachingAgent(db, session_id)

    messages_result = await db.execute(text("SELECT * FROM messages WHERE session_id = :session_id AND is_active = 1 ORDER BY created_at"), {"session_id": session_id})
    messages = [dict(row._mapping) for row in messages_result.fetchall()]

    user_messages = [m for m in messages if m['role'] == 'user']
    last_user_message = user_messages[-1]['content'] if user_messages else ""
    last_user_message_id = user_messages[-1]['id'] if user_messages else None

    # 幂等保护：最后一条user消息若已有assistant回复（SSE重连/重复触发时），直接结束，
    # 避免同一输入生成多条AI消息
    if last_user_message_id:
        existing_reply = await db.execute(
            text("""SELECT id FROM messages WHERE session_id = :sid AND role = 'assistant'
                    AND parent_id = :pid AND is_active = 1"""),
            {"sid": session_id, "pid": last_user_message_id}
        )
        if existing_reply.first():
            print(f"[stream] message {last_user_message_id} already has assistant reply, skipping")
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

    yield f"data: {json.dumps({'type': 'thinking'})}\n\n"

    # 收集完整的响应文本和工具调用
    full_response = ''
    tool_calls_buffer = {}
    tool_call_ids = {}  # 存储 tool_call_id
    tool_results = {}  # 存储工具执行结果
    reasoning_content = ""  # 存储reasoning_content（OpenAI thinking模式要求）
    tool_calls_text_parts = []  # 存储工具调用的文本片段,用于插入到响应文本中

    print(f"Starting to process AI response...")
    
    # 流式处理AI响应
    async for chunk in agent.process_user_input(last_user_message):
        # print(f"Received chunk: {chunk}")
        
        if chunk['type'] == 'text':
            full_response += chunk['content']
            yield f"data: {json.dumps({'type': 'text', 'content': chunk['content']})}\n\n"
        elif chunk['type'] == 'reasoning':
            # 保存reasoning_content（必须传回给后续API调用）
            reasoning_content += chunk['content']
            print(f"Received reasoning content: {len(chunk['content'])} chars")
        elif chunk['type'] == 'tool_call':
            # 收集工具调用的参数
            tool_name = chunk['name']
            tool_id = chunk.get('id', '')  # 获取 tool_call_id
            print(f"Received tool call: {tool_name}, id: {tool_id}")
            if tool_name not in tool_calls_buffer:
                tool_calls_buffer[tool_name] = ''
                tool_call_ids[tool_name] = tool_id  # 保存 id
            tool_calls_buffer[tool_name] += chunk['arguments']

    print(f"Finished processing AI response. Tool calls: {tool_calls_buffer}")

    # 保存AI消息到数据库（工具调用XML会在所有工具执行完后统一追加到消息内容中，见generate_streaming_response末尾）

    assistant_message = Message(
        id=str(uuid4()),
        session_id=session_id,
        parent_id=last_user_message_id,
        role="assistant",
        content=full_response,
        is_active=True
    )
    db.add(assistant_message)

    # 处理工具调用
    for tool_name, arguments_str in tool_calls_buffer.items():
        try:
            arguments = json.loads(arguments_str)
            print(f"Processing tool call: {tool_name}, arguments: {arguments}")

            if tool_name == 'task_complete':
                # 收到task_complete工具调用,标记任务已完成
                task_completed = True
                print(f"Task completed: {arguments.get('summary', '')}")
                yield f"data: {json.dumps({'type': 'task_complete', 'summary': arguments.get('summary', '')})}\n\n"
                # 将工具调用信息格式化为文本
                result_json = json.dumps({"status": "success", "summary": arguments.get("summary", "")}, ensure_ascii=False)
                tool_call_text = f'<tool_call iteration="0" timestamp="{datetime.utcnow().isoformat()}">\n  <name>{tool_name}</name>\n  <arguments>{json.dumps(arguments, ensure_ascii=False)}</arguments>\n  <result>{result_json}</result>\n</tool_call>\n'
                tool_calls_text_parts.append(tool_call_text)
                continue

            # 记录工具调用信息(在执行前),用于后续插入到文本中
            tool_call_text_start = f'<tool_call iteration="0" timestamp="{datetime.utcnow().isoformat()}">\n  <name>{tool_name}</name>\n  <arguments>{json.dumps(arguments, ensure_ascii=False)}</arguments>\n'

            if tool_name == 'mark_concepts_mastered':
                concepts = arguments.get('concepts', [])

                # 获取当前session的所有概念列表
                all_concepts_result = await db.execute(
                    text("SELECT name, status FROM concepts WHERE session_id = :session_id"),
                    {"session_id": session_id}
                )
                all_concepts = {row[0]: row[1] for row in all_concepts_result.fetchall()}
                unmastered_concepts = [name for name, status in all_concepts.items() if status != 'mastered']

                for concept_data in concepts:
                    concept_name = concept_data.get('concept_name')
                    summary = concept_data.get('summary')

                    # 检查概念是否存在于当前session
                    if concept_name not in all_concepts:
                        # 概念不存在，返回错误信息和未掌握概念列表
                        error_msg = f"错误：概念【{concept_name}】不存在于当前教学session中。"
                        if unmastered_concepts:
                            error_msg += f"\n当前未掌握的概念列表：{', '.join(unmastered_concepts)}"
                        else:
                            error_msg += "\n当前没有未掌握的概念。"
                        print(f"Concept not found: {concept_name}")
                        tool_results['mark_concepts_mastered'] = json.dumps({
                            "status": "error",
                            "message": error_msg,
                            "unmastered_concepts": unmastered_concepts
                        }, ensure_ascii=False)
                        continue

                    # 检查是否已存在同名概念
                    existing_concept = await db.execute(
                        text("SELECT * FROM concepts WHERE session_id = :session_id AND name = :name"),
                        {"session_id": session_id, "name": concept_name}
                    )
                    existing = existing_concept.first()
                    print(f"Existing concept: {existing}")

                    if existing:
                        # 更新现有概念的状态为mastered
                        await db.execute(
                            text("UPDATE concepts SET status = 'mastered', description = :description WHERE id = :id"),
                            {"description": summary, "id": existing[0]}
                        )
                        concept_id = existing[0]
                        print(f"Updated concept status to mastered: {concept_name}")
                        yield f"data: {json.dumps({'type': 'concept', 'concept_name': concept_name, 'content': f'很好！已标记【{concept_name}】为已掌握概念。'})}\n\n"

                        # 更新关联节点的掌握度为 30%
                        node_result = await db.execute(
                            text("SELECT id FROM nodes WHERE concept_id = :cid"),
                            {"cid": concept_id}
                        )
                        node_row = node_result.first()
                        if node_row:
                            await db.execute(
                                text("UPDATE nodes SET mastery_score = 0.3 WHERE id = :nid"),
                                {"nid": node_row[0]}
                            )
                            print(f"Updated node mastery_score to 0.3 for concept: {concept_name}")

                # 将工具执行结果添加到文本中
                result_json = tool_results.get('mark_concepts_mastered', {"status": "success"})
                tool_call_text = tool_call_text_start + f'  <result>{json.dumps(result_json, ensure_ascii=False)}</result>\n</tool_call>\n'
                tool_calls_text_parts.append(tool_call_text)
                yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'arguments': arguments, 'result': result_json, 'iteration': 0})}\n\n"

            elif tool_name == 'mark_misconception':
                concept_name = arguments.get('concept_name')
                misconception = arguments.get('misconception')
                correction = arguments.get('correction')

                new_misconception = Misconception(
                    id=str(uuid4()),
                    session_id=session_id,
                    concept_name=concept_name,
                    user_claim=last_user_message,
                    ai_correction=correction,
                    resolved=False
                )
                db.add(new_misconception)
                print(f"Added new misconception: {concept_name}")
                yield f"data: {json.dumps({'type': 'misconception', 'concept_name': concept_name, 'content': f'注意：【{concept_name}】存在误解，我来帮你纠正。'})}\n\n"
                # 将工具执行结果添加到文本中
                result_json = json.dumps({"status": "success", "concept_name": concept_name}, ensure_ascii=False)
                tool_call_text = tool_call_text_start + f'  <result>{result_json}</result>\n</tool_call>\n'
                tool_calls_text_parts.append(tool_call_text)
                yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'arguments': arguments, 'result': json.loads(result_json), 'iteration': 0})}\n\n"

            # ====== Integration Level 工具 ======
            elif tool_name == 'create_graph_node':
                label = arguments.get('label')
                description = arguments.get('description', '')
                mastery_score = arguments.get('mastery_score', 0)

                # 获取正确的图谱ID：优先使用 source_note -> directory -> graph 的路径
                session_info = await db.execute(
                    text("SELECT project_id, source_note_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for create_graph_node")
                    continue
                project_id = session_row[0]
                source_note_id = session_row[1]

                # 优先使用 source_note -> directory -> graph 的路径
                graph_id = None
                if source_note_id:
                    # 通过 source_note 找到目录，再找到图谱
                    note_result = await db.execute(
                        text("SELECT directory_id FROM notes WHERE id = :note_id"),
                        {"note_id": source_note_id}
                    )
                    note_row = note_result.first()
                    if note_row and note_row[0]:
                        graph_result = await db.execute(
                            text("SELECT id FROM graphs WHERE directory_id = :directory_id"),
                            {"directory_id": note_row[0]}
                        )
                        graph_row = graph_result.first()
                        if graph_row:
                            graph_id = graph_row[0]
                            print(f"Found graph_id from source_note: {graph_id}")

                # 如果没有找到，使用项目的第一个图谱
                if not graph_id:
                    graph_result = await db.execute(
                        text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                        {"pid": project_id}
                    )
                    graph_row = graph_result.first()
                    if not graph_row:
                        # 创建默认图谱
                        graph_id = str(uuid4())
                        await db.execute(
                            text("INSERT INTO graphs (id, project_id, name, created_at, updated_at) VALUES (:id, :pid, '知识图谱', datetime('now'), datetime('now'))"),
                            {"id": graph_id, "pid": project_id}
                        )
                        print(f"Created default graph for project: {graph_id}")
                    else:
                        graph_id = graph_row[0]
                        print(f"Found graph_id from project: {graph_id}")

                # 创建节点
                node_id = str(uuid4())
                await db.execute(
                    text("INSERT INTO nodes (id, graph_id, label, mastery_score) VALUES (:id, :gid, :label, :ms)"),
                    {"id": node_id, "gid": graph_id, "label": label, "ms": mastery_score}
                )
                print(f"Created graph node: {label} with id {node_id} in graph {graph_id}")
                result_json = {"status": "success", "label": label, "node_id": node_id, "graph_id": graph_id}
                tool_call_text = tool_call_text_start + f'  <result>{json.dumps(result_json, ensure_ascii=False)}</result>\n</tool_call>\n'
                tool_calls_text_parts.append(tool_call_text)
                yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'arguments': arguments, 'result': result_json, 'iteration': 0})}\n\n"

            elif tool_name == 'create_graph_edge':
                source_label = arguments.get('source_label')
                target_label = arguments.get('target_label')
                relation = arguments.get('relation', 'related')
                edge_label = arguments.get('label', '')

                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for create_graph_edge")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for create_graph_edge")
                    continue
                graph_id = graph_row[0]

                # 查找源节点和目标节点
                source_node = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": source_label}
                )
                source_row = source_node.first()
                target_node = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": target_label}
                )
                target_row = target_node.first()

                if source_row and target_row:
                    edge_id = str(uuid4())
                    await db.execute(
                        text("INSERT INTO edges (id, graph_id, source_node_id, target_node_id, relation, label, weight) VALUES (:id, :gid, :src, :tgt, :rel, :lbl, 1.0)"),
                        {"id": edge_id, "gid": graph_id, "src": source_row[0], "tgt": target_row[0], "rel": relation, "lbl": edge_label}
                    )
                    print(f"Created graph edge: {source_label} -> {target_label} ({relation})")
                    result_json = {"status": "success", "source": source_label, "target": target_label, "relation": relation}
                    tool_call_text = tool_call_text_start + f'  <result>{json.dumps(result_json, ensure_ascii=False)}</result>\n</tool_call>\n'
                    tool_calls_text_parts.append(tool_call_text)
                    yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'arguments': arguments, 'result': result_json, 'iteration': 0})}\n\n"
                else:
                    print(f"Nodes not found for edge: {source_label} or {target_label}")

            elif tool_name == 'update_graph_node':
                label = arguments.get('label')
                new_description = arguments.get('description')
                new_mastery = arguments.get('mastery_score')

                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for update_graph_node")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for update_graph_node")
                    continue
                graph_id = graph_row[0]

                # 查找节点
                node_result = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": label}
                )
                node_row = node_result.first()
                if node_row:
                    updates = []
                    params = {"nid": node_row[0]}
                    if new_description is not None:
                        updates.append("description = :desc")
                        params["desc"] = new_description
                    if new_mastery is not None:
                        updates.append("mastery_score = :ms")
                        params["ms"] = new_mastery
                    if updates:
                        sql = f"UPDATE nodes SET {', '.join(updates)} WHERE id = :nid"
                        await db.execute(text(sql), params)
                        print(f"Updated graph node: {label}")
                        result_json = {"status": "success", "label": label}
                        tool_call_text = tool_call_text_start + f'  <result>{json.dumps(result_json, ensure_ascii=False)}</result>\n</tool_call>\n'
                        tool_calls_text_parts.append(tool_call_text)
                        yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'arguments': arguments, 'result': result_json, 'iteration': 0})}\n\n"
                else:
                    print(f"Node not found for update: {label}")

            elif tool_name == 'delete_graph_node':
                label = arguments.get('label')

                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for delete_graph_node")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for delete_graph_node")
                    continue
                graph_id = graph_row[0]

                # 查找节点
                node_result = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": label}
                )
                node_row = node_result.first()
                if node_row:
                    node_id = node_row[0]
                    # 删除关联的边
                    await db.execute(
                        text("DELETE FROM edges WHERE source_node_id = :nid OR target_node_id = :nid"),
                        {"nid": node_id}
                    )
                    # 删除节点
                    await db.execute(
                        text("DELETE FROM nodes WHERE id = :nid"),
                        {"nid": node_id}
                    )
                    print(f"Deleted graph node: {label}")
                    result_json = {"status": "success", "label": label}
                    tool_call_text = tool_call_text_start + f'  <result>{json.dumps(result_json, ensure_ascii=False)}</result>\n</tool_call>\n'
                    tool_calls_text_parts.append(tool_call_text)
                    yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'arguments': arguments, 'result': result_json, 'iteration': 0})}\n\n"
                else:
                    print(f"Node not found for delete: {label}")

            elif tool_name == 'delete_graph_edge':
                source_label = arguments.get('source_label')
                target_label = arguments.get('target_label')

                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for delete_graph_edge")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for delete_graph_edge")
                    continue
                graph_id = graph_row[0]

                # 查找源节点和目标节点
                source_node = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": source_label}
                )
                source_row = source_node.first()
                target_node = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": target_label}
                )
                target_row = target_node.first()

                if source_row and target_row:
                    await db.execute(
                        text("DELETE FROM edges WHERE graph_id = :gid AND source_node_id = :src AND target_node_id = :tgt"),
                        {"gid": graph_id, "src": source_row[0], "tgt": target_row[0]}
                    )
                    print(f"Deleted graph edge: {source_label} -> {target_label}")
                    result_json = {"status": "success", "source": source_label, "target": target_label}
                    tool_call_text = tool_call_text_start + f'  <result>{json.dumps(result_json, ensure_ascii=False)}</result>\n</tool_call>\n'
                    tool_calls_text_parts.append(tool_call_text)
                    yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'arguments': arguments, 'result': result_json, 'iteration': 0})}\n\n"
                else:
                    print(f"Nodes not found for edge delete: {source_label} or {target_label}")

            elif tool_name == 'get_graph_nodes':
                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for get_graph_nodes")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for get_graph_nodes")
                    continue
                graph_id = graph_row[0]

                # 获取所有节点
                nodes_result = await db.execute(
                    text("SELECT label, description, mastery_score FROM nodes WHERE graph_id = :gid ORDER BY label"),
                    {"gid": graph_id}
                )
                nodes = nodes_result.fetchall()
                node_list = [{"label": n[0], "description": n[1] or "", "mastery_score": n[2]} for n in nodes]
                print(f"Retrieved {len(node_list)} nodes from graph")
                tool_results['get_graph_nodes'] = json.dumps(node_list, ensure_ascii=False)
                result_json = {"nodes": node_list}
                tool_call_text = tool_call_text_start + f'  <result>{json.dumps(result_json, ensure_ascii=False)}</result>\n</tool_call>\n'
                tool_calls_text_parts.append(tool_call_text)
                yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'arguments': arguments, 'result': result_json, 'iteration': 0})}\n\n"

            elif tool_name == 'get_graph_node':
                label = arguments.get('label')

                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for get_graph_node")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for get_graph_node")
                    continue
                graph_id = graph_row[0]

                # 查找节点
                node_result = await db.execute(
                    text("SELECT label, description, mastery_score FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": label}
                )
                node_row = node_result.first()
                if node_row:
                    node_info = {"label": node_row[0], "description": node_row[1] or "", "mastery_score": node_row[2]}
                    print(f"Retrieved node: {label}")
                    tool_results['get_graph_node'] = json.dumps(node_info, ensure_ascii=False)
                    result_json = {"node": node_info}
                    tool_call_text = tool_call_text_start + f'  <result>{json.dumps(result_json, ensure_ascii=False)}</result>\n</tool_call>\n'
                    tool_calls_text_parts.append(tool_call_text)
                    yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'arguments': arguments, 'result': result_json, 'iteration': 0})}\n\n"
                else:
                    print(f"Node not found: {label}")
                    tool_results['get_graph_node'] = json.dumps({"error": "Node not found"}, ensure_ascii=False)

            elif tool_name == 'get_graph_edges':
                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for get_graph_edges")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for get_graph_edges")
                    continue
                graph_id = graph_row[0]

                # 获取所有边
                edges_result = await db.execute(
                    text("""SELECT sn.label as source_label, tn.label as target_label, e.relation, e.label
                           FROM edges e
                           JOIN nodes sn ON e.source_node_id = sn.id
                           JOIN nodes tn ON e.target_node_id = tn.id
                           WHERE e.graph_id = :gid ORDER BY e.relation"""),
                    {"gid": graph_id}
                )
                edges = edges_result.fetchall()
                edge_list = [{"source": e[0], "target": e[1], "relation": e[2], "label": e[3] or ""} for e in edges]
                print(f"Retrieved {len(edge_list)} edges from graph")
                tool_results['get_graph_edges'] = json.dumps(edge_list, ensure_ascii=False)
                result_json = {"edges": edge_list}
                tool_call_text = tool_call_text_start + f'  <result>{json.dumps(result_json, ensure_ascii=False)}</result>\n</tool_call>\n'
                tool_calls_text_parts.append(tool_call_text)
                yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'arguments': arguments, 'result': result_json, 'iteration': 0})}\n\n"

            elif tool_name == 'get_node_edges':
                label = arguments.get('label')

                # 获取 session 的 project_id
                session_info = await db.execute(
                    text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
                    {"sid": session_id}
                )
                session_row = session_info.first()
                if not session_row:
                    print(f"Session not found for get_node_edges")
                    continue
                project_id = session_row[0]

                # 获取图谱
                graph_result = await db.execute(
                    text("SELECT id FROM graphs WHERE project_id = :pid ORDER BY created_at LIMIT 1"),
                    {"pid": project_id}
                )
                graph_row = graph_result.first()
                if not graph_row:
                    print(f"No graph found for get_node_edges")
                    continue
                graph_id = graph_row[0]

                # 查找节点
                node_result = await db.execute(
                    text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
                    {"gid": graph_id, "label": label}
                )
                node_row = node_result.first()
                if node_row:
                    node_id = node_row[0]
                    # 获取节点相关的边
                    edges_result = await db.execute(
                        text("""SELECT sn.label as source_label, tn.label as target_label, e.relation, e.label
                               FROM edges e
                               JOIN nodes sn ON e.source_node_id = sn.id
                               JOIN nodes tn ON e.target_node_id = tn.id
                               WHERE e.graph_id = :gid AND (e.source_node_id = :nid OR e.target_node_id = :nid)"""),
                        {"gid": graph_id, "nid": node_id}
                    )
                    edges = edges_result.fetchall()
                    edge_list = [{"source": e[0], "target": e[1], "relation": e[2], "label": e[3] or ""} for e in edges]
                    print(f"Retrieved {len(edge_list)} edges for node: {label}")
                    tool_results['get_node_edges'] = json.dumps({"label": label, "edges": edge_list}, ensure_ascii=False)
                    result_json = {"label": label, "edges": edge_list}
                    tool_call_text = tool_call_text_start + f'  <result>{json.dumps(result_json, ensure_ascii=False)}</result>\n</tool_call>\n'
                    tool_calls_text_parts.append(tool_call_text)
                    yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'arguments': arguments, 'result': result_json, 'iteration': 0})}\n\n"
                else:
                    print(f"Node not found: {label}")
                    tool_results['get_node_edges'] = json.dumps({"error": "Node not found"}, ensure_ascii=False)

            # ====== 虚拟图工具（必须真正执行，否则AI会误以为参数没传对） ======
            elif tool_name in VIRTUAL_GRAPH_TOOLS:
                result_json = await _execute_virtual_graph_tool(db, session_id, tool_name, arguments)
                print(f"Executed virtual graph tool: {tool_name}, result: {result_json}")
                tool_results[tool_name] = result_json
                try:
                    result_data = json.loads(result_json)
                except Exception:
                    result_data = {"status": "error"}
                tool_call_text = tool_call_text_start + f'  <result>{result_json}</result>\n</tool_call>\n'
                tool_calls_text_parts.append(tool_call_text)
                yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'arguments': arguments, 'result': result_data, 'iteration': 0})}\n\n"

        except Exception as e:
            print(f"Error processing tool call: {e}")
            # 将错误信息添加到工具调用文本中
            error_result = json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)
            tool_call_text = tool_call_text_start + f'  <result>{error_result}</result>\n</tool_call>\n'
            tool_calls_text_parts.append(tool_call_text)

    # 一次性提交所有数据库操作
    await db.commit()
    print(f"Database committed")
    
    # 处理工具调用的循环：AI可能需要多轮工具调用
    # max_iterations设置为一个较大的值,主要依赖task_complete工具来结束循环
    max_iterations = 50  # 设置为50次,防止真正的无限循环
    iteration = 0
    task_completed = False  # 跟踪是否收到task_complete工具调用

    while (tool_results or tool_calls_buffer) and iteration < max_iterations and not task_completed:
        iteration += 1
        print(f"Tool call iteration {iteration}")
        
        # 构建工具消息：包含所有工具的执行结果
        tool_messages = []
        
        # 添加读取工具的结果
        for tool_name, result in tool_results.items():
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_ids.get(tool_name, f"call_{tool_name}"),
                "name": tool_name,
                "content": result
            })
        
        # 对于非读取工具（已在第一轮执行），添加成功结果
        read_tools = ['get_graph_nodes', 'get_graph_node', 'get_graph_edges', 'get_node_edges']
        for tool_name in tool_calls_buffer.keys():
            if tool_name not in tool_results and tool_name not in read_tools:
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_ids.get(tool_name, f"call_{tool_name}"),
                    "name": tool_name,
                    "content": json.dumps({"status": "success"}, ensure_ascii=False)
                })
        
        if not tool_messages:
            break

        print(f"Sending tool results to AI: {len(tool_messages)} messages")

        # 写入工具调用结果到日志
        with open("ai_response.log", "a", encoding="utf-8") as log_file:
            log_file.write("\n【工具调用结果】\n")
            for msg in tool_messages:
                log_file.write(f"工具: {msg['name']}\n")
                log_file.write(f"结果: {msg['content']}\n")

        # 再次调用AI生成响应
        yield f"data: {json.dumps({'type': 'thinking'})}\n\n"
        
        # 重置变量
        old_tool_calls_buffer = tool_calls_buffer
        old_tool_call_ids = tool_call_ids
        tool_calls_buffer = {}
        tool_call_ids = {}
        tool_results = {}
        continuation_response = ''
        
        # 重要：将之前的reasoning_content传递给process_tool_results
        async for chunk in agent.process_tool_results(tool_messages, reasoning_content):
            if chunk['type'] == 'text':
                continuation_response += chunk['content']
                yield f"data: {json.dumps({'type': 'text', 'content': chunk['content']})}\n\n"
            elif chunk['type'] == 'reasoning':
                # 更新reasoning_content（如果有新的）
                reasoning_content += chunk['content']
                print(f"Received new reasoning content in continuation: {len(chunk['content'])} chars")
            elif chunk['type'] == 'tool_call':
                tool_name = chunk['name']
                tool_id = chunk.get('id', '')
                if tool_name not in tool_calls_buffer:
                    tool_calls_buffer[tool_name] = ''
                    tool_call_ids[tool_name] = tool_id
                tool_calls_buffer[tool_name] += chunk['arguments']
                print(f"Received tool call in continuation: {tool_name}, id: {tool_id}")
        
        # 更新AI消息内容
        if continuation_response:
            await db.execute(
                text("UPDATE messages SET content = content || :extra WHERE id = :mid"),
                {"extra": continuation_response, "mid": assistant_message.id}
            )
            await db.commit()
        
        # 处理新一轮的工具调用(简化版本)
        # 注意：这里只处理图谱工具,其他工具已在第一轮处理
        for tool_name, arguments_str in tool_calls_buffer.items():
            try:
                arguments = json.loads(arguments_str)
                print(f"Processing continuation tool call: {tool_name}, arguments: {arguments}")

                # 记录工具调用信息(在执行前)
                tool_call_text_start = f'<tool_call iteration="{iteration}" timestamp="{datetime.utcnow().isoformat()}">\n  <name>{tool_name}</name>\n  <arguments>{json.dumps(arguments, ensure_ascii=False)}</arguments>\n'

                if tool_name == 'task_complete':
                    # 收到task_complete工具调用,标记任务已完成
                    task_completed = True
                    print(f"Task completed in continuation: {arguments.get('summary', '')}")
                    yield f"data: {json.dumps({'type': 'task_complete', 'summary': arguments.get('summary', '')})}\n\n"
                    # 将工具调用信息格式化为文本
                    result_json = json.dumps({"status": "success", "summary": arguments.get("summary", "")}, ensure_ascii=False)
                    tool_call_text = tool_call_text_start + f'  <result>{result_json}</result>\n</tool_call>\n'
                    tool_calls_text_parts.append(tool_call_text)
                    continue

                # 虚拟图工具：必须真正执行并返回真实结果，否则AI会误以为参数没传对
                if tool_name in VIRTUAL_GRAPH_TOOLS:
                    tool_results[tool_name] = await _execute_virtual_graph_tool(db, session_id, tool_name, arguments)
                    result_text = tool_results[tool_name]
                    print(f"Executed virtual graph tool in continuation: {tool_name}, result: {result_text}")
                # 只处理图谱相关工具,返回结果让AI知道操作状态
                elif tool_name in read_tools:
                    # 读取工具：需要执行并返回数据
                    tool_results[tool_name] = json.dumps({"result": "需要重新获取"}, ensure_ascii=False)
                    result_text = tool_results[tool_name]
                else:
                    # 写入工具：执行操作后返回成功
                    tool_results[tool_name] = json.dumps({"status": "success"}, ensure_ascii=False)
                    result_text = '{"status": "success"}'

                # 将工具调用信息格式化为文本
                tool_call_text = tool_call_text_start + f'  <result>{result_text}</result>\n</tool_call>\n'
                tool_calls_text_parts.append(tool_call_text)
                try:
                    result_data = json.loads(result_text)
                except Exception:
                    result_data = result_text
                yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'arguments': arguments, 'result': result_data, 'iteration': iteration})}\n\n"

            except Exception as e:
                print(f"Error processing continuation tool call: {e}")
                # 将错误信息添加到工具调用文本中
                error_result = json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)
                tool_call_text = tool_call_text_start + f'  <result>{error_result}</result>\n</tool_call>\n'
                tool_calls_text_parts.append(tool_call_text)

        await db.commit()

    # 输出任务完成状态
    if task_completed:
        print(f"Task completed successfully with task_complete tool")
    else:
        print(f"Task ended after {iteration} iterations (max_iterations={max_iterations})")

    # 将工具调用XML追加到消息内容中，刷新页面后仍能以artifact形式显示
    if tool_calls_text_parts:
        extra_content = "\n\n" + "".join(tool_calls_text_parts)
        await db.execute(
            text("UPDATE messages SET content = content || :extra WHERE id = :mid"),
            {"extra": extra_content, "mid": assistant_message.id}
        )
        await db.commit()

    yield f"data: {json.dumps({'type': 'done'})}\n\n"

@router.get("/stream/{session_id}")
async def stream_teaching(session_id: str, project_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    async def stream_generator():
        async for chunk in generate_streaming_response(session_id, project_id, db):
            yield chunk
    
    return StreamingResponse(stream_generator(), media_type="text/event-stream")

@router.get("/sessions/{session_id}/progress")
async def get_session_progress(session_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    concepts_result = await db.execute(text("SELECT * FROM concepts WHERE session_id = :session_id"), {"session_id": session_id})
    concepts = [dict(row._mapping) for row in concepts_result.fetchall()]

    misconceptions_result = await db.execute(text("SELECT * FROM misconceptions WHERE session_id = :session_id"), {"session_id": session_id})
    misconceptions = [dict(row._mapping) for row in misconceptions_result.fetchall()]

    mastered_concepts = [c for c in concepts if c.get("status") == "mastered"]
    promoted_concepts = [c for c in concepts if c.get("status") == "promoted"]
    total_concepts = len(concepts) + len(misconceptions)
    completed_concepts = len(mastered_concepts) + len(promoted_concepts)  # promoted也算已完成
    progress_percent = int((completed_concepts / max(total_concepts, 1)) * 100)

    # 如果所有概念都已掌握，自动更新session状态为completed
    if total_concepts > 0 and completed_concepts >= total_concepts:
        await db.execute(
            text("UPDATE teaching_sessions SET status = 'completed' WHERE id = :session_id AND status != 'completed'"),
            {"session_id": session_id}
        )
        await db.commit()

    return {"completed": completed_concepts, "total": max(total_concepts, 1), "percent": progress_percent}

@router.post("/sessions/{session_id}/promote")
async def promote_concepts(session_id: str, request: Request, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    body = await request.json()
    concept_ids = body.get('concept_ids', [])

    # 获取session信息
    session_result = await db.execute(
        text("SELECT * FROM teaching_sessions WHERE id = :session_id"),
        {"session_id": session_id}
    )
    session_row = session_result.fetchone()
    if not session_row:
        raise HTTPException(status_code=404, detail="Session not found")

    session = dict(session_row._mapping)
    project_id = session["project_id"]

    # 获取正确的图谱ID：优先使用 source_note -> directory -> graph 的路径
    graph_id = None
    directory_id = None
    directory_name = None
    if session.get("source_note_id"):
        # 通过 source_note 找到目录，再找到图谱
        note_result = await db.execute(
            text("SELECT directory_id FROM notes WHERE id = :note_id"),
            {"note_id": session["source_note_id"]}
        )
        note_row = note_result.first()
        if note_row and note_row[0]:
            directory_id = note_row[0]
            dir_result = await db.execute(
                text("SELECT name FROM directories WHERE id = :directory_id"),
                {"directory_id": directory_id}
            )
            dir_row = dir_result.first()
            directory_name = dir_row[0] if dir_row else None
            graph_result = await db.execute(
                text("SELECT id FROM graphs WHERE directory_id = :directory_id"),
                {"directory_id": directory_id}
            )
            graph_row = graph_result.first()
            if graph_row:
                graph_id = graph_row[0]

    # fallback：笔记有目录但目录还没有图谱 → 创建与目录同名的图谱
    if not graph_id and directory_id:
        new_graph_id = str(uuid4())
        await db.execute(
            text("""INSERT INTO graphs (id, project_id, directory_id, name, created_at, updated_at)
                   VALUES (:id, :pid, :did, :name, datetime('now'), datetime('now'))"""),
            {"id": new_graph_id, "pid": project_id, "did": directory_id,
             "name": directory_name or "知识图谱"}
        )
        graph_id = new_graph_id

    # 无目录上下文：如果没有找到，使用项目的第一个图谱
    if not graph_id:
        graph_result = await db.execute(
            text("SELECT id FROM graphs WHERE project_id = :project_id ORDER BY created_at LIMIT 1"),
            {"project_id": project_id}
        )
        graph_row = graph_result.first()
        if graph_row:
            graph_id = graph_row[0]
    
    # 如果仍然没有图谱，创建一个新的
    if not graph_id:
        new_graph_id = str(uuid4())
        await db.execute(
            text("INSERT INTO graphs (id, project_id, created_at, updated_at) VALUES (:id, :project_id, datetime('now'), datetime('now'))"),
            {"id": new_graph_id, "project_id": project_id}
        )
        graph_id = new_graph_id

    promoted_concepts = []
    print(f"promote_concepts: graph_id={graph_id}, concept_ids={concept_ids}")

    for concept_id in concept_ids:
        # 获取concept
        result = await db.execute(
            text("SELECT * FROM concepts WHERE id = :concept_id AND session_id = :session_id"),
            {"concept_id": concept_id, "session_id": session_id}
        )
        concept = result.fetchone()

        if concept:
            concept_name = concept[2]  # name字段在第2列（索引2）
            description = concept[3] if len(concept) > 3 else ""  # description字段在第3列
            status = concept[5]  # status字段在第5列
            print(f"Found concept: name={concept_name}, status={status}")

            if status == 'mastered':
                # 挂载式合并：同名节点复用（mastery取较大值、补concept_id），新节点自动挂载到图谱网络
                node_id, created = await merge_or_create_node(
                    db, graph_id, concept_name, concept_id=concept_id, mastery=0.3
                )
                if created:
                    await mount_node(db, graph_id, node_id, concept_name)
                    print(f"Created node: id={node_id}, label={concept_name}, graph_id={graph_id}")
                else:
                    print(f"Merged into existing node: id={node_id}, label={concept_name}")

                # 更新concept状态为promoted
                await db.execute(
                    text("UPDATE concepts SET status = 'promoted' WHERE id = :concept_id"),
                    {"concept_id": concept_id}
                )

                promoted_concepts.append({"name": concept_name, "node_id": node_id})

    # 同步虚拟图到真实图谱：补全虚拟图所有节点 + 投影内部边（形成完整结构网络）
    projected_edges = []
    synced_nodes = []
    if promoted_concepts:
        vg_result = await db.execute(
            text("SELECT id FROM virtual_graphs WHERE session_id = :sid"),
            {"sid": session_id}
        )
        for vg_row in vg_result.fetchall():
            result = await sync_virtual_graph_to_real(db, graph_id, vg_row[0])
            synced_nodes.extend(result["nodes"])
            projected_edges.extend(result["edges"])
        print(f"promote_concepts: synced {len(synced_nodes)} nodes, projected {len(projected_edges)} edges from virtual graphs")

    # 更新graph的updated_at
    await db.execute(
        text("UPDATE graphs SET updated_at = datetime('now') WHERE id = :graph_id"),
        {"graph_id": graph_id}
    )
    await db.commit()

    return {
        "promoted_count": len(promoted_concepts),
        "concepts": promoted_concepts,
        "graph_id": graph_id,
        "projected_edges": projected_edges,
        "status": "ok"
    }

@router.post("/sessions/promote-by-ids")
async def promote_by_ids(request: Request, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    """从图谱页面调用：根据concept_ids沉淀概念到图谱"""
    body = await request.json()
    project_id = body.get("project_id")
    concept_ids = body.get("concept_ids", [])

    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")

    # 查找或创建Graph
    graph_result = await db.execute(
        text("SELECT id FROM graphs WHERE project_id = :project_id"),
        {"project_id": project_id}
    )
    graph = graph_result.first()

    if not graph:
        new_graph_id = str(uuid4())
        await db.execute(
            text("INSERT INTO graphs (id, project_id, created_at, updated_at) VALUES (:id, :pid, datetime('now'), datetime('now'))"),
            {"id": new_graph_id, "pid": project_id}
        )
        graph_id = new_graph_id
    else:
        graph_id = graph[0]

    promoted = []
    session_ids = set()

    for cid in concept_ids:
        result = await db.execute(
            text("SELECT * FROM concepts WHERE id = :cid AND status = 'mastered'"),
            {"cid": cid}
        )
        concept = result.fetchone()
        if not concept:
            continue

        name = concept[2]  # name字段在第2列（索引2）
        description = concept[3] if len(concept) > 3 else ""  # description字段在第3列
        session_ids.add(concept[1])  # session_id字段在第1列

        # 挂载式合并：同名节点复用，新节点自动挂载到图谱网络
        node_id, created = await merge_or_create_node(
            db, graph_id, name, concept_id=cid, mastery=0.3
        )
        if created:
            await mount_node(db, graph_id, node_id, name)
        else:
            continue

        await db.execute(text("UPDATE concepts SET status = 'promoted' WHERE id = :cid"), {"cid": cid})
        promoted.append({"name": name, "node_id": node_id})

    # 同步虚拟图到真实图谱：补全虚拟图所有节点 + 投影内部边
    projected_edges = []
    synced_nodes = []
    if promoted:
        for sid in session_ids:
            vg_result = await db.execute(
                text("SELECT id FROM virtual_graphs WHERE session_id = :sid"),
                {"sid": sid}
            )
            for vg_row in vg_result.fetchall():
                result = await sync_virtual_graph_to_real(db, graph_id, vg_row[0])
                synced_nodes.extend(result["nodes"])
                projected_edges.extend(result["edges"])

    await db.execute(text("UPDATE graphs SET updated_at = datetime('now') WHERE id = :gid"), {"gid": graph_id})
    await db.commit()

    return {"status": "ok", "promoted_count": len(promoted), "concepts": promoted,
            "synced_nodes": synced_nodes, "projected_edges": projected_edges}

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    await db.execute(text("DELETE FROM misconceptions WHERE session_id = :session_id"), {"session_id": session_id})
    await db.execute(text("DELETE FROM concepts WHERE session_id = :session_id"), {"session_id": session_id})
    await db.execute(text("DELETE FROM messages WHERE session_id = :session_id"), {"session_id": session_id})
    await db.execute(text("DELETE FROM teaching_sessions WHERE id = :session_id"), {"session_id": session_id})
    await db.commit