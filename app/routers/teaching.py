import asyncio
import json
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import text
from starlette.requests import Request

from app.core.database import AsyncSessionLocal
from app.core.deps import (
    get_current_active_user,
    get_db,
    require_project,
    require_session,
)
from app.i18n.i18n import t
from app.models.teaching import Message, Misconception, TeachingSession
from app.models.user import User
from app.schemas.teaching import (
    MessageCreate,
    MessageResponse,
    TeachingSessionCreate,
    TeachingSessionResponse,
)
from app.services import teaching_streams
from app.services.graph_mount import (
    merge_or_create_node,
    mount_node,
    sync_virtual_graph_to_real,
)
from app.services.teaching_agent import TeachingAgent

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

        await _insert_virtual_graph_nodes_and_edges(db, vg_id, nodes, edges)

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

# ====== 统一工具执行（流式/PUT路由共用，避免重复代码） ======

async def _get_project_id(db, session_id: str):
    result = await db.execute(
        text("SELECT project_id FROM teaching_sessions WHERE id = :sid"),
        {"sid": session_id}
    )
    row = result.first()
    return row[0] if row else None

def _tool_call_xml(iteration: int, tool_name: str, arguments: dict, result_json: str) -> str:
    """格式化工具调用记录，追加到消息内容中，刷新页面后仍能以artifact形式显示"""
    return (f'<tool_call iteration="{iteration}" timestamp="{datetime.utcnow().isoformat()}">\n'
            f'  <name>{tool_name}</name>\n'
            f'  <arguments>{json.dumps(arguments, ensure_ascii=False)}</arguments>\n'
            f'  <result>{result_json}</result>\n</tool_call>\n')

async def _execute_tool(db, session_id: str, tool_name: str, arguments: dict, user_claim: str = "") -> tuple:
    """执行单个教学工具（图谱/概念/虚拟图），返回 (结果JSON字符串, SSE事件列表)"""
    events = []

    if tool_name == 'mark_concepts_mastered':
        concepts = arguments.get('concepts', [])
        all_concepts_result = await db.execute(
            text("SELECT name, status FROM concepts WHERE session_id = :sid"),
            {"sid": session_id}
        )
        all_concepts = {row[0]: row[1] for row in all_concepts_result.fetchall()}
        unmastered_concepts = [name for name, status in all_concepts.items() if status != 'mastered']

        error_msg = None
        for concept_data in concepts:
            concept_name = concept_data.get('concept_name')
            summary = concept_data.get('summary')

            if concept_name not in all_concepts:
                error_msg = f"错误：概念【{concept_name}】不存在于当前教学session中。"
                if unmastered_concepts:
                    error_msg += f"\n当前未掌握的概念列表：{', '.join(unmastered_concepts)}"
                else:
                    error_msg += "\n当前没有未掌握的概念。"
                continue

            existing = (await db.execute(
                text("SELECT id FROM concepts WHERE session_id = :sid AND name = :name"),
                {"sid": session_id, "name": concept_name}
            )).first()
            if existing:
                await db.execute(
                    text("UPDATE concepts SET status = 'mastered', description = :description WHERE id = :id"),
                    {"description": summary, "id": existing[0]}
                )
                # 更新关联节点的掌握度为 30%
                node_row = (await db.execute(
                    text("SELECT id FROM nodes WHERE concept_id = :cid"),
                    {"cid": existing[0]}
                )).first()
                if node_row:
                    await db.execute(
                        text("UPDATE nodes SET mastery_score = 0.3 WHERE id = :nid"),
                        {"nid": node_row[0]}
                    )
                events.append({
                    "type": "concept",
                    "concept_name": concept_name,
                    "content": f'很好！已标记【{concept_name}】为已掌握概念。'
                })

        if error_msg:
            result_json = json.dumps({
                "status": "error",
                "message": error_msg,
                "unmastered_concepts": unmastered_concepts
            }, ensure_ascii=False)
        else:
            result_json = json.dumps({"status": "success"}, ensure_ascii=False)
        return result_json, events

    if tool_name == 'mark_misconception':
        concept_name = arguments.get('concept_name')
        correction = arguments.get('correction')
        db.add(Misconception(
            id=str(uuid4()),
            session_id=session_id,
            concept_name=concept_name,
            user_claim=user_claim,
            ai_correction=correction,
            resolved=False
        ))
        events.append({
            "type": "misconception",
            "concept_name": concept_name,
            "content": f'注意：【{concept_name}】存在误解，我来帮你纠正。'
        })
        return json.dumps({"status": "success", "concept_name": concept_name}, ensure_ascii=False), events

    if tool_name == 'create_graph_node':
        label = arguments.get('label')
        description = arguments.get('description', '')
        mastery_score = float(arguments.get('mastery_score', 0))

        graph_id = await _get_project_graph_id(db, session_id)
        if not graph_id:
            project_id = await _get_project_id(db, session_id)
            if not project_id:
                return json.dumps({"status": "error", "message": "Session not found"}, ensure_ascii=False), events
            graph_id = str(uuid4())
            await db.execute(
                text("INSERT INTO graphs (id, project_id, name, created_at, updated_at) VALUES (:id, :pid, '知识图谱', datetime('now'), datetime('now'))"),
                {"id": graph_id, "pid": project_id}
            )

        node_id = str(uuid4())
        await db.execute(
            text("INSERT INTO nodes (id, graph_id, label, description, mastery_score) VALUES (:id, :gid, :label, :desc, :ms)"),
            {"id": node_id, "gid": graph_id, "label": label, "desc": description, "ms": mastery_score}
        )
        return json.dumps({"status": "success", "label": label, "node_id": node_id, "graph_id": graph_id}, ensure_ascii=False), events

    if tool_name == 'create_graph_edge':
        source_label = arguments.get('source_label')
        target_label = arguments.get('target_label')
        relation = arguments.get('relation', 'related')
        edge_label = arguments.get('label', '')

        graph_id = await _get_project_graph_id(db, session_id)
        if not graph_id:
            return json.dumps({"status": "error", "message": "No graph found"}, ensure_ascii=False), events
        source_row = (await db.execute(
            text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
            {"gid": graph_id, "label": source_label}
        )).first()
        target_row = (await db.execute(
            text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
            {"gid": graph_id, "label": target_label}
        )).first()
        if not source_row or not target_row:
            return json.dumps({"status": "error", "message": f"Nodes not found: {source_label} or {target_label}"}, ensure_ascii=False), events

        edge_id = str(uuid4())
        await db.execute(
            text("INSERT INTO edges (id, graph_id, source_node_id, target_node_id, relation, label, weight) VALUES (:id, :gid, :src, :tgt, :rel, :lbl, 1.0)"),
            {"id": edge_id, "gid": graph_id, "src": source_row[0], "tgt": target_row[0], "rel": relation, "lbl": edge_label}
        )
        return json.dumps({"status": "success", "source": source_label, "target": target_label, "relation": relation}, ensure_ascii=False), events

    if tool_name == 'update_graph_node':
        label = arguments.get('label')
        new_description = arguments.get('description')
        new_mastery = arguments.get('mastery_score')

        graph_id = await _get_project_graph_id(db, session_id)
        if not graph_id:
            return json.dumps({"status": "error", "message": "No graph found"}, ensure_ascii=False), events
        node_row = (await db.execute(
            text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
            {"gid": graph_id, "label": label}
        )).first()
        if not node_row:
            return json.dumps({"status": "error", "message": f"Node not found: {label}"}, ensure_ascii=False), events

        updates = []
        params = {"nid": node_row[0]}
        if new_description is not None:
            updates.append("description = :desc")
            params["desc"] = new_description
        if new_mastery is not None:
            updates.append("mastery_score = :ms")
            params["ms"] = float(new_mastery)
        if updates:
            await db.execute(text(f"UPDATE nodes SET {', '.join(updates)} WHERE id = :nid"), params)
        return json.dumps({"status": "success", "label": label}, ensure_ascii=False), events

    if tool_name == 'delete_graph_node':
        label = arguments.get('label')

        graph_id = await _get_project_graph_id(db, session_id)
        if not graph_id:
            return json.dumps({"status": "error", "message": "No graph found"}, ensure_ascii=False), events
        node_row = (await db.execute(
            text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
            {"gid": graph_id, "label": label}
        )).first()
        if not node_row:
            return json.dumps({"status": "error", "message": f"Node not found: {label}"}, ensure_ascii=False), events

        await db.execute(text("DELETE FROM edges WHERE source_node_id = :nid OR target_node_id = :nid"), {"nid": node_row[0]})
        await db.execute(text("DELETE FROM nodes WHERE id = :nid"), {"nid": node_row[0]})
        return json.dumps({"status": "success", "label": label}, ensure_ascii=False), events

    if tool_name == 'delete_graph_edge':
        source_label = arguments.get('source_label')
        target_label = arguments.get('target_label')

        graph_id = await _get_project_graph_id(db, session_id)
        if not graph_id:
            return json.dumps({"status": "error", "message": "No graph found"}, ensure_ascii=False), events
        source_row = (await db.execute(
            text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
            {"gid": graph_id, "label": source_label}
        )).first()
        target_row = (await db.execute(
            text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
            {"gid": graph_id, "label": target_label}
        )).first()
        if not source_row or not target_row:
            return json.dumps({"status": "error", "message": f"Nodes not found: {source_label} or {target_label}"}, ensure_ascii=False), events

        await db.execute(
            text("DELETE FROM edges WHERE graph_id = :gid AND source_node_id = :src AND target_node_id = :tgt"),
            {"gid": graph_id, "src": source_row[0], "tgt": target_row[0]}
        )
        return json.dumps({"status": "success", "source": source_label, "target": target_label}, ensure_ascii=False), events

    if tool_name == 'get_graph_nodes':
        graph_id = await _get_project_graph_id(db, session_id)
        if not graph_id:
            return json.dumps([], ensure_ascii=False), events
        nodes_result = await db.execute(
            text("SELECT label, description, mastery_score FROM nodes WHERE graph_id = :gid ORDER BY label"),
            {"gid": graph_id}
        )
        node_list = [{"label": n[0], "description": n[1] or "", "mastery_score": n[2]} for n in nodes_result.fetchall()]
        return json.dumps(node_list, ensure_ascii=False), events

    if tool_name == 'get_graph_node':
        label = arguments.get('label')

        graph_id = await _get_project_graph_id(db, session_id)
        if not graph_id:
            return json.dumps({"error": "No graph found"}, ensure_ascii=False), events
        node_row = (await db.execute(
            text("SELECT label, description, mastery_score FROM nodes WHERE graph_id = :gid AND label = :label"),
            {"gid": graph_id, "label": label}
        )).first()
        if not node_row:
            return json.dumps({"error": "Node not found"}, ensure_ascii=False), events
        return json.dumps({"label": node_row[0], "description": node_row[1] or "", "mastery_score": node_row[2]}, ensure_ascii=False), events

    if tool_name == 'get_graph_edges':
        graph_id = await _get_project_graph_id(db, session_id)
        if not graph_id:
            return json.dumps([], ensure_ascii=False), events
        edges_result = await db.execute(
            text("""SELECT sn.label as source_label, tn.label as target_label, e.relation, e.label
                   FROM edges e
                   JOIN nodes sn ON e.source_node_id = sn.id
                   JOIN nodes tn ON e.target_node_id = tn.id
                   WHERE e.graph_id = :gid ORDER BY e.relation"""),
            {"gid": graph_id}
        )
        edge_list = [{"source": e[0], "target": e[1], "relation": e[2], "label": e[3] or ""} for e in edges_result.fetchall()]
        return json.dumps(edge_list, ensure_ascii=False), events

    if tool_name == 'get_node_edges':
        label = arguments.get('label')

        graph_id = await _get_project_graph_id(db, session_id)
        if not graph_id:
            return json.dumps({"error": "No graph found"}, ensure_ascii=False), events
        node_row = (await db.execute(
            text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
            {"gid": graph_id, "label": label}
        )).first()
        if not node_row:
            return json.dumps({"error": "Node not found"}, ensure_ascii=False), events

        edges_result = await db.execute(
            text("""SELECT sn.label as source_label, tn.label as target_label, e.relation, e.label
                   FROM edges e
                   JOIN nodes sn ON e.source_node_id = sn.id
                   JOIN nodes tn ON e.target_node_id = tn.id
                   WHERE e.graph_id = :gid AND (e.source_node_id = :nid OR e.target_node_id = :nid)"""),
            {"gid": graph_id, "nid": node_row[0]}
        )
        edge_list = [{"source": e[0], "target": e[1], "relation": e[2], "label": e[3] or ""} for e in edges_result.fetchall()]
        return json.dumps({"label": label, "edges": edge_list}, ensure_ascii=False), events

    if tool_name in VIRTUAL_GRAPH_TOOLS:
        return await _execute_virtual_graph_tool(db, session_id, tool_name, arguments), events

    return json.dumps({"status": "error", "message": f"Unknown tool: {tool_name}"}, ensure_ascii=False), events

async def _run_tool_batch(db, session_id: str, tool_calls_buffer: dict, user_claim: str,
                          iteration: int, tool_calls_text_parts: list, tool_results: dict) -> tuple:
    """执行一批工具调用，返回 (task_completed, 待推送的SSE事件列表)"""
    task_completed = False
    pending_events = []

    for tool_name, arguments_str in tool_calls_buffer.items():
        arguments = {}
        try:
            arguments = json.loads(arguments_str)
        except Exception:
            pass
        try:
            if tool_name == 'task_complete':
                result_json = json.dumps({"status": "success", "summary": arguments.get("summary", "")}, ensure_ascii=False)
                task_completed = True
                pending_events.append({"type": "task_complete", "summary": arguments.get("summary", "")})
            else:
                result_json, events = await _execute_tool(db, session_id, tool_name, arguments, user_claim)
                pending_events.extend(events)
                try:
                    result_data = json.loads(result_json)
                except Exception:
                    result_data = result_json
                pending_events.append({
                    "type": "tool_call", "name": tool_name, "arguments": arguments,
                    "result": result_data, "iteration": iteration
                })
        except Exception as e:
            result_json = json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False)
            pending_events.append({
                "type": "tool_call", "name": tool_name, "arguments": arguments,
                "result": {"status": "error", "error": str(e)}, "iteration": iteration
            })

        tool_calls_text_parts.append(_tool_call_xml(iteration, tool_name, arguments, result_json))
        if tool_name != 'task_complete':
            tool_results[tool_name] = result_json

    return task_completed, pending_events

async def _run_tool_continuations(agent, db, session_id: str, user_claim: str, assistant_message_id: str,
                                  tool_calls_buffer: dict, tool_call_ids: dict, tool_results: dict,
                                  reasoning_content: str, tool_calls_text_parts: list):
    """将工具结果回传给AI并循环执行后续工具调用，yield SSE事件。max_iterations依赖task_complete结束。"""
    max_iterations = 50
    iteration = 0
    task_completed = False

    while iteration < max_iterations and not task_completed:
        if not (tool_calls_buffer or tool_results):
            break
        iteration += 1

        # 构建工具消息：已执行工具的真实结果 + 未执行工具的成功占位
        tool_messages = []
        for tool_name, result in tool_results.items():
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_ids.get(tool_name, f"call_{tool_name}"),
                "name": tool_name,
                "content": result
            })
        for tool_name in tool_calls_buffer.keys():
            if tool_name not in tool_results:
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_ids.get(tool_name, f"call_{tool_name}"),
                    "name": tool_name,
                    "content": json.dumps({"status": "success"}, ensure_ascii=False)
                })
        if not tool_messages:
            break

        yield {"type": "thinking"}

        tool_calls_buffer.clear()
        tool_call_ids.clear()
        tool_results.clear()
        continuation_response = ''
        async for chunk in agent.process_tool_results(tool_messages, reasoning_content):
            if chunk['type'] == 'text':
                continuation_response += chunk['content']
                yield {"type": "text", "content": chunk['content']}
            elif chunk['type'] == 'reasoning':
                reasoning_content += chunk['content']
            elif chunk['type'] == 'tool_call':
                tool_name = chunk['name']
                if tool_name not in tool_calls_buffer:
                    tool_calls_buffer[tool_name] = ''
                    tool_call_ids[tool_name] = chunk.get('id', '')
                tool_calls_buffer[tool_name] += chunk['arguments']

        if continuation_response:
            await db.execute(
                text("UPDATE messages SET content = content || :extra WHERE id = :mid"),
                {"extra": continuation_response, "mid": assistant_message_id}
            )

        task_completed, pending_events = await _run_tool_batch(
            db, session_id, tool_calls_buffer, user_claim, iteration, tool_calls_text_parts, tool_results
        )
        for event in pending_events:
            yield event
        await db.commit()

@router.post("/sessions", response_model=TeachingSessionResponse)
async def create_session(session: TeachingSessionCreate, current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    await require_project(db, session.project_id, current_user.id)

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
async def get_session_detail(request: Request, session_id: str, current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    await require_session(db, session_id, current_user.id)

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
async def create_message(session_id: str, message: MessageCreate, current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    await require_session(db, session_id, current_user.id)

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
async def list_messages(session_id: str, branch_id: str = None, current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    await require_session(db, session_id, current_user.id)

    if branch_id:
        result = await db.execute(text("SELECT * FROM messages WHERE session_id = :session_id AND branch_id = :branch_id AND is_active = 1 ORDER BY created_at"), {"session_id": session_id, "branch_id": branch_id})
    else:
        result = await db.execute(text("SELECT * FROM messages WHERE session_id = :session_id AND branch_id IS NULL AND is_active = 1 ORDER BY created_at"), {"session_id": session_id})
    messages = result.fetchall()
    return [dict(row._mapping) for row in messages]

@router.put("/sessions/{session_id}/messages/{message_id}")
async def update_message_and_create_branch(session_id: str, message_id: str, message: MessageCreate, current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    await require_session(db, session_id, current_user.id)

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
    
    agent = TeachingAgent(db, session_id)

    # 收集完整的响应文本和工具调用
    response_text = ''
    tool_calls_buffer = {}
    tool_call_ids = {}
    tool_results = {}
    reasoning_content = ""
    tool_calls_text_parts = []

    async for chunk in agent.process_user_input(message.content):
        if chunk['type'] == 'text':
            response_text += chunk['content']
        elif chunk['type'] == 'reasoning':
            reasoning_content += chunk['content']
        elif chunk['type'] == 'tool_call':
            tool_name = chunk['name']
            if tool_name not in tool_calls_buffer:
                tool_calls_buffer[tool_name] = ''
                tool_call_ids[tool_name] = chunk.get('id', '')
            tool_calls_buffer[tool_name] += chunk['arguments']

    # 创建新的AI响应消息（parent_id 指向被编辑的user消息，保证SSE幂等检查能识别"已有回复"，避免与流式路径双写）
    assistant_message = Message(
        id=str(uuid4()),
        session_id=session_id,
        parent_id=message_id,
        role="assistant",
        content=response_text,
        is_active=True
    )
    db.add(assistant_message)

    # 执行首轮工具调用
    task_completed, _ = await _run_tool_batch(
        db, session_id, tool_calls_buffer, message.content, 0, tool_calls_text_parts, tool_results
    )
    await db.commit()

    # 多轮工具调用循环（依赖task_complete结束）
    if not task_completed:
        async for _event in _run_tool_continuations(
            agent, db, session_id, message.content, assistant_message.id,
            tool_calls_buffer, tool_call_ids, tool_results, reasoning_content, tool_calls_text_parts
        ):
            pass

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

async def _pending_user_message_id(db, session_id: str) -> str | None:
    """最后一条还没有 assistant 回复的 user 消息 id；没有则返回 None。

    用于刷新/重连时判断是否需要（继续）流式生成。
    """
    rows = await db.execute(
        text("""SELECT id FROM messages
                WHERE session_id = :sid AND role = 'user' AND is_active = 1
                ORDER BY created_at DESC LIMIT 1"""),
        {"sid": session_id}
    )
    row = rows.first()
    if not row:
        return None
    uid = row[0]
    reply = await db.execute(
        text("""SELECT id FROM messages WHERE session_id = :sid AND role = 'assistant'
                AND parent_id = :pid AND is_active = 1"""),
        {"sid": session_id, "pid": uid}
    )
    if reply.first():
        return None
    return uid


async def _run_teaching_stream(state):
    """Teaching 生成后台任务：与 HTTP 连接解耦，结束后必然落库。

    刷新/断开连接不影响生成；新连接通过 teaching_streams.ensure_stream
    附加订阅并先收到 partial_text 回放。
    """
    session_id = state.session_id
    try:
        async with AsyncSessionLocal() as db:
            agent = TeachingAgent(db, session_id)

            msg_result = await db.execute(
                text("SELECT * FROM messages WHERE id = :mid AND role = 'user' AND is_active = 1"),
                {"mid": state.user_message_id}
            )
            user_row = msg_result.first()
            if not user_row:
                state.status = "done"
                teaching_streams.broadcast(state, {"type": "done"})
                return
            last_user_message = dict(user_row._mapping)["content"]

            # 幂等保护：生成前再查一次是否已有回复（并发/编辑时避免双写）
            existing_reply = await db.execute(
                text("""SELECT id FROM messages WHERE session_id = :sid AND role = 'assistant'
                        AND parent_id = :pid AND is_active = 1"""),
                {"sid": session_id, "pid": state.user_message_id}
            )
            if existing_reply.first():
                state.status = "done"
                teaching_streams.broadcast(state, {"type": "done"})
                return

            teaching_streams.broadcast(state, {"type": "thinking"})

            # 收集完整的响应文本和工具调用
            full_response = ''
            tool_calls_buffer = {}
            tool_call_ids = {}
            tool_results = {}
            reasoning_content = ""
            tool_calls_text_parts = []

            async for chunk in agent.process_user_input(last_user_message):
                if chunk['type'] == 'text':
                    full_response += chunk['content']
                    state.partial_text += chunk['content']
                    teaching_streams.broadcast(state, {"type": "text", "content": chunk['content']})
                elif chunk['type'] == 'reasoning':
                    reasoning_content += chunk['content']
                elif chunk['type'] == 'tool_call':
                    tool_name = chunk['name']
                    if tool_name not in tool_calls_buffer:
                        tool_calls_buffer[tool_name] = ''
                        tool_call_ids[tool_name] = chunk.get('id', '')
                    tool_calls_buffer[tool_name] += chunk['arguments']

            assistant_message = Message(
                id=str(uuid4()),
                session_id=session_id,
                parent_id=state.user_message_id,
                role="assistant",
                content=full_response,
                is_active=True
            )
            db.add(assistant_message)

            # 执行首轮工具调用
            task_completed, pending_events = await _run_tool_batch(
                db, session_id, tool_calls_buffer, last_user_message, 0, tool_calls_text_parts, tool_results
            )
            for event in pending_events:
                teaching_streams.broadcast(state, event)
            await db.commit()

            # 多轮工具调用循环（依赖task_complete结束）
            if not task_completed:
                async for event in _run_tool_continuations(
                    agent, db, session_id, last_user_message, assistant_message.id,
                    tool_calls_buffer, tool_call_ids, tool_results, reasoning_content, tool_calls_text_parts
                ):
                    teaching_streams.broadcast(state, event)

            # 将工具调用XML追加到消息内容中，刷新页面后仍能以artifact形式显示
            if tool_calls_text_parts:
                extra_content = "\n\n" + "".join(tool_calls_text_parts)
                await db.execute(
                    text("UPDATE messages SET content = content || :extra WHERE id = :mid"),
                    {"extra": extra_content, "mid": assistant_message.id}
                )
                await db.commit()

            state.status = "done"
            teaching_streams.broadcast(state, {"type": "done"})
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"[teaching] session {session_id} generation failed: {e}")
        state.status = "error"
        state.error = str(e)
        teaching_streams.broadcast(state, {"type": "error", "error": str(e)})
    finally:
        teaching_streams.finish(state)


@router.get("/stream/{session_id}")
async def stream_teaching(session_id: str, project_id: str, current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    await require_session(db, session_id, current_user.id)
    await require_project(db, project_id, current_user.id)

    # 无待回复的 user 消息（已有回复/无消息）时直接结束
    pending_id = await _pending_user_message_id(db, session_id)
    if not pending_id:
        async def done_stream():
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(done_stream(), media_type="text/event-stream")

    # 后台任务已在运行则附加订阅（刷新后的页面），否则启动生成
    state, queue = teaching_streams.ensure_stream(session_id, pending_id, _run_teaching_stream)

    async def stream_generator():
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            teaching_streams.unsubscribe(state, queue)

    return StreamingResponse(stream_generator(), media_type="text/event-stream")

@router.get("/sessions/{session_id}/progress")
async def get_session_progress(session_id: str, current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    await require_session(db, session_id, current_user.id)

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
async def promote_concepts(session_id: str, request: Request, current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    await require_session(db, session_id, current_user.id)

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

    for concept_id in concept_ids:
        # 获取concept
        result = await db.execute(
            text("SELECT * FROM concepts WHERE id = :concept_id AND session_id = :session_id"),
            {"concept_id": concept_id, "session_id": session_id}
        )
        concept = result.fetchone()

        if concept:
            concept_name = concept[2]  # name字段在第2列（索引2）
            status = concept[5]  # status字段在第5列

            if status == 'mastered':
                # 挂载式合并：同名节点复用（mastery取较大值、补concept_id），新节点自动挂载到图谱网络
                node_id, created = await merge_or_create_node(
                    db, graph_id, concept_name, concept_id=concept_id, mastery=0.3
                )
                if created:
                    await mount_node(db, graph_id, node_id, concept_name)

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
async def promote_by_ids(request: Request, current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    """从图谱页面调用：根据concept_ids沉淀概念到图谱"""
    body = await request.json()
    project_id = body.get("project_id")
    concept_ids = body.get("concept_ids", [])

    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")

    await require_project(db, project_id, current_user.id)

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
async def delete_session(session_id: str, current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    await require_session(db, session_id, current_user.id)

    await db.execute(text("DELETE FROM misconceptions WHERE session_id = :session_id"), {"session_id": session_id})
    await db.execute(text("DELETE FROM concepts WHERE session_id = :session_id"), {"session_id": session_id})
    await db.execute(text("DELETE FROM messages WHERE session_id = :session_id"), {"session_id": session_id})
    await db.execute(text("DELETE FROM teaching_sessions WHERE id = :session_id"), {"session_id": session_id})
    await db.commit()
    return {"status": "ok"}
