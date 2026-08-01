from fastapi import APIRouter, Depends, HTTPException
from fastapi.requests import Request
from uuid import uuid4
import json

from sqlalchemy import text
from app.core.deps import get_current_user, get_db
from app.models.user import User

router = APIRouter()

@router.post("/promote-virtual-node/{vnode_id}")
async def promote_virtual_node(
    vnode_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db = Depends(get_db)
):
    """推送虚拟图节点到Integration Level，创建主node、子nodes和边"""
    body = await request.json() if request else {}
    graph_id = body.get("graph_id")

    # 获取虚拟图节点信息
    vnode_result = await db.execute(
        text("SELECT * FROM virtual_graph_nodes WHERE id = :vnode_id"),
        {"vnode_id": vnode_id}
    )
    vnode_row = vnode_result.first()
    if not vnode_row:
        raise HTTPException(status_code=404, detail="Virtual graph node not found")

    vnode = dict(vnode_row._mapping)
    main_label = vnode["label"]
    properties_json = vnode.get("properties", "[]")

    # 解析properties字段（二元组列表）
    try:
        properties = json.loads(properties_json) if properties_json else []
    except json.JSONDecodeError:
        properties = []

    # 如果没有提供graph_id，使用虚拟图关联的graph_id
    if not graph_id:
        vg_result = await db.execute(
            text("SELECT graph_id FROM virtual_graphs WHERE id = :vgid"),
            {"vgid": vnode["virtual_graph_id"]}
        )
        vg_row = vg_result.first()
        graph_id = vg_row[0] if vg_row else None

    if not graph_id:
        raise HTTPException(status_code=400, detail="Graph ID required")

    # 创建主node
    main_node_id = str(uuid4())
    await db.execute(
        text("""INSERT INTO nodes (id, graph_id, label, mastery_score, created_at)
               VALUES (:id, :gid, :label, 0.0, datetime('now'))"""),
        {"id": main_node_id, "gid": graph_id, "label": main_label}
    )

    # 为每个二元组创建子node和边
    child_node_ids = []
    for prop in properties:
        if len(prop) >= 2:
            relation = prop[0]  # 和node的关系（边的relation）
            child_name = prop[1]  # 名称（子node的label）

            # 创建子node（掌握度0.0）
            child_node_id = str(uuid4())
            await db.execute(
                text("""INSERT INTO nodes (id, graph_id, label, mastery_score, created_at)
                       VALUES (:id, :gid, :label, 0.0, datetime('now'))"""),
                {"id": child_node_id, "gid": graph_id, "label": child_name}
            )
            child_node_ids.append(child_node_id)

            # 创建边：主node → 子node，relation为和node的关系
            edge_id = str(uuid4())
            await db.execute(
                text("""INSERT INTO edges (id, graph_id, source_node_id, target_node_id, relation, created_at)
                       VALUES (:id, :gid, :src, :tgt, :rel, datetime('now'))"""),
                {"id": edge_id, "gid": graph_id, "src": main_node_id, "tgt": child_node_id, "rel": relation}
            )

    # 计算主node的掌握度（所有子node的平均值）
    if child_node_ids:
        # 所有子node初始掌握度都是0.0，所以平均值也是0.0
        # 但如果后续子node掌握度更新，主node也需要更新
        main_mastery = 0.0
        await db.execute(
            text("UPDATE nodes SET mastery_score = :ms WHERE id = :nid"),
            {"ms": main_mastery, "nid": main_node_id}
        )

    # 更新虚拟图节点的node_id字段，关联到真实node
    await db.execute(
        text("UPDATE virtual_graph_nodes SET node_id = :nid WHERE id = :vnid"),
        {"nid": main_node_id, "vnid": vnode_id}
    )

    # 更新图谱的updated_at
    await db.execute(
        text("UPDATE graphs SET updated_at = datetime('now') WHERE id = :gid"),
        {"gid": graph_id}
    )

    await db.commit()

    return {
        "status": "ok",
        "main_node_id": main_node_id,
        "main_label": main_label,
        "child_count": len(child_node_ids),
        "children": [{"id": cid, "label": properties[i][1], "relation": properties[i][0]}
                     for i, cid in enumerate(child_node_ids) if i < len(properties)]
    }