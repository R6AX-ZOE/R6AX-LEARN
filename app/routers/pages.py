from fastapi import APIRouter, Depends, HTTPException, Request, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm

from sqlalchemy import text

from app.core.database import get_db
from app.core.security import verify_password, create_access_token
from app.core.deps import get_current_user
from app.models.user import User
from app.models.input import Project
from app.schemas.project import ProjectCreate

from app.i18n.i18n import t, set_locale, get_current_locale

from jinja2 import Environment, FileSystemLoader

router = APIRouter()

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
    
    response = HTMLResponse(content=jinja_env.get_template("auth/login.html").render(request=request, error=None))
    if locale:
        response.set_cookie(key="locale", value=locale)
    return response

@router.post("/login")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db = Depends(get_db)):
    user = await db.execute(text("SELECT * FROM users WHERE username = :username"), {"username": form_data.username})
    user = user.first()
    
    if not user or not verify_password(form_data.password, user.password_hash):
        html_content = jinja_env.get_template("auth/login.html").render(request=request, error=t("error.login.failed"))
        return HTMLResponse(content=html_content, status_code=401)
    
    access_token = create_access_token(data={"sub": user.username})
    
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(key="access_token", value=access_token, httponly=True)
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
    
    template = jinja_env.get_template("pages/project_list.html")
    html_content = template.render(request=request, user=current_user, projects=projects)
    return HTMLResponse(content=html_content)

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
    
    template = jinja_env.get_template("pages/project_detail.html")
    html_content = template.render(request=request, user=current_user, project=project)
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
