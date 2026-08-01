from pydantic import BaseModel

class GraphResponse(BaseModel):
    id: str
    project_id: str
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = True

class NodeCreate(BaseModel):
    graph_id: str
    concept_id: str | None = None
    label: str
    description: str = ""
    mastery_score: float = 0.0

class NodeResponse(BaseModel):
    id: str
    graph_id: str
    concept_id: str | None
    label: str
    description: str
    mastery_score: float
    
    class Config:
        from_attributes = True

class EdgeCreate(BaseModel):
    graph_id: str
    source_node_id: str
    target_node_id: str
    relation: str
    label: str = ""
    weight: float = 1.0

class EdgeResponse(BaseModel):
    id: str
    graph_id: str
    source_node_id: str
    target_node_id: str
    relation: str
    label: str
    weight: float
    
    class Config:
        from_attributes = True
