from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, JSON, Boolean, Enum
from sqlalchemy.orm import relationship

from app.models.base import Base

class TeachingSession(Base):
    __tablename__ = "teaching_sessions"
    
    id = Column(String, primary_key=True, index=True)
    project_id = Column(String, ForeignKey("projects.id"))
    source_note_id = Column(String, ForeignKey("notes.id"), nullable=True)
    trigger_concept_id = Column(String, ForeignKey("concepts.id"), nullable=True)
    title = Column(String, nullable=False)
    status = Column(Enum("active", "archived"), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    project = relationship("Project", back_populates="teaching_sessions")
    messages = relationship("Message", back_populates="session")
    concepts = relationship("Concept", back_populates="session", foreign_keys="Concept.session_id")
    misconceptions = relationship("Misconception", back_populates="session")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(String, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("teaching_sessions.id"))
    parent_id = Column(String, ForeignKey("messages.id"), nullable=True)
    branch_id = Column(String, nullable=True)
    role = Column(Enum("user", "assistant", "system"), nullable=False)
    content = Column(Text, nullable=False)
    extra_data = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    session = relationship("TeachingSession", back_populates="messages")
    parent = relationship("Message", remote_side=[id], backref="children")

class Concept(Base):
    __tablename__ = "concepts"
    
    id = Column(String, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("teaching_sessions.id"))
    name = Column(String, nullable=False)
    description = Column(Text)
    user_explanation = Column(Text)
    status = Column(Enum("mastered", "learning"), default="learning")
    
    session = relationship("TeachingSession", back_populates="concepts", foreign_keys=[session_id])
    questions = relationship("Question", back_populates="concept")
    node = relationship("Node", back_populates="concept", uselist=False)

class Misconception(Base):
    __tablename__ = "misconceptions"
    
    id = Column(String, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("teaching_sessions.id"))
    concept_name = Column(String, nullable=False)
    user_claim = Column(Text)
    ai_correction = Column(Text)
    resolved = Column(Boolean, default=False)
    
    session = relationship("TeachingSession", back_populates="misconceptions")
