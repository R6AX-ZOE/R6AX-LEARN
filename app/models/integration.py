from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, Float, Integer, Enum
from sqlalchemy.orm import relationship

from app.models.base import Base

class Graph(Base):
    __tablename__ = "graphs"

    id = Column(String, primary_key=True, index=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    directory_id = Column(String, ForeignKey("directories.id"), nullable=True)
    name = Column(String, default="知识图谱")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="graphs")
    directory = relationship("Directory", back_populates="graphs")
    nodes = relationship("Node", back_populates="graph")
    edges = relationship("Edge", back_populates="graph")

class Node(Base):
    __tablename__ = "nodes"

    id = Column(String, primary_key=True, index=True)
    graph_id = Column(String, ForeignKey("graphs.id"))
    concept_id = Column(String, ForeignKey("concepts.id"))
    label = Column(String, nullable=False)
    mastery_score = Column(Float, default=0.0)

    graph = relationship("Graph", back_populates="nodes")
    concept = relationship("Concept", back_populates="node")
    embeddings = relationship("NodeEmbedding", back_populates="node")
    source_edges = relationship("Edge", foreign_keys="Edge.source_node_id", back_populates="source")
    target_edges = relationship("Edge", foreign_keys="Edge.target_node_id", back_populates="target")

class Edge(Base):
    __tablename__ = "edges"
    
    id = Column(String, primary_key=True, index=True)
    graph_id = Column(String, ForeignKey("graphs.id"))
    source_node_id = Column(String, ForeignKey("nodes.id"))
    target_node_id = Column(String, ForeignKey("nodes.id"))
    relation = Column(Enum("prerequisite", "related", "parent"), nullable=False)
    label = Column(String)
    weight = Column(Float, default=1.0)
    
    graph = relationship("Graph", back_populates="edges")
    source = relationship("Node", foreign_keys=[source_node_id], back_populates="source_edges")
    target = relationship("Node", foreign_keys=[target_node_id], back_populates="target_edges")

class NodeEmbedding(Base):
    __tablename__ = "node_embeddings"
    
    id = Column(String, primary_key=True, index=True)
    node_id = Column(String, ForeignKey("nodes.id"))
    embedding = Column(Text)
    
    node = relationship("Node", back_populates="embeddings")

# ====== 虚拟图模型（中间层）======

class VirtualGraph(Base):
    """虚拟图：包含多个节点的结构化知识单元，作为中间层"""
    __tablename__ = "virtual_graphs"
    
    id = Column(String, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("teaching_sessions.id"))
    graph_id = Column(String, ForeignKey("graphs.id"), nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    session = relationship("TeachingSession")
    graph = relationship("Graph")
    virtual_nodes = relationship("VirtualGraphNode", back_populates="virtual_graph")
    virtual_edges = relationship("VirtualGraphEdge", back_populates="virtual_graph")
    to_node_edges = relationship("VirtualGraphToNodeEdge", back_populates="virtual_graph")

class VirtualGraphNode(Base):
    """虚拟图节点：虚拟图内部的节点"""
    __tablename__ = "virtual_graph_nodes"

    id = Column(String, primary_key=True, index=True)
    virtual_graph_id = Column(String, ForeignKey("virtual_graphs.id"))
    node_id = Column(String, ForeignKey("nodes.id"), nullable=True)  # 可选：关联真实Node
    label = Column(String, nullable=False)
    properties = Column(Text)  # JSON格式的二元组列表：[[和node的关系, 名称], ...]
    content = Column(Text)  # 详细内容
    order_index = Column(Integer, default=0)
    mastery_score = Column(Float, default=0.0)

    virtual_graph = relationship("VirtualGraph", back_populates="virtual_nodes")
    node = relationship("Node")
    source_v_edges = relationship("VirtualGraphEdge", foreign_keys="VirtualGraphEdge.source_vnode_id", back_populates="source_vnode")
    target_v_edges = relationship("VirtualGraphEdge", foreign_keys="VirtualGraphEdge.target_vnode_id", back_populates="target_vnode")

class VirtualGraphEdge(Base):
    """虚拟图边：虚拟图内部节点之间的连接"""
    __tablename__ = "virtual_graph_edges"
    
    id = Column(String, primary_key=True, index=True)
    virtual_graph_id = Column(String, ForeignKey("virtual_graphs.id"))
    source_vnode_id = Column(String, ForeignKey("virtual_graph_nodes.id"))
    target_vnode_id = Column(String, ForeignKey("virtual_graph_nodes.id"))
    relation = Column(String, nullable=False)  # prerequisite, related, next, detail等
    label = Column(String)
    
    virtual_graph = relationship("VirtualGraph", back_populates="virtual_edges")
    source_vnode = relationship("VirtualGraphNode", foreign_keys=[source_vnode_id], back_populates="source_v_edges")
    target_vnode = relationship("VirtualGraphNode", foreign_keys=[target_vnode_id], back_populates="target_v_edges")

class VirtualGraphToNodeEdge(Base):
    """虚拟图到真实节点的连接：虚拟图与真实图谱的关联"""
    __tablename__ = "virtual_graph_to_node_edges"
    
    id = Column(String, primary_key=True, index=True)
    virtual_graph_id = Column(String, ForeignKey("virtual_graphs.id"))
    node_id = Column(String, ForeignKey("nodes.id"))
    relation_type = Column(String, nullable=False)  # contains, references, expands等
    
    virtual_graph = relationship("VirtualGraph", back_populates="to_node_edges")
    node = relationship("Node")

class VirtualGraphEmbedding(Base):
    """虚拟图嵌入向量：用于RAG搜索"""
    __tablename__ = "virtual_graph_embeddings"
    
    id = Column(String, primary_key=True, index=True)
    virtual_graph_id = Column(String, ForeignKey("virtual_graphs.id"))
    embedding = Column(Text)  # JSON格式的向量数据
    
    virtual_graph = relationship("VirtualGraph")
