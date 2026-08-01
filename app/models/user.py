from datetime import datetime

from sqlalchemy import Column, DateTime, String

from app.models.base import Base

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    preferred_locale = Column(String, default="zh_CN")
    created_at = Column(DateTime, default=datetime.utcnow)
