from fastapi import APIRouter, Depends, HTTPException
from uuid import uuid4

from app.core.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.input import Project, Directory, Note
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse

router = APIRouter()

@router.get("/", response_model=list[ProjectResponse])
async def list_projects(current_user: User = Depends(get_current_user), db = Depends(get_db)):
    projects = await db.execute("SELECT * FROM projects WHERE user_id = :user_id", {"user_id": current_user.id})
    return projects.fetchall()

@router.post("/", response_model=ProjectResponse)
async def create_project(project: ProjectCreate, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    new_project = Project(
        id=str(uuid4()),
        user_id=current_user.id,
        name=project.name,
        description=project.description
    )
    db.add(new_project)
    await db.commit()
    await db.refresh(new_project)
    return new_project

@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    project = await db.execute("SELECT * FROM projects WHERE id = :project_id AND user_id = :user_id", 
                              {"project_id": project_id, "user_id": current_user.id})
    project = project.first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(project_id: str, project: ProjectUpdate, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    existing = await db.execute("SELECT * FROM projects WHERE id = :project_id AND user_id = :user_id", 
                               {"project_id": project_id, "user_id": current_user.id})
    existing = existing.first()
    if not existing:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if project.name:
        existing.name = project.name
    if project.description:
        existing.description = project.description
    
    await db.commit()
    await db.refresh(existing)
    return existing

@router.delete("/{project_id}")
async def delete_project(project_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    project = await db.execute("SELECT * FROM projects WHERE id = :project_id AND user_id = :user_id", 
                              {"project_id": project_id, "user_id": current_user.id})
    project = project.first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    await db.delete(project)
    await db.commit()
    return {"message": "Project deleted successfully"}
