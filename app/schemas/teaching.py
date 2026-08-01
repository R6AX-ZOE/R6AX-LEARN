from pydantic import BaseModel

class TeachingSessionCreate(BaseModel):
    project_id: str
    title: str

class TeachingSessionResponse(BaseModel):
    id: str
    project_id: str
    title: str
    status: str
    created_at: str
    
    class Config:
        from_attributes = True

class MessageCreate(BaseModel):
    content: str

class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: str
    
    class Config:
        from_attributes = True

class ConceptResponse(BaseModel):
    id: str
    session_id: str
    name: str
    description: str
    status: str
    
    class Config:
        from_attributes = True
