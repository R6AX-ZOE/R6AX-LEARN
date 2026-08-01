from pydantic import BaseModel

class ProjectCreate(BaseModel):
    name: str
    description: str = ""

class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None

class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str
    created_at: str
    
    class Config:
        from_attributes = True
