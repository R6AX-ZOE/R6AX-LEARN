from fastapi import APIRouter, Depends, HTTPException
from fastapi.requests import Request
from uuid import uuid4
import json

from sqlalchemy import text
from app.core.deps import get_current_user, get_db
from app.models.user import User
from app.services.embedding_service import get_embedding_service

router = APIRouter()

@router.get("/graphs/{project_id}")
async def list_graphs(project_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    """获取项目的所有图谱列表"""
    result = await db.execute(
        text("SELECT g.*, d.name as directory_name FROM graphs g LEFT JOIN directories d ON g.directory_id = d.id WHERE g.project_id = :project_id ORDER BY g.created_at"),
        {"project_id": project_id}
    )
    return [dict(row._mapping) for row in result.fetchall()]

@router.post("/graphs/{project_id}")
async def create_graph(project_id: str, request: Request, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    """创建新图谱，可关联目录"""
    body = await request.json() if request else {}
    name = body.get("name", "知识图谱")
    directory_id = body.get("directory_id")

    new_id = str(uuid4())
    await db.execute(
        text("INSERT INTO graphs (id, project_id, directory_id, name, created_at, updated_at) VALUES (:id, :pid, :did, :name, datetime('now'), datetime('now'))"),
        {"id": new_id, "pid": project_id, "did": directory_id, "name": name}
    )
    await db.commit()
    return {"id": new_id, "name": name, "status": "ok"}

@router.get("/graph/{graph_id}")
async def get_graph_detail(graph_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    """获取单个图谱详情"""
    result = await db.execute(
        text("SELECT g.*, d.name as directory_name FROM graphs g LEFT JOIN directories d ON g.directory_id = d.id WHERE g.id = :gid"),
        {"gid": graph_id}
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Graph not found")
    return dict(row._mapping)

@router.put("/graph/{graph_id}")
async def update_graph(graph_id: str, request: Request, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    """更新图谱信息"""
    body = await request.json()
    name = body.get("name")
    directory_id = body.get("directory_id")

    updates = []
    params = {"gid": graph_id}
    if name is not None:
        updates.append("name = :name")
        params["name"] = name
    if directory_id is not None:
        updates.append("directory_id = :did")
        params["did"] = directory_id

    if updates:
        sql = f"UPDATE graphs SET {', '.join(updates)}, updated_at = datetime('now') WHERE id = :gid"
        await db.execute(text(sql), params)
        await db.commit()

    return {"status": "ok"}

@router.delete("/graph/{graph_id}")
async def delete_graph(graph_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    """删除图谱及其所有节点和边"""
    # 删除关联的边
    await db.execute(text("DELETE FROM edges WHERE graph_id = :gid"), {"gid": graph_id})
    # 删除关联的节点
    await db.execute(text("DELETE FROM nodes WHERE graph_id = :gid"), {"gid": graph_id})
    # 删除图谱
    await db.execute(text("DELETE FROM graphs WHERE id = :gid"), {"gid": graph_id})
    await db.commit()
    return {"status": "ok"}

@router.get("/nodes/{graph_id}")
async def list_nodes(graph_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    result = await db.execute(
        text("SELECT * FROM nodes WHERE graph_id = :gid ORDER BY label"),
        {"gid": graph_id}
    )
    return [dict(row._mapping) for row in result.fetchall()]

@router.post("/nodes")
async def create_node(request: Request, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    body = await request.json()
    graph_id = body.get("graph_id")
    label = body.get("label", "").strip()
    mastery_score = body.get("mastery_score", 0.0)

    if not graph_id or not label:
        raise HTTPException(status_code=400, detail="graph_id and label are required")

    # 确保graph存在
    graph = await db.execute(text("SELECT id FROM graphs WHERE id = :gid"), {"gid": graph_id})
    if not graph.first():
        raise HTTPException(status_code=404, detail="Graph not found")

    node_id = str(uuid4())
    await db.execute(
        text("""INSERT INTO nodes (id, graph_id, concept_id, label, mastery_score)
               VALUES (:id, :gid, NULL, :label, :ms)"""),
        {"id": node_id, "gid": graph_id, "label": label, "ms": mastery_score}
    )

    # 更新graph updated_at
    await db.execute(text("UPDATE graphs SET updated_at = datetime('now') WHERE id = :gid"), {"gid": graph_id})
    await db.commit()

    return {"id": node_id, "status": "ok"}

@router.put("/nodes/{node_id}")
async def update_node(node_id: str, request: Request, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    body = await request.json()
    label = body.get("label", "").strip()
    mastery_score = body.get("mastery_score")

    existing = await db.execute(text("SELECT id FROM nodes WHERE id = :nid"), {"nid": node_id})
    if not existing.first():
        raise HTTPException(status_code=404, detail="Node not found")

    updates = []
    params = {"nid": node_id}
    if label is not None:
        updates.append("label = :label")
        params["label"] = label
    if mastery_score is not None:
        updates.append("mastery_score = :ms")
        params["ms"] = float(mastery_score)

    if updates:
        sql = f"UPDATE nodes SET {', '.join(updates)} WHERE id = :nid"
        await db.execute(text(sql), params)
        await db.commit()

    return {"status": "ok"}

@router.delete("/nodes/{node_id}")
async def delete_node(node_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    # 先删除关联的边
    await db.execute(text("DELETE FROM edges WHERE source_node_id = :nid OR target_node_id = :nid"), {"nid": node_id})
    # 删除节点
    await db.execute(text("DELETE FROM nodes WHERE id = :nid"), {"nid": node_id})
    await db.commit()
    return {"message": "Node deleted successfully"}

@router.get("/edges/{graph_id}")
async def list_edges(graph_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    result = await db.execute(
        text("""SELECT e.*, sn.label as source_label, tn.label as target_label
               FROM edges e
               LEFT JOIN nodes sn ON e.source_node_id = sn.id
               LEFT JOIN nodes tn ON e.target_node_id = tn.id
               WHERE e.graph_id = :gid ORDER BY e.relation"""),
        {"gid": graph_id}
    )
    return [dict(row._mapping) for row in result.fetchall()]

@router.post("/edges")
async def create_edge(request: Request, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    body = await request.json()
    graph_id = body.get("graph_id")
    source_node_id = body.get("source_node_id")
    target_node_id = body.get("target_node_id")
    relation = body.get("relation", "related")
    label = body.get("label", "")

    if not all([graph_id, source_node_id, target_node_id]):
        raise HTTPException(status_code=400, detail="graph_id, source_node_id, target_node_id are required")

    edge_id = str(uuid4())
    await db.execute(
        text("""INSERT INTO edges (id, graph_id, source_node_id, target_node_id, relation, label, weight)
               VALUES (:id, :gid, :src, :tgt, :rel, :lbl, 1.0)"""),
        {"id": edge_id, "gid": graph_id, "src": source_node_id, "tgt": target_node_id,
         "rel": relation, "lbl": label}
    )
    await db.execute(text("UPDATE graphs SET updated_at = datetime('now') WHERE id = :gid"), {"gid": graph_id})
    await db.commit()

    return {"id": edge_id, "status": "ok"}

@router.delete("/edges/{edge_id}")
async def delete_edge(edge_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    await db.execute(text("DELETE FROM edges WHERE id = :eid"), {"eid": edge_id})
    await db.commit()
    return {"message": "Edge deleted successfully"}

# ====== 虚拟图 CRUD API ======

@router.get("/virtual-graphs/{project_id}")
async def list_virtual_graphs(project_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    """获取项目的所有虚拟图列表"""
    result = await db.execute(
        text("""SELECT vg.*, ts.title as session_title, g.name as graph_name
               FROM virtual_graphs vg
               LEFT JOIN teaching_sessions ts ON vg.session_id = ts.id
               LEFT JOIN graphs g ON vg.graph_id = g.id
               WHERE ts.project_id = :project_id
               ORDER BY vg.created_at DESC"""),
        {"project_id": project_id}
    )
    return [dict(row._mapping) for row in result.fetchall()]

@router.post("/virtual-graphs")
async def create_virtual_graph(request: Request, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    """创建新的虚拟图"""
    body = await request.json()
    session_id = body.get("session_id")
    graph_id = body.get("graph_id")
    name = body.get("name", "虚拟知识图")
    description = body.get("description", "")
    nodes = body.get("nodes", [])  # 节点列表
    edges = body.get("edges", [])  # 内部边列表
    node_connections = body.get("node_connections", [])  # 到真实节点的连接列表

    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    # 创建虚拟图
    vg_id = str(uuid4())
    await db.execute(
        text("INSERT INTO virtual_graphs (id, session_id, graph_id, name, description, created_at, updated_at) VALUES (:id, :sid, :gid, :name, :desc, datetime('now'), datetime('now'))"),
        {"id": vg_id, "sid": session_id, "gid": graph_id, "name": name, "desc": description}
    )

    # 创建虚拟图节点
    vnode_ids = {}
    for idx, node_data in enumerate(nodes):
        vnode_id = str(uuid4())
        label = node_data.get("label")
        # properties字段：二元组列表 [[和node的关系, 名称], ...]
        properties_json = json.dumps(node_data.get("properties", []), ensure_ascii=False)
        content = node_data.get("content", "")
        mastery = node_data.get("mastery_score", 0)
        real_node_id = node_data.get("node_id")

        await db.execute(
            text("""INSERT INTO virtual_graph_nodes (id, virtual_graph_id, node_id, label, properties, content, order_index, mastery_score)
                   VALUES (:id, :vgid, :nid, :label, :props, :content, :idx, :ms)"""),
            {"id": vnode_id, "vgid": vg_id, "nid": real_node_id, "label": label, "props": properties_json, "content": content, "idx": idx, "ms": mastery}
        )
        vnode_ids[label] = vnode_id

    # 创建虚拟图内部边
    for edge_data in edges:
        source_label = edge_data.get("source")
        target_label = edge_data.get("target")
        relation = edge_data.get("relation", "related")
        label = edge_data.get("label", "")

        if source_label in vnode_ids and target_label in vnode_ids:
            edge_id = str(uuid4())
            await db.execute(
                text("""INSERT INTO virtual_graph_edges (id, virtual_graph_id, source_vnode_id, target_vnode_id, relation, label)
                       VALUES (:id, :vgid, :src, :tgt, :rel, :lbl)"""),
                {"id": edge_id, "vgid": vg_id, "src": vnode_ids[source_label], "tgt": vnode_ids[target_label], "rel": relation, "lbl": label}
            )

    # 创建虚拟图到真实节点的连接
    for conn_data in node_connections:
        node_id = conn_data.get("node_id")
        relation_type = conn_data.get("relation_type", "contains")

        if node_id:
            conn_id = str(uuid4())
            await db.execute(
                text("""INSERT INTO virtual_graph_to_node_edges (id, virtual_graph_id, node_id, relation_type)
                       VALUES (:id, :vgid, :nid, :rtype)"""),
                {"id": conn_id, "vgid": vg_id, "nid": node_id, "rtype": relation_type}
            )

    await db.commit()

    # 生成虚拟图的embedding（用于RAG搜索）
    try:
        embedding_service = get_embedding_service()

        # 组合虚拟图内容为文本（用于embedding）
        content_text = f"{name}\n{description}\n"
        for node in nodes:
            content_text += f"{node.get('label')}: {node.get('description', '')} {node.get('content', '')}\n"

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

        print(f"Generated embedding for virtual graph: {name}")
    except Exception as e:
        print(f"Error generating embedding for virtual graph: {e}")
        # 不影响主流程，继续返回成功

    return {"id": vg_id, "name": name, "node_count": len(nodes), "status": "ok"}

@router.get("/virtual-graph/{vg_id}")
async def get_virtual_graph_detail(vg_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    """获取单个虚拟图详情，包含节点和边"""
    result = await db.execute(
        text("""SELECT vg.*, ts.title as session_title, g.name as graph_name
               FROM virtual_graphs vg
               LEFT JOIN teaching_sessions ts ON vg.session_id = ts.id
               LEFT JOIN graphs g ON vg.graph_id = g.id
               WHERE vg.id = :vgid"""),
        {"vgid": vg_id}
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Virtual graph not found")

    vg = dict(row._mapping)

    # 获取虚拟图节点
    nodes_result = await db.execute(
        text("SELECT * FROM virtual_graph_nodes WHERE virtual_graph_id = :vgid ORDER BY order_index"),
        {"vgid": vg_id}
    )
    vg["nodes"] = [dict(row._mapping) for row in nodes_result.fetchall()]

    # 获取虚拟图内部边
    edges_result = await db.execute(
        text("""SELECT vge.*, svn.label as source_label, tvn.label as target_label
               FROM virtual_graph_edges vge
               LEFT JOIN virtual_graph_nodes svn ON vge.source_vnode_id = svn.id
               LEFT JOIN virtual_graph_nodes tvn ON vge.target_vnode_id = tvn.id
               WHERE vge.virtual_graph_id = :vgid"""),
        {"vgid": vg_id}
    )
    vg["edges"] = [dict(row._mapping) for row in edges_result.fetchall()]

    # 获取虚拟图到真实节点的连接
    connections_result = await db.execute(
        text("""SELECT vgne.*, n.label as node_label
               FROM virtual_graph_to_node_edges vgne
               LEFT JOIN nodes n ON vgne.node_id = n.id
               WHERE vgne.virtual_graph_id = :vgid"""),
        {"vgid": vg_id}
    )
    vg["node_connections"] = [dict(row._mapping) for row in connections_result.fetchall()]

    return vg

@router.put("/virtual-graph/{vg_id}")
async def update_virtual_graph(vg_id: str, request: Request, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    """更新虚拟图信息"""
    body = await request.json()
    name = body.get("name")
    description = body.get("description")
    graph_id = body.get("graph_id")

    updates = []
    params = {"vgid": vg_id}
    if name is not None:
        updates.append("name = :name")
        params["name"] = name
    if description is not None:
        updates.append("description = :desc")
        params["desc"] = description
    if graph_id is not None:
        updates.append("graph_id = :gid")
        params["gid"] = graph_id

    if updates:
        sql = f"UPDATE virtual_graphs SET {', '.join(updates)}, updated_at = datetime('now') WHERE id = :vgid"
        await db.execute(text(sql), params)
        await db.commit()

    return {"status": "ok"}

@router.delete("/virtual-graph/{vg_id}")
async def delete_virtual_graph(vg_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    """删除虚拟图及其所有节点、边和连接"""
    # 删除到真实节点的连接
    await db.execute(text("DELETE FROM virtual_graph_to_node_edges WHERE virtual_graph_id = :vgid"), {"vgid": vg_id})
    # 删除虚拟图内部边
    await db.execute(text("DELETE FROM virtual_graph_edges WHERE virtual_graph_id = :vgid"), {"vgid": vg_id})
    # 删除虚拟图节点
    await db.execute(text("DELETE FROM virtual_graph_nodes WHERE virtual_graph_id = :vgid"), {"vgid": vg_id})
    # 删除嵌入向量
    await db.execute(text("DELETE FROM virtual_graph_embeddings WHERE virtual_graph_id = :vgid"), {"vgid": vg_id})
    # 删除虚拟图
    await db.execute(text("DELETE FROM virtual_graphs WHERE id = :vgid"), {"vgid": vg_id})
    await db.commit()
    return {"status": "ok"}

# ====== RAG搜索API ======

@router.post("/virtual-graphs/search")
async def search_virtual_graphs_rag(
    request: Request,
    current_user: User = Depends(get_current_user),
    db = Depends(get_db)
):
    """使用本地RAG搜索虚拟图（基于embedding相似度）"""
    body = await request.json()
    query = body.get("query", "")
    project_id = body.get("project_id")
    top_k = body.get("top_k", 5)

    if not query or not project_id:
        raise HTTPException(status_code=400, detail="query and project_id required")

    try:
        # 获取数据库路径
        from app.config import settings
        db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")

        # 使用embedding服务搜索
        embedding_service = get_embedding_service()
        search_results = embedding_service.search_virtual_graphs(
            db_path=db_path,
            query=query,
            project_id=project_id,
            top_k=top_k
        )

        # 为每个结果添加详细节点信息（符合前端期望格式）
        enhanced_results = []
        for result in search_results:
            vg_id = result["id"]

            # 获取虚拟图节点（取第一个节点作为主要结果）
            nodes_result = await db.execute(
                text("SELECT id, label, content FROM virtual_graph_nodes WHERE virtual_graph_id = :vgid ORDER BY order_index LIMIT 1"),
                {"vgid": vg_id}
            )
            node_row = nodes_result.first()

            if node_row:
                node_id, node_label, node_content = node_row
                preview = node_content or ""

                enhanced_results.append({
                    "node_id": node_id,
                    "node_label": node_label,
                    "virtual_graph_id": vg_id,
                    "virtual_graph_name": result["name"],
                    "score": result["score"],
                    "preview": preview[:200] + "..." if len(preview) > 200 else preview
                })
            else:
                # 如果没有节点，返回虚拟图本身的信息
                enhanced_results.append({
                    "node_id": None,
                    "node_label": result["name"],
                    "virtual_graph_id": vg_id,
                    "virtual_graph_name": result["name"],
                    "score": result["score"],
                    "preview": result["description"] or ""
                })

        return {"results": enhanced_results, "query": query, "total": len(enhanced_results)}

    except Exception as e:
        print(f"Error in RAG search: {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
