from pydantic import BaseModel

class DirectoryCreate(BaseModel):
    project_id: str
    parent_id: str | None = None
    name: str
    description: str = ""

class DirectoryResponse(BaseModel):
    id: str
    project_id: str
    parent_id: str | None
    name: str
    description: str
    
    class Config:
        from_attributes = True

class NoteCreate(BaseModel):
    directory_id: str
    title: str
    content: str = ""

class NoteUpdate(BaseModel):
    title: str | None = None
    content: str | None = None

class NoteResponse(BaseModel):
    id: str
    directory_id: str
    title: str
    content: str
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = True
