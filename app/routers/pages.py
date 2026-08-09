from fastapi import APIRouter, Depends, HTTPException, Request, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm

from datetime import date as _date, datetime, timedelta
import json
import secrets
from uuid import uuid4

from sqlalchemy import text

from app.config import settings
from app.core.database import get_db
from app.core.security import verify_password, create_access_token
from app.core.deps import get_current_user
from app.models.user import User
from app.models.input import Project
from app.schemas.project import ProjectCreate

from app.i18n.i18n import t, set_locale, get_current_locale

from jinja2 import Environment, FileSystemLoader

router = APIRouter()

CSRF_COOKIE = "csrf_token"

def _csrf_cookie_kwargs() -> dict:
    return {
        "httponly": False,
        "samesite": "lax",
        "secure": not settings.DEBUG,
        "path": "/",
    }

jinja_env = Environment(
    loader=FileSystemLoader("app/templates"),
    autoescape=True,
    cache_size=0
)
jinja_env.globals['t'] = t

@router.get("/", response_class=HTMLResponse)
async def home(request: Request, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    projects = await db.execute(text("SELECT * FROM projects WHERE user_id = :user_id"), {"user_id": current_user.id})
    projects = projects.fetchall()
    
    template = jinja_env.get_template("pages/home.html")
    html_content = template.render(request=request, user=current_user, projects=projects)
    return HTMLResponse(content=html_content)

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, locale: str = None):
    if locale:
        set_locale(locale)

    csrf_token = secrets.token_urlsafe(32)
    response = HTMLResponse(content=jinja_env.get_template("auth/login.html").render(
        request=request, error=None, csrf_token=csrf_token))
    response.set_cookie(key=CSRF_COOKIE, value=csrf_token, **_csrf_cookie_kwargs())
    if locale:
        response.set_cookie(key="locale", value=locale)
    return response

@router.post("/login")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db = Depends(get_db)):
    user = await db.execute(text("SELECT * FROM users WHERE username = :username"), {"username": form_data.username})
    user = user.first()
    
    if not user or not verify_password(form_data.password, user.password_hash):
        csrf_token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
        html_content = jinja_env.get_template("auth/login.html").render(
            request=request, error=t("error.login.failed"), csrf_token=csrf_token)
        response = HTMLResponse(content=html_content, status_code=401)
        if CSRF_COOKIE not in request.cookies:
            response.set_cookie(key=CSRF_COOKIE, value=csrf_token, **_csrf_cookie_kwargs())
        return response
    
    access_token = create_access_token(data={"sub": user.username})
    
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(key="access_token", value=access_token, httponly=True,
                        samesite="lax", secure=not settings.DEBUG, path="/")
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="access_token")
    return response

@router.get("/projects", response_class=HTMLResponse)
async def project_list(request: Request, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    projects = await db.execute(text("SELECT * FROM projects WHERE user_id = :user_id ORDER BY created_at DESC"), {"user_id": current_user.id})
    projects = projects.fetchall()
    
    csrf_token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
    template = jinja_env.get_template("pages/project_list.html")
    html_content = template.render(request=request, user=current_user, projects=projects, csrf_token=csrf_token)
    response = HTMLResponse(content=html_content)
    if CSRF_COOKIE not in request.cookies:
        response.set_cookie(key=CSRF_COOKIE, value=csrf_token, **_csrf_cookie_kwargs())
    return response

@router.post("/projects")
async def create_project(request: Request, name: str = Form(...), description: str = Form(""), current_user: User = Depends(get_current_user), db = Depends(get_db)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    from uuid import uuid4
    new_project = Project(
        id=str(uuid4()),
        user_id=current_user.id,
        name=name,
        description=description
    )
    db.add(new_project)
    await db.commit()
    
    return RedirectResponse(url="/projects", status_code=status.HTTP_302_FOUND)

@router.post("/projects/delete")
async def delete_project(request: Request, project_id: str = Form(...), current_user: User = Depends(get_current_user), db = Depends(get_db)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    await db.execute(text("DELETE FROM projects WHERE id = :project_id AND user_id = :user_id"),
                     {"project_id": project_id, "user_id": current_user.id})
    await db.commit()
    
    return RedirectResponse(url="/projects", status_code=status.HTTP_302_FOUND)

@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    project = await db.execute(text("SELECT * FROM projects WHERE id = :project_id AND user_id = :user_id"), 
                              {"project_id": project_id, "user_id": current_user.id})
    project = project.first()
    
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    # 目录（用于笔记组件绑定选项，按最近笔记活动排序）
    dirs_result = await db.execute(
        text("""SELECT d.id, d.name, COUNT(n.id) AS note_count, MAX(n.updated_at) AS last_note
                FROM directories d LEFT JOIN notes n ON n.directory_id = d.id
                WHERE d.project_id = :pid
                GROUP BY d.id
                ORDER BY d.order_index"""),
        {"pid": project_id}
    )
    all_directories = [dict(row._mapping) for row in dirs_result.fetchall()]
    
    # 笔记组件（1~3 个）：优先最近有笔记活动的目录，否则取最新目录
    active_dirs = [d for d in all_directories if d.get("last_note")]
    active_dirs.sort(key=lambda d: d["last_note"], reverse=True)
    note_widgets = (active_dirs or all_directories)[:3]
    
    # 教 AI 以复习组件：全部未完成的 session
    ts_result = await db.execute(
        text("SELECT id, title, created_at FROM teaching_sessions WHERE project_id = :pid AND status = 'active' ORDER BY created_at DESC"),
        {"pid": project_id}
    )
    teaching_widgets = [dict(row._mapping) for row in ts_result.fetchall()]
    
    # 继续练习组件：全部未完成的 session（含进度）
    ps_result = await db.execute(
        text("""SELECT ps.id, ps.status, ps.created_at,
                       (SELECT COUNT(*) FROM practice_session_questions WHERE session_id = ps.id) AS q_count,
                       (SELECT COUNT(*) FROM practice_session_questions WHERE session_id = ps.id AND answered_at IS NOT NULL) AS answered_count
                FROM practice_sessions ps
                WHERE ps.user_id = :uid AND ps.project_id = :pid AND ps.status = 'active'
                ORDER BY ps.created_at DESC"""),
        {"uid": current_user.id, "pid": project_id}
    )
    practice_widgets = [dict(row._mapping) for row in ps_result.fetchall()]
    
    # 连胜组件：项目内连续有学习活动（练习作答 / 教学消息 / 笔记）的天数
    act_result = await db.execute(
        text("""SELECT DISTINCT date(answered_at) FROM practice_session_questions
                WHERE answered_at IS NOT NULL
                  AND session_id IN (SELECT id FROM practice_sessions WHERE user_id = :uid AND project_id = :pid)
                UNION
                SELECT DISTINCT date(created_at) FROM messages
                WHERE role = 'user'
                  AND session_id IN (SELECT id FROM teaching_sessions WHERE project_id = :pid)
                UNION
                SELECT DISTINCT date(created_at) FROM notes
                WHERE directory_id IN (SELECT id FROM directories WHERE project_id = :pid)"""),
        {"uid": current_user.id, "pid": project_id}
    )
    active_days = {_date.fromisoformat(row[0]) for row in act_result.fetchall()}
    cursor = datetime.utcnow().date()
    if cursor not in active_days:
        cursor -= timedelta(days=1)
    streak_days = 0
    while cursor in active_days:
        streak_days += 1
        cursor -= timedelta(days=1)
    
    # 新练习组件默认主题：最近一个概念名
    topic_result = await db.execute(
        text("""SELECT c.name FROM concepts c
                JOIN teaching_sessions ts ON c.session_id = ts.id
                WHERE ts.project_id = :pid
                ORDER BY ts.created_at DESC, c.rowid DESC LIMIT 1"""),
        {"pid": project_id}
    )
    topic_row = topic_result.first()
    default_topic = topic_row[0] if topic_row else project.name
    
    directories_json = json.dumps(
        [{"id": d["id"], "name": d["name"]} for d in all_directories],
        ensure_ascii=False
    )
    
    template = jinja_env.get_template("pages/project_detail.html")
    html_content = template.render(
        request=request,
        user=current_user,
        project=project,
        note_widgets=note_widgets,
        teaching_widgets=teaching_widgets,
        practice_widgets=practice_widgets,
        streak_days=streak_days,
        default_topic=default_topic,
        directories_json=directories_json
    )
    return HTMLResponse(content=html_content)

@router.get("/input/{project_id}", response_class=HTMLResponse)
async def input_page(request: Request, project_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    project = await db.execute(text("SELECT * FROM projects WHERE id = :project_id AND user_id = :user_id"), 
                              {"project_id": project_id, "user_id": current_user.id})
    project = project.first()
    
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    template = jinja_env.get_template("input_level/note_editor.html")
    html_content = template.render(request=request, user=current_user, project=project, current_dir=None)
    return HTMLResponse(content=html_content)

@router.get("/teaching/{project_id}", response_class=HTMLResponse)
async def teaching_page(request: Request, project_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    project_result = await db.execute(text("SELECT * FROM projects WHERE id = :project_id AND user_id = :user_id"),
                              {"project_id": project_id, "user_id": current_user.id})
    project_row = project_result.first()

    if not project_row:
        raise HTTPException(status_code=404, detail="项目不存在")

    project = dict(project_row._mapping)

    sessions_result = await db.execute(text("SELECT * FROM teaching_sessions WHERE project_id = :project_id ORDER BY created_at DESC"),
                               {"project_id": project_id})
    sessions = [dict(row._mapping) for row in sessions_result.fetchall()]

    template = jinja_env.get_template("teaching/session_list.html")
    html_content = template.render(request=request, user=current_user, project=project, sessions=sessions)
    return HTMLResponse(content=html_content)

@router.get("/practice/{project_id}", response_class=HTMLResponse)
async def practice_page(request: Request, project_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    project_result = await db.execute(text("SELECT * FROM projects WHERE id = :project_id AND user_id = :user_id"),
                              {"project_id": project_id, "user_id": current_user.id})
    project_row = project_result.first()

    if not project_row:
        raise HTTPException(status_code=404, detail="项目不存在")

    project = dict(project_row._mapping)

    # 习题会话列表：未完成（active）与已完成（completed）
    sessions_result = await db.execute(
        text("""SELECT ps.*,
                       (SELECT COUNT(*) FROM practice_session_questions WHERE session_id = ps.id) AS q_count,
                       (SELECT COUNT(*) FROM practice_session_questions WHERE session_id = ps.id AND answered_at IS NOT NULL) AS answered_count,
                       (SELECT AVG(score) FROM practice_session_questions WHERE session_id = ps.id AND answered_at IS NOT NULL) AS avg_score
                FROM practice_sessions ps
                WHERE ps.user_id = :uid AND ps.project_id = :pid
                ORDER BY ps.created_at DESC"""),
        {"uid": current_user.id, "pid": project_id}
    )
    all_sessions = [dict(row._mapping) for row in sessions_result.fetchall()]
    active_sessions = [s for s in all_sessions if s.get("status") == "active"]
    completed_sessions = [s for s in all_sessions if s.get("status") == "completed"]

    # F-16：错题触发的 Teaching 会话（未归档）→ 首页横幅提醒
    trigger_result = await db.execute(
        text("""SELECT ts.id, ts.title, ts.created_at, c.name AS concept_name
                FROM teaching_sessions ts
                LEFT JOIN concepts c ON ts.trigger_concept_id = c.id
                WHERE ts.project_id = :pid AND ts.trigger_concept_id IS NOT NULL AND ts.status = 'active'
                ORDER BY ts.created_at DESC"""),
        {"pid": project_id}
    )
    trigger_sessions = [dict(row._mapping) for row in trigger_result.fetchall()]

    template = jinja_env.get_template("practice/today.html")
    html_content = template.render(
        request=request,
        user=current_user,
        project=project,
        active_sessions=active_sessions,
        completed_sessions=completed_sessions,
        trigger_sessions=trigger_sessions
    )
    return HTMLResponse(content=html_content)

@router.get("/practice/{project_id}/bank", response_class=HTMLResponse)
async def practice_bank_page(request: Request, project_id: str, q: str = "", current_user: User = Depends(get_current_user), db = Depends(get_db)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    project_result = await db.execute(text("SELECT * FROM projects WHERE id = :project_id AND user_id = :user_id"),
                              {"project_id": project_id, "user_id": current_user.id})
    project_row = project_result.first()

    if not project_row:
        raise HTTPException(status_code=404, detail="项目不存在")

    project = dict(project_row._mapping)

    like = f"%{q.strip()}%" if q and q.strip() else None
    if like:
        result = await db.execute(
            text("""SELECT q.*, c.name AS concept_name, ts.title AS session_title
                    FROM questions q
                    LEFT JOIN concepts c ON q.concept_id = c.id
                    LEFT JOIN teaching_sessions ts ON c.session_id = ts.id
                    WHERE ts.project_id = :pid AND (q.prompt LIKE :like OR c.name LIKE :like)
                    ORDER BY q.created_at DESC, q.id DESC"""),
            {"pid": project_id, "like": like}
        )
    else:
        result = await db.execute(
            text("""SELECT q.*, c.name AS concept_name, ts.title AS session_title
                    FROM questions q
                    LEFT JOIN concepts c ON q.concept_id = c.id
                    LEFT JOIN teaching_sessions ts ON c.session_id = ts.id
                    WHERE ts.project_id = :pid
                    ORDER BY q.created_at DESC, q.id DESC"""),
            {"pid": project_id}
        )
    bank = []
    for row in result.fetchall():
        item = dict(row._mapping)
        try:
            item["knowledge_points"] = json.loads(item.get("knowledge_points") or "[]")
        except Exception:
            item["knowledge_points"] = []
        bank.append(item)

    template = jinja_env.get_template("practice/bank.html")
    html_content = template.render(
        request=request,
        user=current_user,
        project=project,
        bank=bank
    )
    return HTMLResponse(content=html_content)

@router.get("/practice/{project_id}/bank-search")
async def practice_bank_search(request: Request, project_id: str, q: str = "", current_user: User = Depends(get_current_user), db = Depends(get_db)):
    """题库搜索 partial：按题目内容或考点（概念名）搜索。"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    project_result = await db.execute(text("SELECT 1 FROM projects WHERE id = :project_id AND user_id = :user_id"),
                              {"project_id": project_id, "user_id": current_user.id})
    if not project_result.first():
        raise HTTPException(status_code=404, detail="项目不存在")

    like = f"%{q.strip()}%" if q and q.strip() else None
    if like:
        result = await db.execute(
            text("""SELECT q.*, c.name AS concept_name, ts.title AS session_title
                    FROM questions q
                    LEFT JOIN concepts c ON q.concept_id = c.id
                    LEFT JOIN teaching_sessions ts ON c.session_id = ts.id
                    WHERE ts.project_id = :pid AND (q.prompt LIKE :like OR c.name LIKE :like)
                    ORDER BY q.created_at DESC, q.id DESC"""),
            {"pid": project_id, "like": like}
        )
    else:
        result = await db.execute(
            text("""SELECT q.*, c.name AS concept_name, ts.title AS session_title
                    FROM questions q
                    LEFT JOIN concepts c ON q.concept_id = c.id
                    LEFT JOIN teaching_sessions ts ON c.session_id = ts.id
                    WHERE ts.project_id = :pid
                    ORDER BY q.created_at DESC, q.id DESC"""),
            {"pid": project_id}
        )
    bank = []
    for row in result.fetchall():
        item = dict(row._mapping)
        try:
            item["knowledge_points"] = json.loads(item.get("knowledge_points") or "[]")
        except Exception:
            item["knowledge_points"] = []
        bank.append(item)

    template = jinja_env.get_template("practice/partials/bank.html")
    html_content = template.render(request=request, user=current_user, bank=bank)
    return HTMLResponse(content=html_content)

@router.get("/practice/session/{session_id}", response_class=HTMLResponse)
async def practice_session_page(request: Request, session_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    session_result = await db.execute(
        text("SELECT * FROM practice_sessions WHERE id = :sid AND user_id = :uid"),
        {"sid": session_id, "uid": current_user.id}
    )
    session_row = session_result.first()
    if not session_row:
        raise HTTPException(status_code=404, detail="Session not found")
    session = dict(session_row._mapping)

    project_result = await db.execute(
        text("SELECT * FROM projects WHERE id = :pid AND user_id = :uid"),
        {"pid": session["project_id"], "uid": current_user.id}
    )
    project_row = project_result.first()
    if not project_row:
        raise HTTPException(status_code=404, detail="项目不存在")
    project = dict(project_row._mapping)

    # 会话题目（含作答状态）
    items_result = await db.execute(
        text("""SELECT psq.id AS sq_id, psq.order_index, psq.user_answer, psq.score, psq.feedback, psq.answered_at,
                       q.*, q.id AS question_id, c.id AS concept_id, c.name AS concept_name, ts.title AS session_title
                FROM practice_session_questions psq
                JOIN questions q ON psq.question_id = q.id
                LEFT JOIN concepts c ON q.concept_id = c.id
                LEFT JOIN teaching_sessions ts ON c.session_id = ts.id
                WHERE psq.session_id = :sid
                ORDER BY psq.order_index"""),
        {"sid": session_id}
    )
    questions = []
    for row in items_result.fetchall():
        item = dict(row._mapping)
        try:
            item["knowledge_points"] = json.loads(item.get("knowledge_points") or "[]")
        except Exception:
            item["knowledge_points"] = []
        questions.append(item)

    # 若会话题目不足 10 道，用项目中最新题目补足（含刚生成/刚撤销保留的题目）；
    # 同样排除短期内已作答的题目（避免重复）
    existing_ids = [q["question_id"] for q in questions]
    if len(questions) < 10:
        need = 10 - len(questions)
        cutoff = datetime.utcnow() - timedelta(hours=24)
        base_sql = """SELECT q.id FROM questions q
                      LEFT JOIN concepts c ON q.concept_id = c.id
                      LEFT JOIN teaching_sessions ts ON c.session_id = ts.id
                      WHERE ts.project_id = :pid
                        AND NOT EXISTS (SELECT 1 FROM review_records rr2
                                        JOIN review_schedules rs2 ON rr2.schedule_id = rs2.id
                                        WHERE rs2.user_id = :uid AND rs2.question_id = q.id
                                          AND rr2.reviewed_at > :cutoff)"""
        if existing_ids:
            placeholders = ",".join([f":eid{i}" for i in range(len(existing_ids))])
            params = {f"eid{i}": eid for i, eid in enumerate(existing_ids)}
            params.update({"pid": project["id"], "uid": current_user.id, "cutoff": cutoff, "need": need})
            fill_result = await db.execute(
                text(f"{base_sql} AND q.id NOT IN ({placeholders})"
                     f" ORDER BY q.created_at DESC, q.id DESC LIMIT :need"),
                params
            )
        else:
            fill_result = await db.execute(
                text(base_sql + " ORDER BY q.created_at DESC, q.id DESC LIMIT :need"),
                {"pid": project["id"], "uid": current_user.id, "cutoff": cutoff, "need": need}
            )
        fill_rows = fill_result.fetchall()
        for idx, frow in enumerate(fill_rows):
            sq_id = str(uuid4())
            await db.execute(
                text("INSERT INTO practice_session_questions (id, session_id, question_id, order_index) VALUES (:id, :sid, :qid, :idx)"),
                {"id": sq_id, "sid": session_id, "qid": frow[0], "idx": len(questions) + idx}
            )
        if fill_rows:
            await db.commit()
            return RedirectResponse(url=f"/practice/session/{session_id}", status_code=302)

    answered = sum(1 for q in questions if q.get("answered_at"))
    template = jinja_env.get_template("practice/session.html")
    html_content = template.render(
        request=request,
        user=current_user,
        project=project,
        session=session,
        questions=questions,
        answered=answered,
        total=len(questions)
    )
    return HTMLResponse(content=html_content)

@router.get("/integration/{project_id}", response_class=HTMLResponse)
async def integration_page(request: Request, project_id: str, graph_id: str = None, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    project_result = await db.execute(text("SELECT * FROM projects WHERE id = :project_id AND user_id = :user_id"),
                              {"project_id": project_id, "user_id": current_user.id})
    project_row = project_result.first()

    if not project_row:
        raise HTTPException(status_code=404, detail="项目不存在")

    project = dict(project_row._mapping)

    # 获取项目的所有图谱
    graphs_result = await db.execute(
        text("SELECT g.*, d.name as directory_name FROM graphs g LEFT JOIN directories d ON g.directory_id = d.id WHERE g.project_id = :project_id ORDER BY g.created_at"),
        {"project_id": project_id}
    )
    graphs = [dict(row._mapping) for row in graphs_result.fetchall()]

    # 获取项目的所有目录（用于关联图谱）
    directories_result = await db.execute(
        text("SELECT id, name FROM directories WHERE project_id = :project_id ORDER BY name"),
        {"project_id": project_id}
    )
    directories = [dict(row._mapping) for row in directories_result.fetchall()]

    # 确定当前图谱：优先使用传入的 graph_id，否则使用第一个图谱
    current_graph = None
    if graph_id:
        for g in graphs:
            if g['id'] == graph_id:
                current_graph = g
                break
    if not current_graph and graphs:
        current_graph = graphs[0]

    current_graph_id = current_graph['id'] if current_graph else None

    # 获取当前图谱的节点和边
    nodes = []
    edges = []
    if current_graph_id:
        nodes_result = await db.execute(
            text("""SELECT n.*, c.name as concept_name, c.status as concept_status
                   FROM nodes n LEFT JOIN concepts c ON n.concept_id = c.id
                   WHERE n.graph_id = :graph_id ORDER BY n.label"""),
            {"graph_id": current_graph_id}
        )
        nodes = [dict(row._mapping) for row in nodes_result.fetchall()]

        edges_result = await db.execute(
            text("""SELECT e.*, sn.label as source_label, tn.label as target_label
                   FROM edges e
                   LEFT JOIN nodes sn ON e.source_node_id = sn.id
                   LEFT JOIN nodes tn ON e.target_node_id = tn.id
                   WHERE e.graph_id = :graph_id ORDER BY e.relation"""),
            {"graph_id": current_graph_id}
        )
        edges = [dict(row._mapping) for row in edges_result.fetchall()]

    # 获取可沉淀的概念（已掌握但未沉淀）
    promotable_result = await db.execute(
        text("""SELECT c.*, ts.title as session_title
               FROM concepts c
               JOIN teaching_sessions ts ON c.session_id = ts.id
               WHERE ts.project_id = :project_id AND c.status = 'mastered'
               AND NOT EXISTS (SELECT 1 FROM nodes n WHERE n.concept_id = c.id)"""),
        {"project_id": project_id}
    )
    promotable_concepts = [dict(row._mapping) for row in promotable_result.fetchall()]

    # 获取虚拟图列表
    virtual_graphs_result = await db.execute(
        text("""SELECT vg.*, ts.title as session_title, g.name as graph_name,
               (SELECT COUNT(*) FROM virtual_graph_nodes vgn WHERE vgn.virtual_graph_id = vg.id) as node_count
               FROM virtual_graphs vg
               LEFT JOIN teaching_sessions ts ON vg.session_id = ts.id
               LEFT JOIN graphs g ON vg.graph_id = g.id
               WHERE ts.project_id = :project_id
               ORDER BY vg.created_at DESC"""),
        {"project_id": project_id}
    )
    virtual_graphs = [dict(row._mapping) for row in virtual_graphs_result.fetchall()]

    # 获取教学会话列表（用于创建虚拟图时选择）
    teaching_sessions_result = await db.execute(
        text("SELECT id, title FROM teaching_sessions WHERE project_id = :project_id ORDER BY created_at DESC"),
        {"project_id": project_id}
    )
    teaching_sessions = [dict(row._mapping) for row in teaching_sessions_result.fetchall()]

    template = jinja_env.get_template("integration/graph.html")
    html_content = template.render(
        request=request,
        user=current_user,
        project=project,
        graphs=graphs,
        current_graph=current_graph,
        directories=directories,
        nodes=nodes,
        edges=edges,
        promotable_concepts=promotable_concepts,
        virtual_graphs=virtual_graphs,
        teaching_sessions=teaching_sessions
    )
    return HTMLResponse(content=html_content)
