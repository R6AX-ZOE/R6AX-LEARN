from fastapi import APIRouter, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse
from uuid import uuid4
from sqlalchemy import text
import json

from app.core.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.input import Directory, Note
from app.models.teaching import TeachingSession, Concept

router = APIRouter()

@router.get("/directories/{project_id}")
async def list_directories(project_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    dirs = await db.execute(text("SELECT * FROM directories WHERE project_id = :project_id ORDER BY order_index"), {"project_id": project_id})
    dirs = dirs.fetchall()
    
    if not dirs:
        return HTMLResponse("<div class='text-white/40 text-sm italic'>暂无目录</div>")
    
    html = ""
    for directory in dirs:
        html += f"""
        <div data-directory-id="{directory.id}" data-directory-name="{directory.name}" class="directory-item flex items-center justify-between p-3 rounded-lg hover:bg-white/10 transition-colors cursor-pointer">
            <span class="text-white/80 text-sm">{directory.name}</span>
            <div class="flex items-center space-x-2">
                <span class="text-white/40 text-xs">→</span>
                <button class="delete-dir-btn text-red-400 text-xs hover:text-red-300 px-2 py-1" data-directory-id="{directory.id}">删除</button>
            </div>
        </div>
        """
    
    return HTMLResponse(html)

@router.delete("/directories/{directory_id}")
async def delete_directory(directory_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    result = await db.execute(text("SELECT project_id FROM directories WHERE id = :directory_id"), {"directory_id": directory_id})
    dir_info = result.first()

    if not dir_info:
        raise HTTPException(status_code=404, detail="目录不存在")

    project_id = dir_info.project_id

    # 删除关联的笔记
    await db.execute(text("DELETE FROM notes WHERE directory_id = :directory_id"), {"directory_id": directory_id})

    # 删除关联的图谱及其节点和边
    graph_result = await db.execute(text("SELECT id FROM graphs WHERE directory_id = :directory_id"), {"directory_id": directory_id})
    graph_row = graph_result.first()
    if graph_row:
        graph_id = graph_row[0]
        await db.execute(text("DELETE FROM edges WHERE graph_id = :graph_id"), {"graph_id": graph_id})
        await db.execute(text("DELETE FROM nodes WHERE graph_id = :graph_id"), {"graph_id": graph_id})
        await db.execute(text("DELETE FROM graphs WHERE id = :graph_id"), {"graph_id": graph_id})

    # 删除目录
    await db.execute(text("DELETE FROM directories WHERE id = :directory_id"), {"directory_id": directory_id})
    await db.commit()
    
    dirs = await db.execute(text("SELECT * FROM directories WHERE project_id = :project_id ORDER BY order_index"), {"project_id": project_id})
    dirs = dirs.fetchall()
    
    if not dirs:
        return HTMLResponse("<div class='text-white/40 text-sm italic'>暂无目录</div>")
    
    html = ""
    for directory in dirs:
        html += f"""
        <div data-directory-id="{directory.id}" data-directory-name="{directory.name}" class="directory-item flex items-center justify-between p-3 rounded-lg hover:bg-white/10 transition-colors cursor-pointer">
            <span class="text-white/80 text-sm">{directory.name}</span>
            <div class="flex items-center space-x-2">
                <span class="text-white/40 text-xs">→</span>
                <button class="delete-dir-btn text-red-400 text-xs hover:text-red-300 px-2 py-1" data-directory-id="{directory.id}" data-project-id="{project_id}">删除</button>
            </div>
        </div>
        """
    
    return HTMLResponse(html)

@router.post("/directories")
async def create_directory(project_id: str = Form(...), parent_id: str = Form(None), name: str = Form(...), description: str = Form(""), current_user: User = Depends(get_current_user), db = Depends(get_db)):
    dir_id = str(uuid4())
    new_dir = Directory(
        id=dir_id,
        project_id=project_id,
        parent_id=parent_id,
        name=name,
        description=description
    )
    db.add(new_dir)

    # 自动创建对应的图谱（Integration Level）
    graph_id = str(uuid4())
    await db.execute(
        text("INSERT INTO graphs (id, project_id, directory_id, name, created_at, updated_at) VALUES (:id, :pid, :did, :name, datetime('now'), datetime('now'))"),
        {"id": graph_id, "pid": project_id, "did": dir_id, "name": name}
    )

    await db.commit()
    await db.refresh(new_dir)
    
    dirs = await db.execute(text("SELECT * FROM directories WHERE project_id = :project_id ORDER BY order_index"), {"project_id": project_id})
    dirs = dirs.fetchall()
    
    html = ""
    for directory in dirs:
        html += f"""
        <div data-directory-id="{directory.id}" data-directory-name="{directory.name}" class="directory-item flex items-center justify-between p-3 rounded-lg hover:bg-white/10 transition-colors cursor-pointer">
            <span class="text-white/80 text-sm">{directory.name}</span>
            <div class="flex items-center space-x-2">
                <span class="text-white/40 text-xs">→</span>
                <button class="delete-dir-btn text-red-400 text-xs hover:text-red-300 px-2 py-1" data-directory-id="{directory.id}">删除</button>
            </div>
        </div>
        """
    
    return HTMLResponse(html)

@router.get("/notes/{directory_id}")
async def list_notes(directory_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    notes = await db.execute(text("SELECT * FROM notes WHERE directory_id = :directory_id ORDER BY created_at"), {"directory_id": directory_id})
    notes = notes.fetchall()
    
    if not notes:
        return HTMLResponse("<div class='text-center text-white/40 py-12'>暂无笔记</div>")
    
    html = ""
    for note in notes:
        # Escape content for data attribute using JSON encoding
        # This properly handles backslashes, newlines, and other special characters
        # ensure_ascii=False preserves Chinese and other Unicode characters
        # Keep the full JSON string format (with quotes) for proper decoding in JavaScript
        # Then escape HTML entities to prevent breaking the HTML attribute
        json_content = json.dumps(note.content, ensure_ascii=False)
        escaped_content = json_content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;')
        html += f"""
        <div class="p-4 bg-white/5 rounded-lg hover:bg-white/10 transition-colors note-card" data-note-id="{note.id}">
            <div class="note-main-content">
                <h3 class="text-white font-medium mb-2">{note.title}</h3>
                <div class="markdown-content text-sm note-content" data-content="{escaped_content}"></div>
                <div class="flex justify-between items-center mt-3">
                    <span class="text-white/40 text-xs">{note.created_at[:16]}</span>
                    <div class="flex space-x-2">
                        <button class="extract-concepts-btn text-green-400 text-xs hover:text-green-300">提取概念</button>
                        <button class="edit-note-btn text-blue-400 text-xs hover:text-blue-300">编辑</button>
                        <button class="delete-note-btn text-red-400 text-xs hover:text-red-300">删除</button>
                    </div>
                </div>
            </div>
            <div id="note-concepts-{note.id}" class="note-concepts-area mt-4"></div>
        </div>
        """
    
    return HTMLResponse(html)

@router.delete("/notes/{note_id}")
async def delete_note(note_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    result = await db.execute(text("SELECT directory_id FROM notes WHERE id = :note_id"), {"note_id": note_id})
    note_info = result.first()
    
    if not note_info:
        return HTMLResponse("<div class='text-center text-red-400 py-12'>笔记不存在</div>")
    
    directory_id = note_info.directory_id
    
    await db.execute(text("DELETE FROM notes WHERE id = :note_id"), {"note_id": note_id})
    await db.commit()
    
    if directory_id:
        notes = await db.execute(text("SELECT * FROM notes WHERE directory_id = :directory_id ORDER BY created_at"), {"directory_id": directory_id})
    else:
        notes = await db.execute(text("SELECT * FROM notes WHERE directory_id IS NULL ORDER BY created_at"))
    notes = notes.fetchall()
    
    if not notes:
        return HTMLResponse("<div class='text-center text-white/40 py-12'>暂无笔记</div>")
    
    html = ""
    for note in notes:
        escaped_content = note.content.replace('"', '&quot;').replace("'", '&#39;')
        html += f"""
        <div class="p-4 bg-white/5 rounded-lg hover:bg-white/10 transition-colors note-card" data-note-id="{note.id}">
            <h3 class="text-white font-medium mb-2">{note.title}</h3>
            <div class="markdown-content text-sm note-content" data-content="{escaped_content}"></div>
            <div class="flex justify-between items-center mt-3">
                <span class="text-white/40 text-xs">{note.created_at[:16]}</span>
                <div class="flex space-x-2">
                    <button class="extract-concepts-btn text-green-400 text-xs hover:text-green-300">提取概念</button>
                    <button class="edit-note-btn text-blue-400 text-xs hover:text-blue-300">编辑</button>
                    <button class="delete-note-btn text-red-400 text-xs hover:text-red-300">删除</button>
                </div>
            </div>
        </div>
        """
    
    return HTMLResponse(html)

@router.put("/notes/{note_id}")
async def update_note(note_id: str, title: str = Form(...), content: str = Form(""), current_user: User = Depends(get_current_user), db = Depends(get_db)):
    result = await db.execute(text("SELECT directory_id FROM notes WHERE id = :note_id"), {"note_id": note_id})
    note_info = result.first()
    
    if not note_info:
        return HTMLResponse("<div class='text-center text-red-400 py-12'>笔记不存在</div>")
    
    directory_id = note_info.directory_id
    
    await db.execute(
        text("UPDATE notes SET title = :title, content = :content WHERE id = :note_id"),
        {"note_id": note_id, "title": title, "content": content}
    )
    await db.commit()
    
    if directory_id:
        notes = await db.execute(text("SELECT * FROM notes WHERE directory_id = :directory_id ORDER BY created_at"), {"directory_id": directory_id})
    else:
        notes = await db.execute(text("SELECT * FROM notes WHERE directory_id IS NULL ORDER BY created_at"))
    notes = notes.fetchall()
    
    if not notes:
        return HTMLResponse("<div class='text-center text-white/40 py-12'>暂无笔记</div>")
    
    html = ""
    for note in notes:
        escaped_content = note.content.replace('"', '&quot;').replace("'", '&#39;')
        html += f"""
        <div class="p-4 bg-white/5 rounded-lg hover:bg-white/10 transition-colors note-card" data-note-id="{note.id}">
            <h3 class="text-white font-medium mb-2">{note.title}</h3>
            <div class="markdown-content text-sm note-content" data-content="{escaped_content}"></div>
            <div class="flex justify-between items-center mt-3">
                <span class="text-white/40 text-xs">{note.created_at[:16]}</span>
                <div class="flex space-x-2">
                    <button class="extract-concepts-btn text-green-400 text-xs hover:text-green-300">提取概念</button>
                    <button class="edit-note-btn text-blue-400 text-xs hover:text-blue-300">编辑</button>
                    <button class="delete-note-btn text-red-400 text-xs hover:text-red-300">删除</button>
                </div>
            </div>
        </div>
        """
    
    return HTMLResponse(html)

@router.post("/notes")
async def create_note(directory_id: str = Form(None), title: str = Form(...), content: str = Form(""), current_user: User = Depends(get_current_user), db = Depends(get_db)):
    new_note = Note(
        id=str(uuid4()),
        directory_id=directory_id,
        title=title,
        content=content
    )
    db.add(new_note)
    await db.commit()
    await db.refresh(new_note)
    
    if directory_id:
        notes = await db.execute(text("SELECT * FROM notes WHERE directory_id = :directory_id ORDER BY created_at"), {"directory_id": directory_id})
    else:
        notes = await db.execute(text("SELECT * FROM notes WHERE directory_id IS NULL ORDER BY created_at"))
    notes = notes.fetchall()
    
    if not notes:
        return HTMLResponse("<div class='text-center text-white/40 py-12'>暂无笔记</div>")
    
    html = ""
    for note in notes:
        # Escape content for data attribute using JSON encoding
        # This properly handles backslashes, newlines, and other special characters
        # ensure_ascii=False preserves Chinese and other Unicode characters
        # Keep the full JSON string format (with quotes) for proper decoding in JavaScript
        # Then escape HTML entities to prevent breaking the HTML attribute
        json_content = json.dumps(note.content, ensure_ascii=False)
        escaped_content = json_content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&#39;')
        html += f"""
        <div class="p-4 bg-white/5 rounded-lg hover:bg-white/10 transition-colors note-card" data-note-id="{note.id}">
            <div class="note-main-content">
                <h3 class="text-white font-medium mb-2">{note.title}</h3>
                <div class="markdown-content text-sm note-content" data-content="{escaped_content}"></div>
                <div class="flex justify-between items-center mt-3">
                    <span class="text-white/40 text-xs">{note.created_at[:16]}</span>
                    <div class="flex space-x-2">
                        <button class="extract-concepts-btn text-green-400 text-xs hover:text-green-300">提取概念</button>
                        <button class="edit-note-btn text-blue-400 text-xs hover:text-blue-300">编辑</button>
                        <button class="delete-note-btn text-red-400 text-xs hover:text-red-300">删除</button>
                    </div>
                </div>
            </div>
            <div id="note-concepts-{note.id}" class="note-concepts-area mt-4"></div>
        </div>
        """
    
    return HTMLResponse(html)

@router.post("/notes/{note_id}/extract-concepts")
async def extract_note_concepts(note_id: str, re_extract: bool = Form(False), current_user: User = Depends(get_current_user), db = Depends(get_db)):
    # 获取笔记信息
    result = await db.execute(text("SELECT title, content, directory_id FROM notes WHERE id = :note_id"), {"note_id": note_id})
    note = result.first()
    
    if not note:
        return HTMLResponse("<div class='text-red-400'>笔记不存在</div>")
    
    # 检查是否已提取过概念
    existing_session = await db.execute(
        text("SELECT id, title FROM teaching_sessions WHERE source_note_id = :note_id"),
        {"note_id": note_id}
    )
    existing_session = existing_session.first()
    
    if existing_session and not re_extract:
        # 已提取过，直接显示已保存的概念
        concepts_result = await db.execute(
            text("SELECT id, name, description FROM concepts WHERE session_id = :session_id"),
            {"session_id": existing_session.id}
        )
        saved_concepts = concepts_result.fetchall()

        # 生成概念卡片HTML
        concepts_html = ""
        for i, concept in enumerate(saved_concepts, 1):
            concepts_html += f"""
            <div class="p-3 border-b border-white/10 last:border-b-0">
                <div class="flex items-start justify-between">
                    <div>
                        <div class="flex items-center space-x-2 mb-1">
                            <span class="text-blue-400 text-sm font-medium">{i}. {concept.name}</span>
                        </div>
                        <p class="text-white/60 text-sm">{concept.description or ''}</p>
                    </div>
                    <input type="checkbox" checked class="concept-checkbox" data-concept-id="{concept.id}">
                </div>
            </div>
            """

        html = f"""
        <div class="space-y-3">
            <div class="flex items-center justify-between mb-4">
                <h3 class="text-white font-medium">已提取的概念</h3>
                <div class="flex space-x-2">
                    <button onclick="reExtractConcepts('{note_id}')" class="btn-secondary text-sm">重新提取</button>
                    <button onclick="collapseConcepts('{note_id}')" class="btn-secondary text-sm">收起</button>
                    <button onclick="startTeaching('{existing_session.id}')" class="btn-primary text-sm">继续教学</button>
                </div>
            </div>
            <p class="text-white/40 text-xs mb-4">此笔记已提取过概念，共 {len(saved_concepts)} 个</p>
            <div id="concepts-list-{note_id}">
                {concepts_html}
            </div>
        </div>
        """

        return HTMLResponse(html)
    
    # 如果需要重新提取，删除旧数据
    if existing_session and re_extract:
        await db.execute(text("DELETE FROM concepts WHERE session_id = :session_id"), {"session_id": existing_session.id})
        await db.execute(text("DELETE FROM teaching_sessions WHERE id = :session_id"), {"session_id": existing_session.id})
        await db.commit()
    
    # 获取项目ID
    dir_result = await db.execute(text("SELECT project_id FROM directories WHERE id = :dir_id"), {"dir_id": note.directory_id})
    dir_info = dir_result.first()
    project_id = dir_info.project_id if dir_info else None

    # 查询项目中已有的概念（排除当前笔记本身的概念，避免重新提取时重复）
    existing_concepts = []
    if project_id:
        # 通过 teaching_sessions 和 concepts 表联查获取项目中的所有概念
        # 排除当前笔记本身的概念，这样重新提取时可以重新提取这个笔记的概念
        concepts_result = await db.execute(
            text("""
                SELECT DISTINCT c.name, c.description
                FROM concepts c
                JOIN teaching_sessions ts ON c.session_id = ts.id
                WHERE ts.project_id = :project_id
                AND ts.source_note_id != :note_id
            """),
            {"project_id": project_id, "note_id": note_id}
        )
        concepts_rows = concepts_result.fetchall()
        existing_concepts = [
            {"name": row.name, "description": row.description}
            for row in concepts_rows
        ]

    # 提取概念
    from app.services.concept_extractor import extract_concepts
    concepts_data = await extract_concepts(note.content, note.title, existing_concepts)
    
    if not concepts_data:
        return HTMLResponse("<div class='text-white/40'>未能提取出概念</div>")
    
    # 创建教学会话
    session_id = str(uuid4())
    session = TeachingSession(
        id=session_id,
        project_id=project_id,
        source_note_id=note_id,
        title=f"从「{note.title}」提取的概念",
        status="active"
    )
    db.add(session)
    
    # 保存概念到数据库
    saved_concepts = []
    for concept_data in concepts_data:
        concept_id = str(uuid4())
        concept = Concept(
            id=concept_id,
            session_id=session_id,
            name=concept_data.get("name", ""),
            description=concept_data.get("description", ""),
            status="learning"
        )
        db.add(concept)
        saved_concepts.append({
            "id": concept_id,
            "name": concept_data.get("name", ""),
            "description": concept_data.get("description", ""),
            "key_points": concept_data.get("key_points", [])
        })
    
    await db.commit()

    # 生成概念卡片HTML
    concepts_html = ""
    for i, concept in enumerate(saved_concepts, 1):
        key_points_html = "<br>".join([f"• {point}" for point in concept.get("key_points", [])])
        concepts_html += f"""
        <div class="p-3 border-b border-white/10 last:border-b-0">
            <div class="flex items-start justify-between">
                <div>
                    <div class="flex items-center space-x-2 mb-1">
                        <span class="text-blue-400 text-sm font-medium">{i}. {concept.get('name', '')}</span>
                    </div>
                    <p class="text-white/60 text-sm mb-1">{concept.get('description', '')}</p>
                    <div class="text-white/50 text-xs">
                        {key_points_html}
                    </div>
                </div>
                <input type="checkbox" checked class="concept-checkbox" data-concept-id="{concept.get('id', '')}">
            </div>
        </div>
        """

    # 构建返回HTML
    html = f"""
    <div class="space-y-3">
        <div class="flex items-center justify-between mb-4">
            <h3 class="text-white font-medium">提取的概念</h3>
            <div class="flex space-x-2">
                <button onclick="reExtractConcepts('{note_id}')" class="btn-secondary text-sm">重新提取</button>
                <button onclick="collapseConcepts('{note_id}')" class="btn-secondary text-sm">收起</button>
                <button onclick="startTeaching('{session_id}')" class="btn-primary text-sm">开始教学</button>
            </div>
        </div>
        <p class="text-white/40 text-xs mb-4">已保存到教学会话，共 {len(saved_concepts)} 个概念</p>
        <div id="concepts-list-{note_id}">
            {concepts_html}
        </div>
    </div>
    """

    return HTMLResponse(html)
