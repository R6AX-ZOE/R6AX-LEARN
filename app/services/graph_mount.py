"""
挂载式合并服务
- 合并：同名（label）节点复用，不重复创建孤立节点
- 挂载：新节点自动连接到图谱中最相似的已有节点（related 边），保证网络连通
- 投影：把虚拟图内部的 vnode→vnode 边投影为真实图谱边
- 去重：边按 (graph_id, source, target, relation) 去重
"""

import difflib
from uuid import uuid4

from sqlalchemy import text


# 虚拟图边关系 → 真实图边关系映射
VG_EDGE_RELATION_MAP = {
    "prerequisite": "prerequisite",
    "related": "related",
    "parent": "parent",
    "next": "related",
    "detail": "related",
    "contains": "related",
    "references": "related",
    "expands": "related",
}


async def find_node_by_label(db, graph_id: str, label: str):
    """在图谱中按 label 精确查找节点，返回 node_id 或 None"""
    label = label.strip()
    if not label:
        return None
    result = await db.execute(
        text("SELECT id FROM nodes WHERE graph_id = :gid AND label = :label"),
        {"gid": graph_id, "label": label}
    )
    row = result.first()
    return row[0] if row else None


async def merge_or_create_node(db, graph_id: str, label: str, concept_id=None, mastery: float = 0.0):
    """合并式创建：已存在则复用（mastery 取较大值、补 concept_id），否则新建。
    返回 (node_id, created)"""
    label = label.strip()
    node_id = await find_node_by_label(db, graph_id, label)
    if node_id:
        result = await db.execute(
            text("SELECT mastery_score, concept_id FROM nodes WHERE id = :nid"),
            {"nid": node_id}
        )
        row = result.first()
        current_mastery = row[0] if row and row[0] is not None else 0.0
        if mastery > current_mastery:
            await db.execute(
                text("UPDATE nodes SET mastery_score = :ms WHERE id = :nid"),
                {"ms": mastery, "nid": node_id}
            )
        if concept_id and row and not row[1]:
            await db.execute(
                text("UPDATE nodes SET concept_id = :cid WHERE id = :nid"),
                {"cid": concept_id, "nid": node_id}
            )
        return node_id, False

    node_id = str(uuid4())
    await db.execute(
        text("""INSERT INTO nodes (id, graph_id, concept_id, label, mastery_score)
               VALUES (:id, :gid, :cid, :label, :ms)"""),
        {"id": node_id, "gid": graph_id, "cid": concept_id, "label": label, "ms": mastery}
    )
    return node_id, True


async def edge_exists(db, graph_id: str, src: str, tgt: str, relation: str):
    result = await db.execute(
        text("""SELECT 1 FROM edges
                WHERE graph_id = :gid AND source_node_id = :src
                  AND target_node_id = :tgt AND relation = :rel"""),
        {"gid": graph_id, "src": src, "tgt": tgt, "rel": relation}
    )
    return result.first() is not None


async def any_edge_between(db, graph_id: str, src: str, tgt: str):
    """两节点间是否已存在任意关系边（用于避免同源重复边）"""
    result = await db.execute(
        text("""SELECT 1 FROM edges
                WHERE graph_id = :gid
                  AND ((source_node_id = :src AND target_node_id = :tgt)
                       OR (source_node_id = :tgt AND target_node_id = :src))"""),
        {"gid": graph_id, "src": src, "tgt": tgt}
    )
    return result.first() is not None


async def ensure_edge(db, graph_id: str, src: str, tgt: str, relation: str, label: str = ""):
    """创建边（去重），返回 edge_id 或 None"""
    if src == tgt:
        return None
    if await edge_exists(db, graph_id, src, tgt, relation):
        return None
    edge_id = str(uuid4())
    await db.execute(
        text("""INSERT INTO edges (id, graph_id, source_node_id, target_node_id, relation, label, weight)
               VALUES (:id, :gid, :src, :tgt, :rel, :lbl, 1.0)"""),
        {"id": edge_id, "gid": graph_id, "src": src, "tgt": tgt,
         "rel": relation, "lbl": label or relation}
    )
    return edge_id


async def _existing_nodes(db, graph_id: str, exclude_ids=()):
    result = await db.execute(
        text("SELECT id, label FROM nodes WHERE graph_id = :gid"),
        {"gid": graph_id}
    )
    return [{"id": row[0], "label": row[1]}
            for row in result.fetchall() if row[0] not in exclude_ids]


async def mount_node(db, graph_id: str, node_id: str, label: str, top_k: int = 2, threshold: float = 0.45):
    """把节点挂载到图谱中最相似的已有节点（related 边）。
    优先用 embedding 相似度，模型不可用时回退到文本相似度。
    返回挂载结果列表 [{node_id, label, score, edge_id}]"""
    candidates = await _existing_nodes(db, graph_id, exclude_ids={node_id})
    if not candidates:
        return []

    scores = []
    try:
        from app.services.embedding_service import get_embedding_service
        embedding_service = get_embedding_service()
        # 模型未加载时 generate_embeddings_batch 会静默返回随机向量，
        # 这里显式检测，走文本相似度回退，避免随机挂载
        if getattr(embedding_service, "_model", None) is not None:
            texts = [label] + [c["label"] for c in candidates]
            vectors = embedding_service.generate_embeddings_batch(texts)
            if len(vectors) == len(texts):
                import numpy as np
                qv = np.array(vectors[0])
                cvs = np.array(vectors[1:])
                norms = np.linalg.norm(cvs, axis=1) * np.linalg.norm(qv)
                sims = (cvs @ qv) / np.maximum(norms, 1e-9)
                for c, s in zip(candidates, sims):
                    scores.append({"node_id": c["id"], "label": c["label"], "score": float(s)})
    except Exception as e:
        print(f"[graph_mount] embedding unavailable, fallback to text similarity: {e}")

    if not scores:
        for c in candidates:
            scores.append({
                "node_id": c["id"], "label": c["label"],
                "score": difflib.SequenceMatcher(None, label, c["label"]).ratio()
            })

    scores.sort(key=lambda x: -x["score"])

    # 保证连通：最相似节点即使低于阈值也挂载（best effort），其余需过阈值
    mounted = []
    for i, item in enumerate(scores[:top_k]):
        if i > 0 and item["score"] < threshold:
            continue
        # 两节点间已有任何边（如虚拟图投影的 parent/prerequisite）时跳过模糊挂载
        if await any_edge_between(db, graph_id, node_id, item["node_id"]):
            continue
        edge_id = await ensure_edge(db, graph_id, node_id, item["node_id"], "related", label="相关")
        mounted.append({**item, "edge_id": edge_id})
    return mounted


async def sync_virtual_graph_to_real(db, graph_id: str, vg_id: str):
    """把整个虚拟图同步到真实图谱：
    1. 补全虚拟图所有节点到真实图（label级创建，无concept_id，mastery保持0）
    2. 投影虚拟图内部所有边
    返回 {"nodes": [...], "edges": [...]}"""
    nodes_result = await db.execute(
        text("SELECT id, label FROM virtual_graph_nodes WHERE virtual_graph_id = :vgid"),
        {"vgid": vg_id}
    )
    vnodes = nodes_result.fetchall()

    synced_nodes = []
    for vid, label in vnodes:
        node_id, _ = await merge_or_create_node(db, graph_id, label)
        await db.execute(
            text("UPDATE virtual_graph_nodes SET node_id = :nid WHERE id = :vnid"),
            {"nid": node_id, "vnid": vid}
        )
        synced_nodes.append({"vnode_id": vid, "label": label, "node_id": node_id})

    edges = await project_virtual_graph_edges(db, graph_id, vg_id=vg_id)
    return {"nodes": synced_nodes, "edges": edges}


async def _resolve_real_node_id(db, graph_id: str, vnode_id: str, vnode_map: dict):
    """解析虚拟图节点对应的真实节点id：优先 vnode.node_id，否则按label匹配已有节点并回填"""
    info = vnode_map.get(vnode_id)
    if not info:
        return None
    real_node_id, label = info
    if real_node_id:
        return real_node_id
    real = await find_node_by_label(db, graph_id, label)
    if real:
        await db.execute(
            text("UPDATE virtual_graph_nodes SET node_id = :nid WHERE id = :vnid"),
            {"nid": real, "vnid": vnode_id}
        )
        return real
    return None


async def project_virtual_graph_edges(db, graph_id: str, vnode_id: str = None, vg_id: str = None):
    """把虚拟图内部的 vnode→vnode 边投影成真实图谱边（只投影两端都已在真实图存在的边）。
    通过 vnode_id 或 vg_id 定位虚拟图。返回投影的边列表。"""
    if not vg_id:
        vg_result = await db.execute(
            text("SELECT virtual_graph_id FROM virtual_graph_nodes WHERE id = :vid"),
            {"vid": vnode_id}
        )
        vg_row = vg_result.first()
        if not vg_row:
            return []
        vg_id = vg_row[0]

    nodes_result = await db.execute(
        text("SELECT id, node_id, label FROM virtual_graph_nodes WHERE virtual_graph_id = :vgid"),
        {"vgid": vg_id}
    )
    vnode_map = {r[0]: (r[1], r[2]) for r in nodes_result.fetchall()}
    if not vnode_map:
        return []

    edges_result = await db.execute(
        text("SELECT source_vnode_id, target_vnode_id, relation FROM virtual_graph_edges WHERE virtual_graph_id = :vgid"),
        {"vgid": vg_id}
    )
    projected = []
    for row in edges_result.fetchall():
        src_vnode_id, tgt_vnode_id, relation = row
        src_real = await _resolve_real_node_id(db, graph_id, src_vnode_id, vnode_map)
        tgt_real = await _resolve_real_node_id(db, graph_id, tgt_vnode_id, vnode_map)
        if not src_real or not tgt_real:
            continue
        mapped_relation = VG_EDGE_RELATION_MAP.get(relation, "related")
        edge_id = await ensure_edge(db, graph_id, src_real, tgt_real, mapped_relation)
        if edge_id:
            projected.append({
                "source": vnode_map[src_vnode_id][1],
                "target": vnode_map[tgt_vnode_id][1],
                "relation": mapped_relation,
            })
    return projected
