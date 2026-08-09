from fastapi import APIRouter, Depends, HTTPException
from fastapi.requests import Request
import json

from sqlalchemy import text
from app.core.deps import get_current_active_user, get_db, require_virtual_node
from app.models.user import User
from app.services.graph_mount import merge_or_create_node, ensure_edge, mount_node, project_virtual_graph_edges

router = APIRouter()

@router.post("/promote-virtual-node/{vnode_id}")
async def promote_virtual_node(
    vnode_id: str,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db = Depends(get_db)
):
    """推送虚拟图节点到Integration Level（挂载式合并）：
    同名节点复用合并，新节点自动挂载到图谱最近邻节点，边去重，
    并把虚拟图内部的 vnode→vnode 边投影为真实图谱边。"""
    await require_virtual_node(db, vnode_id, current_user.id)

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

    # 主node：合并式创建（同名复用）
    main_node_id, main_created = await merge_or_create_node(db, graph_id, main_label)

    # 为每个二元组创建/复用子node和边（边去重）
    child_node_ids = []
    for prop in properties:
        if len(prop) >= 2:
            relation = prop[0]  # 和node的关系（边的relation）
            child_name = prop[1]  # 名称（子node的label）

            child_node_id, _ = await merge_or_create_node(db, graph_id, child_name)
            child_node_ids.append(child_node_id)

            await ensure_edge(db, graph_id, main_node_id, child_node_id, relation)

    # 计算主node的掌握度（子节点平均值，但与已有掌握度取较大值，避免覆盖）
    if child_node_ids:
        total = 0.0
        for cid in child_node_ids:
            result = await db.execute(
                text("SELECT mastery_score FROM nodes WHERE id = :nid"),
                {"nid": cid}
            )
            row = result.first()
            total += float(row[0] or 0.0) if row else 0.0
        main_mastery = total / len(child_node_ids)
        await db.execute(
            text("UPDATE nodes SET mastery_score = MAX(mastery_score, :ms) WHERE id = :nid"),
            {"ms": main_mastery, "nid": main_node_id}
        )

    # 投影虚拟图内部边：把 vnode→vnode 关系（parent/prerequisite等）沉淀为真实图谱边
    projected = await project_virtual_graph_edges(db, graph_id, vnode_id=vnode_id)

    # 挂载：把新主node接入已有图谱网络（related边到最近邻节点，已有精确边时跳过）
    mounted = []
    if main_created:
        mounted = await mount_node(db, graph_id, main_node_id, main_label)

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
        "merged": not main_created,
        "child_count": len(child_node_ids),
        "children": [{"id": cid, "label": properties[i][1], "relation": properties[i][0]}
                     for i, cid in enumerate(child_node_ids) if i < len(properties)],
        "mounted": [{"node_id": m["node_id"], "label": m["label"], "score": round(m["score"], 3)}
                    for m in mounted],
        "projected_edges": projected
    }
