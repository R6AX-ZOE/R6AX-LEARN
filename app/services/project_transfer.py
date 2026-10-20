import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text

EXPORT_FORMAT = "r6ax-learn.project"
EXPORT_VERSION = 1

JSON_TEXT_KEYS = {"extra_data", "knowledge_points", "properties", "embedding"}


class ProjectImportError(ValueError):
    def __init__(self, message_key: str):
        super().__init__(message_key)
        self.message_key = message_key


async def _fetch_all(db, sql: str, params: dict) -> list[dict]:
    result = await db.execute(text(sql), params)
    return [dict(row._mapping) for row in result.fetchall()]


async def _table_columns(db, table: str) -> list[str]:
    result = await db.execute(text(f"PRAGMA table_info({table})"))
    return [row[1] for row in result.fetchall()]


def _as_rows(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _old_id(row: dict) -> str | None:
    value = row.get("id")
    if value is None:
        return None
    return str(value)


def _remap(mapping: dict[str, str], value) -> str | None:
    if value is None:
        return None
    return mapping.get(str(value))


async def _insert_row(db, table: str, row: dict, columns: list[str], overrides: dict) -> None:
    data = {key: row.get(key) for key in columns if key in row}
    data.update({key: value for key, value in overrides.items() if key in columns})
    for key in JSON_TEXT_KEYS:
        if key in data and isinstance(data[key], (dict, list)):
            data[key] = json.dumps(data[key], ensure_ascii=False)
    keys = [key for key in data if key in columns]
    if not keys:
        raise ProjectImportError("project.import-invalid")
    column_sql = ", ".join(keys)
    value_sql = ", ".join(f":{key}" for key in keys)
    await db.execute(
        text(f"INSERT INTO {table} ({column_sql}) VALUES ({value_sql})"),
        {key: data[key] for key in keys},
    )


async def export_project_payload(db, project_id: str, user_id: str) -> dict:
    project_rows = await _fetch_all(
        db,
        "SELECT * FROM projects WHERE id = :pid AND user_id = :uid",
        {"pid": project_id, "uid": user_id},
    )
    if not project_rows:
        raise LookupError("project.not-found")

    project = project_rows[0]
    project.pop("user_id", None)

    directories = await _fetch_all(
        db,
        "SELECT * FROM directories WHERE project_id = :pid ORDER BY order_index",
        {"pid": project_id},
    )
    notes = await _fetch_all(
        db,
        """SELECT n.* FROM notes n
           JOIN directories d ON n.directory_id = d.id
           WHERE d.project_id = :pid
           ORDER BY n.created_at""",
        {"pid": project_id},
    )
    teaching_sessions = await _fetch_all(
        db,
        "SELECT * FROM teaching_sessions WHERE project_id = :pid ORDER BY created_at",
        {"pid": project_id},
    )
    messages = await _fetch_all(
        db,
        """SELECT m.* FROM messages m
           JOIN teaching_sessions ts ON m.session_id = ts.id
           WHERE ts.project_id = :pid
           ORDER BY m.created_at""",
        {"pid": project_id},
    )
    concepts = await _fetch_all(
        db,
        """SELECT c.* FROM concepts c
           JOIN teaching_sessions ts ON c.session_id = ts.id
           WHERE ts.project_id = :pid
           ORDER BY c.id""",
        {"pid": project_id},
    )
    misconceptions = await _fetch_all(
        db,
        """SELECT m.* FROM misconceptions m
           JOIN teaching_sessions ts ON m.session_id = ts.id
           WHERE ts.project_id = :pid
           ORDER BY m.id""",
        {"pid": project_id},
    )
    questions = await _fetch_all(
        db,
        """SELECT q.* FROM questions q
           JOIN concepts c ON q.concept_id = c.id
           JOIN teaching_sessions ts ON c.session_id = ts.id
           WHERE ts.project_id = :pid
           ORDER BY q.created_at""",
        {"pid": project_id},
    )
    review_schedules = await _fetch_all(
        db,
        """SELECT rs.* FROM review_schedules rs
           JOIN questions q ON rs.question_id = q.id
           JOIN concepts c ON q.concept_id = c.id
           JOIN teaching_sessions ts ON c.session_id = ts.id
           WHERE ts.project_id = :pid AND rs.user_id = :uid
           ORDER BY rs.id""",
        {"pid": project_id, "uid": user_id},
    )
    review_records = await _fetch_all(
        db,
        """SELECT rr.* FROM review_records rr
           JOIN review_schedules rs ON rr.schedule_id = rs.id
           JOIN questions q ON rs.question_id = q.id
           JOIN concepts c ON q.concept_id = c.id
           JOIN teaching_sessions ts ON c.session_id = ts.id
           WHERE ts.project_id = :pid AND rs.user_id = :uid
           ORDER BY rr.reviewed_at""",
        {"pid": project_id, "uid": user_id},
    )
    practice_sessions = await _fetch_all(
        db,
        """SELECT * FROM practice_sessions
           WHERE project_id = :pid AND user_id = :uid
           ORDER BY created_at""",
        {"pid": project_id, "uid": user_id},
    )
    practice_session_questions = await _fetch_all(
        db,
        """SELECT psq.* FROM practice_session_questions psq
           JOIN practice_sessions ps ON psq.session_id = ps.id
           WHERE ps.project_id = :pid AND ps.user_id = :uid
           ORDER BY psq.order_index""",
        {"pid": project_id, "uid": user_id},
    )
    graphs = await _fetch_all(
        db,
        "SELECT * FROM graphs WHERE project_id = :pid ORDER BY created_at",
        {"pid": project_id},
    )
    nodes = await _fetch_all(
        db,
        """SELECT n.* FROM nodes n
           JOIN graphs g ON n.graph_id = g.id
           WHERE g.project_id = :pid
           ORDER BY n.id""",
        {"pid": project_id},
    )
    edges = await _fetch_all(
        db,
        """SELECT e.* FROM edges e
           JOIN graphs g ON e.graph_id = g.id
           WHERE g.project_id = :pid""",
        {"pid": project_id},
    )
    node_embeddings = await _fetch_all(
        db,
        """SELECT ne.* FROM node_embeddings ne
           JOIN nodes n ON ne.node_id = n.id
           JOIN graphs g ON n.graph_id = g.id
           WHERE g.project_id = :pid""",
        {"pid": project_id},
    )
    virtual_graphs = await _fetch_all(
        db,
        """SELECT vg.* FROM virtual_graphs vg
           JOIN teaching_sessions ts ON vg.session_id = ts.id
           WHERE ts.project_id = :pid
           ORDER BY vg.created_at""",
        {"pid": project_id},
    )
    virtual_graph_nodes = await _fetch_all(
        db,
        """SELECT vgn.* FROM virtual_graph_nodes vgn
           JOIN virtual_graphs vg ON vgn.virtual_graph_id = vg.id
           JOIN teaching_sessions ts ON vg.session_id = ts.id
           WHERE ts.project_id = :pid
           ORDER BY vgn.order_index""",
        {"pid": project_id},
    )
    virtual_graph_edges = await _fetch_all(
        db,
        """SELECT vge.* FROM virtual_graph_edges vge
           JOIN virtual_graphs vg ON vge.virtual_graph_id = vg.id
           JOIN teaching_sessions ts ON vg.session_id = ts.id
           WHERE ts.project_id = :pid""",
        {"pid": project_id},
    )
    virtual_graph_to_node_edges = await _fetch_all(
        db,
        """SELECT vgte.* FROM virtual_graph_to_node_edges vgte
           JOIN virtual_graphs vg ON vgte.virtual_graph_id = vg.id
           JOIN teaching_sessions ts ON vg.session_id = ts.id
           WHERE ts.project_id = :pid""",
        {"pid": project_id},
    )
    virtual_graph_embeddings = await _fetch_all(
        db,
        """SELECT vge.* FROM virtual_graph_embeddings vge
           JOIN virtual_graphs vg ON vge.virtual_graph_id = vg.id
           JOIN teaching_sessions ts ON vg.session_id = ts.id
           WHERE ts.project_id = :pid""",
        {"pid": project_id},
    )

    for row in review_schedules:
        row.pop("user_id", None)
    for row in practice_sessions:
        row.pop("user_id", None)

    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "project": project,
        "directories": directories,
        "notes": notes,
        "teaching_sessions": teaching_sessions,
        "messages": messages,
        "concepts": concepts,
        "misconceptions": misconceptions,
        "questions": questions,
        "review_schedules": review_schedules,
        "review_records": review_records,
        "practice_sessions": practice_sessions,
        "practice_session_questions": practice_session_questions,
        "graphs": graphs,
        "nodes": nodes,
        "edges": edges,
        "node_embeddings": node_embeddings,
        "virtual_graphs": virtual_graphs,
        "virtual_graph_nodes": virtual_graph_nodes,
        "virtual_graph_edges": virtual_graph_edges,
        "virtual_graph_to_node_edges": virtual_graph_to_node_edges,
        "virtual_graph_embeddings": virtual_graph_embeddings,
    }


async def import_project_payload(db, payload: dict, user_id: str) -> str:
    if not isinstance(payload, dict):
        raise ProjectImportError("project.import-invalid")

    payload_format = payload.get("format")
    if payload_format and payload_format != EXPORT_FORMAT:
        raise ProjectImportError("project.import-invalid")
    payload_version = payload.get("version")
    if payload_version is not None and payload_version != EXPORT_VERSION:
        raise ProjectImportError("project.import-invalid")

    project_data = payload.get("project")
    if not isinstance(project_data, dict):
        project_data = payload

    name = str(project_data.get("name") or "").strip()
    if not name:
        raise ProjectImportError("project.import-invalid")

    now = datetime.now(UTC).replace(tzinfo=None)
    new_project_id = str(uuid4())

    project_columns = await _table_columns(db, "projects")
    await _insert_row(db, "projects", project_data, project_columns, {
        "id": new_project_id,
        "user_id": user_id,
        "name": name,
        "description": project_data.get("description") or "",
        "created_at": project_data.get("created_at") or now,
        "updated_at": project_data.get("updated_at") or now,
    })

    directory_rows = _as_rows(payload.get("directories"))
    directory_columns = await _table_columns(db, "directories")
    directory_map: dict[str, str] = {}
    for row in directory_rows:
        old_id = _old_id(row)
        if old_id:
            directory_map[old_id] = str(uuid4())
    for row in directory_rows:
        old_id = _old_id(row)
        if not old_id:
            continue
        await _insert_row(db, "directories", row, directory_columns, {
            "id": directory_map[old_id],
            "project_id": new_project_id,
            "parent_id": None,
        })
    for row in directory_rows:
        old_id = _old_id(row)
        parent_id = _remap(directory_map, row.get("parent_id"))
        if old_id and parent_id:
            await db.execute(
                text("UPDATE directories SET parent_id = :parent_id WHERE id = :id"),
                {"parent_id": parent_id, "id": directory_map[old_id]},
            )

    note_rows = _as_rows(payload.get("notes"))
    note_columns = await _table_columns(db, "notes")
    note_map: dict[str, str] = {}
    for row in note_rows:
        old_id = _old_id(row)
        new_id = str(uuid4())
        if old_id:
            note_map[old_id] = new_id
        await _insert_row(db, "notes", row, note_columns, {
            "id": new_id,
            "directory_id": _remap(directory_map, row.get("directory_id")),
        })

    session_rows = _as_rows(payload.get("teaching_sessions"))
    session_columns = await _table_columns(db, "teaching_sessions")
    session_map: dict[str, str] = {}
    for row in session_rows:
        old_id = _old_id(row)
        if old_id:
            session_map[old_id] = str(uuid4())
    trigger_links: list[tuple[str, str]] = []
    for row in session_rows:
        old_id = _old_id(row)
        if not old_id:
            continue
        trigger_id = row.get("trigger_concept_id")
        await _insert_row(db, "teaching_sessions", row, session_columns, {
            "id": session_map[old_id],
            "project_id": new_project_id,
            "source_note_id": _remap(note_map, row.get("source_note_id")),
            "trigger_concept_id": None,
        })
        if trigger_id:
            trigger_links.append((session_map[old_id], str(trigger_id)))

    message_rows = _as_rows(payload.get("messages"))
    message_columns = await _table_columns(db, "messages")
    message_map: dict[str, str] = {}
    for row in message_rows:
        old_id = _old_id(row)
        if old_id:
            message_map[old_id] = str(uuid4())
    for row in message_rows:
        old_id = _old_id(row)
        new_session_id = _remap(session_map, row.get("session_id"))
        if not old_id or not new_session_id:
            continue
        await _insert_row(db, "messages", row, message_columns, {
            "id": message_map[old_id],
            "session_id": new_session_id,
            "parent_id": _remap(message_map, row.get("parent_id")),
        })

    concept_rows = _as_rows(payload.get("concepts"))
    concept_columns = await _table_columns(db, "concepts")
    concept_map: dict[str, str] = {}
    for row in concept_rows:
        old_id = _old_id(row)
        if old_id:
            concept_map[old_id] = str(uuid4())
    for row in concept_rows:
        old_id = _old_id(row)
        new_session_id = _remap(session_map, row.get("session_id"))
        if not old_id or not new_session_id:
            continue
        await _insert_row(db, "concepts", row, concept_columns, {
            "id": concept_map[old_id],
            "session_id": new_session_id,
        })

    for new_session_id, old_concept_id in trigger_links:
        new_concept_id = concept_map.get(old_concept_id)
        if new_concept_id:
            await db.execute(
                text("UPDATE teaching_sessions SET trigger_concept_id = :cid WHERE id = :sid"),
                {"cid": new_concept_id, "sid": new_session_id},
            )

    misconception_rows = _as_rows(payload.get("misconceptions"))
    misconception_columns = await _table_columns(db, "misconceptions")
    for row in misconception_rows:
        old_id = _old_id(row)
        new_session_id = _remap(session_map, row.get("session_id"))
        if not old_id or not new_session_id:
            continue
        await _insert_row(db, "misconceptions", row, misconception_columns, {
            "id": str(uuid4()),
            "session_id": new_session_id,
        })

    question_rows = _as_rows(payload.get("questions"))
    question_columns = await _table_columns(db, "questions")
    question_map: dict[str, str] = {}
    for row in question_rows:
        old_id = _old_id(row)
        if old_id:
            question_map[old_id] = str(uuid4())
    for row in question_rows:
        old_id = _old_id(row)
        new_concept_id = _remap(concept_map, row.get("concept_id"))
        if not old_id or not new_concept_id:
            continue
        await _insert_row(db, "questions", row, question_columns, {
            "id": question_map[old_id],
            "concept_id": new_concept_id,
        })

    schedule_rows = _as_rows(payload.get("review_schedules"))
    schedule_columns = await _table_columns(db, "review_schedules")
    schedule_map: dict[str, str] = {}
    for row in schedule_rows:
        old_id = _old_id(row)
        new_question_id = _remap(question_map, row.get("question_id"))
        if not old_id or not new_question_id:
            continue
        schedule_map[old_id] = str(uuid4())
        await _insert_row(db, "review_schedules", row, schedule_columns, {
            "id": schedule_map[old_id],
            "user_id": user_id,
            "question_id": new_question_id,
            "next_review_at": row.get("next_review_at") or now,
        })

    record_rows = _as_rows(payload.get("review_records"))
    record_columns = await _table_columns(db, "review_records")
    for row in record_rows:
        old_id = _old_id(row)
        new_schedule_id = _remap(schedule_map, row.get("schedule_id"))
        if not old_id or not new_schedule_id:
            continue
        await _insert_row(db, "review_records", row, record_columns, {
            "id": str(uuid4()),
            "schedule_id": new_schedule_id,
        })

    practice_rows = _as_rows(payload.get("practice_sessions"))
    practice_columns = await _table_columns(db, "practice_sessions")
    practice_map: dict[str, str] = {}
    for row in practice_rows:
        old_id = _old_id(row)
        if not old_id:
            continue
        practice_map[old_id] = str(uuid4())
        await _insert_row(db, "practice_sessions", row, practice_columns, {
            "id": practice_map[old_id],
            "user_id": user_id,
            "project_id": new_project_id,
        })

    practice_question_rows = _as_rows(payload.get("practice_session_questions"))
    practice_question_columns = await _table_columns(db, "practice_session_questions")
    for row in practice_question_rows:
        old_id = _old_id(row)
        new_session_id = _remap(practice_map, row.get("session_id"))
        new_question_id = _remap(question_map, row.get("question_id"))
        if not old_id or not new_session_id or not new_question_id:
            continue
        await _insert_row(db, "practice_session_questions", row, practice_question_columns, {
            "id": str(uuid4()),
            "session_id": new_session_id,
            "question_id": new_question_id,
        })

    graph_rows = _as_rows(payload.get("graphs"))
    graph_columns = await _table_columns(db, "graphs")
    graph_map: dict[str, str] = {}
    for row in graph_rows:
        old_id = _old_id(row)
        if not old_id:
            continue
        graph_map[old_id] = str(uuid4())
        await _insert_row(db, "graphs", row, graph_columns, {
            "id": graph_map[old_id],
            "project_id": new_project_id,
            "directory_id": _remap(directory_map, row.get("directory_id")),
        })

    node_rows = _as_rows(payload.get("nodes"))
    node_columns = await _table_columns(db, "nodes")
    node_map: dict[str, str] = {}
    for row in node_rows:
        old_id = _old_id(row)
        new_graph_id = _remap(graph_map, row.get("graph_id"))
        if not old_id or not new_graph_id:
            continue
        node_map[old_id] = str(uuid4())
        await _insert_row(db, "nodes", row, node_columns, {
            "id": node_map[old_id],
            "graph_id": new_graph_id,
            "concept_id": _remap(concept_map, row.get("concept_id")),
            "label": row.get("label") or "",
        })

    edge_rows = _as_rows(payload.get("edges"))
    edge_columns = await _table_columns(db, "edges")
    for row in edge_rows:
        old_id = _old_id(row)
        new_graph_id = _remap(graph_map, row.get("graph_id"))
        new_source_id = _remap(node_map, row.get("source_node_id"))
        new_target_id = _remap(node_map, row.get("target_node_id"))
        if not old_id or not new_graph_id or not new_source_id or not new_target_id:
            continue
        await _insert_row(db, "edges", row, edge_columns, {
            "id": str(uuid4()),
            "graph_id": new_graph_id,
            "source_node_id": new_source_id,
            "target_node_id": new_target_id,
            "relation": row.get("relation") or "related",
        })

    node_embedding_rows = _as_rows(payload.get("node_embeddings"))
    node_embedding_columns = await _table_columns(db, "node_embeddings")
    for row in node_embedding_rows:
        old_id = _old_id(row)
        new_node_id = _remap(node_map, row.get("node_id"))
        if not old_id or not new_node_id:
            continue
        await _insert_row(db, "node_embeddings", row, node_embedding_columns, {
            "id": str(uuid4()),
            "node_id": new_node_id,
        })

    virtual_graph_rows = _as_rows(payload.get("virtual_graphs"))
    virtual_graph_columns = await _table_columns(db, "virtual_graphs")
    virtual_graph_map: dict[str, str] = {}
    for row in virtual_graph_rows:
        old_id = _old_id(row)
        new_session_id = _remap(session_map, row.get("session_id"))
        if not old_id or not new_session_id:
            continue
        virtual_graph_map[old_id] = str(uuid4())
        await _insert_row(db, "virtual_graphs", row, virtual_graph_columns, {
            "id": virtual_graph_map[old_id],
            "session_id": new_session_id,
            "graph_id": _remap(graph_map, row.get("graph_id")),
            "name": row.get("name") or name,
        })

    virtual_node_rows = _as_rows(payload.get("virtual_graph_nodes"))
    virtual_node_columns = await _table_columns(db, "virtual_graph_nodes")
    virtual_node_map: dict[str, str] = {}
    for row in virtual_node_rows:
        old_id = _old_id(row)
        new_virtual_graph_id = _remap(virtual_graph_map, row.get("virtual_graph_id"))
        if not old_id or not new_virtual_graph_id:
            continue
        virtual_node_map[old_id] = str(uuid4())
        await _insert_row(db, "virtual_graph_nodes", row, virtual_node_columns, {
            "id": virtual_node_map[old_id],
            "virtual_graph_id": new_virtual_graph_id,
            "node_id": _remap(node_map, row.get("node_id")),
            "label": row.get("label") or "",
        })

    virtual_edge_rows = _as_rows(payload.get("virtual_graph_edges"))
    virtual_edge_columns = await _table_columns(db, "virtual_graph_edges")
    for row in virtual_edge_rows:
        old_id = _old_id(row)
        new_virtual_graph_id = _remap(virtual_graph_map, row.get("virtual_graph_id"))
        new_source_id = _remap(virtual_node_map, row.get("source_vnode_id"))
        new_target_id = _remap(virtual_node_map, row.get("target_vnode_id"))
        if not old_id or not new_virtual_graph_id or not new_source_id or not new_target_id:
            continue
        await _insert_row(db, "virtual_graph_edges", row, virtual_edge_columns, {
            "id": str(uuid4()),
            "virtual_graph_id": new_virtual_graph_id,
            "source_vnode_id": new_source_id,
            "target_vnode_id": new_target_id,
            "relation": row.get("relation") or "related",
        })

    to_node_edge_rows = _as_rows(payload.get("virtual_graph_to_node_edges"))
    to_node_edge_columns = await _table_columns(db, "virtual_graph_to_node_edges")
    for row in to_node_edge_rows:
        old_id = _old_id(row)
        new_virtual_graph_id = _remap(virtual_graph_map, row.get("virtual_graph_id"))
        new_node_id = _remap(node_map, row.get("node_id"))
        if not old_id or not new_virtual_graph_id or not new_node_id:
            continue
        await _insert_row(db, "virtual_graph_to_node_edges", row, to_node_edge_columns, {
            "id": str(uuid4()),
            "virtual_graph_id": new_virtual_graph_id,
            "node_id": new_node_id,
            "relation_type": row.get("relation_type") or "references",
        })

    virtual_embedding_rows = _as_rows(payload.get("virtual_graph_embeddings"))
    virtual_embedding_columns = await _table_columns(db, "virtual_graph_embeddings")
    for row in virtual_embedding_rows:
        old_id = _old_id(row)
        new_virtual_graph_id = _remap(virtual_graph_map, row.get("virtual_graph_id"))
        if not old_id or not new_virtual_graph_id:
            continue
        await _insert_row(db, "virtual_graph_embeddings", row, virtual_embedding_columns, {
            "id": str(uuid4()),
            "virtual_graph_id": new_virtual_graph_id,
        })

    return new_project_id
