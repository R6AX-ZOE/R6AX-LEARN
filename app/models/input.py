from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import Base

class Project(Base):
    __tablename__ = "projects"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"))
    name = Column(String, nullable=False)
    description = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    directories = relationship("Directory", back_populates="project")
    teaching_sessions = relationship("TeachingSession", back_populates="project")
    graphs = relationship("Graph", back_populates="project")

class Directory(Base):
    __tablename__ = "directories"
    
    id = Column(String, primary_key=True, index=True)
    project_id = Column(String, ForeignKey("projects.id"))
    parent_id = Column(String, ForeignKey("directories.id"), nullable=True)
    name = Column(String, nullable=False)
    description = Column(String, default="")
    order_index = Column(Integer, default=0)
    
    project = relationship("Project", back_populates="directories")
    notes = relationship("Note", back_populates="directory")
    graphs = relationship("Graph", back_populates="directory")
    children = relationship("Directory", back_populates="parent")
    parent = relationship("Directory", remote_side=[id], back_populates="children")

class Note(Base):
    __tablename__ = "notes"

    id = Column(String, primary_key=True, index=True)
    directory_id = Column(String, ForeignKey("directories.id"), nullable=True)
    title = Column(String, nullable=False)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    directory = relationship("Directory", back_populates="notes")
