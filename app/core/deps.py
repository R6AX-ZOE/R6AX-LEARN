from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from fastapi.requests import Request
from sqlalchemy import text

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login", auto_error=False)

async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db = Depends(get_db)
) -> Optional[User]:
    if not token:
        token = request.cookies.get("access_token")
    
    if not token:
        return None
    
    payload = decode_access_token(token)
    if payload is None:
        return None
    
    username: str = payload.get("sub")
    if username is None:
        return None
    
    user = await db.get(User, username)
    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user

async def _require(db, sql: str, params: dict, detail: str) -> None:
    """执行归属校验 SQL，不满足时抛 404（不泄露资源存在性）。"""
    row = await db.execute(text(sql), params)
    if not row.first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)

async def require_project(db, project_id: str, user_id: str) -> None:
    await _require(db,
        "SELECT 1 FROM projects WHERE id = :pid AND user_id = :uid",
        {"pid": project_id, "uid": user_id}, "Project not found")

async def require_session(db, session_id: str, user_id: str) -> None:
    """教学会话归属校验：session -> project -> user"""
    await _require(db,
        """SELECT 1 FROM teaching_sessions ts
           JOIN projects p ON ts.project_id = p.id
           WHERE ts.id = :sid AND p.user_id = :uid""",
        {"sid": session_id, "uid": user_id}, "Session not found")

async def require_graph(db, graph_id: str, user_id: str) -> None:
    """图谱归属校验：graph -> project -> user"""
    await _require(db,
        """SELECT 1 FROM graphs g
           JOIN projects p ON g.project_id = p.id
           WHERE g.id = :gid AND p.user_id = :uid""",
        {"gid": graph_id, "uid": user_id}, "Graph not found")

async def require_node(db, node_id: str, user_id: str) -> None:
    """图谱节点归属校验：node -> graph -> project -> user"""
    await _require(db,
        """SELECT 1 FROM nodes n
           JOIN graphs g ON n.graph_id = g.id
           JOIN projects p ON g.project_id = p.id
           WHERE n.id = :nid AND p.user_id = :uid""",
        {"nid": node_id, "uid": user_id}, "Node not found")

async def require_edge(db, edge_id: str, user_id: str) -> None:
    """图谱边归属校验：edge -> graph -> project -> user"""
    await _require(db,
        """SELECT 1 FROM edges e
           JOIN graphs g ON e.graph_id = g.id
           JOIN projects p ON g.project_id = p.id
           WHERE e.id = :eid AND p.user_id = :uid""",
        {"eid": edge_id, "uid": user_id}, "Edge not found")

async def require_virtual_graph(db, vg_id: str, user_id: str) -> None:
    """虚拟图归属校验：virtual_graph -> session -> project -> user"""
    await _require(db,
        """SELECT 1 FROM virtual_graphs vg
           JOIN teaching_sessions ts ON vg.session_id = ts.id
           JOIN projects p ON ts.project_id = p.id
           WHERE vg.id = :vgid AND p.user_id = :uid""",
        {"vgid": vg_id, "uid": user_id}, "Virtual graph not found")

async def require_virtual_node(db, vnode_id: str, user_id: str) -> None:
    """虚拟图节点归属校验：vnode -> virtual_graph -> session -> project -> user"""
    await _require(db,
        """SELECT 1 FROM virtual_graph_nodes vgn
           JOIN virtual_graphs vg ON vgn.virtual_graph_id = vg.id
           JOIN teaching_sessions ts ON vg.session_id = ts.id
           JOIN projects p ON ts.project_id = p.id
           WHERE vgn.id = :vnid AND p.user_id = :uid""",
        {"vnid": vnode_id, "uid": user_id}, "Virtual graph node not found")

async def require_directory(db, directory_id: str, user_id: str) -> None:
    """目录归属校验：directory -> project -> user"""
    await _require(db,
        """SELECT 1 FROM directories d
           JOIN projects p ON d.project_id = p.id
           WHERE d.id = :did AND p.user_id = :uid""",
        {"did": directory_id, "uid": user_id}, "Directory not found")

async def require_note(db, note_id: str, user_id: str) -> None:
    """笔记归属校验：note -> directory -> project -> user"""
    await _require(db,
        """SELECT 1 FROM notes n
           JOIN directories d ON n.directory_id = d.id
           JOIN projects p ON d.project_id = p.id
           WHERE n.id = :nid AND p.user_id = :uid""",
        {"nid": note_id, "uid": user_id}, "Note not found")
