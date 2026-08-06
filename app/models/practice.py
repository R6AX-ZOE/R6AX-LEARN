from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, Float, Boolean, Enum, Integer
from sqlalchemy.orm import relationship

from app.models.base import Base

class Question(Base):
    __tablename__ = "questions"
    
    id = Column(String, primary_key=True, index=True)
    concept_id = Column(String, ForeignKey("concepts.id"))
    question_type = Column(Enum("choice", "fill", "short", "code"), nullable=False)
    prompt = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    explanation = Column(Text)
    difficulty = Column(Float, default=1.0)
    is_extension = Column(Boolean, default=False)
    knowledge_points = Column(Text)  # JSON: 涉及的知识点列表
    rationale = Column(Text)  # 出题思路（该题的设计意图与思维链）
    created_at = Column(DateTime, default=datetime.utcnow)
    
    concept = relationship("Concept", back_populates="questions")
    review_schedules = relationship("ReviewSchedule", back_populates="question")

class ReviewSchedule(Base):
    __tablename__ = "review_schedules"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"))
    question_id = Column(String, ForeignKey("questions.id"))
    next_review_at = Column(DateTime, nullable=False)
    interval_days = Column(Float, default=1.0)
    ease_factor = Column(Float, default=2.5)
    
    question = relationship("Question", back_populates="review_schedules")
    records = relationship("ReviewRecord", back_populates="schedule")

class ReviewRecord(Base):
    __tablename__ = "review_records"
    
    id = Column(String, primary_key=True, index=True)
    schedule_id = Column(String, ForeignKey("review_schedules.id"))
    user_answer = Column(Text)
    is_correct = Column(Boolean, nullable=False)
    score = Column(Float, default=0.0)  # AI 赋分 0~100
    ai_feedback = Column(Text)
    reviewed_at = Column(DateTime, default=datetime.utcnow)
    
    schedule = relationship("ReviewSchedule", back_populates="records")

class PracticeSession(Base):
    """一次"开始完成习题"的练习会话：固定包含 10 道题（复习范围内）"""
    __tablename__ = "practice_sessions"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"))
    project_id = Column(String, ForeignKey("projects.id"))
    status = Column(Enum("active", "completed"), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    
    user = relationship("User")
    questions = relationship("PracticeSessionQuestion", back_populates="session")

class PracticeSessionQuestion(Base):
    __tablename__ = "practice_session_questions"
    
    id = Column(String, primary_key=True, index=True)
    session_id = Column(String, ForeignKey("practice_sessions.id"))
    question_id = Column(String, ForeignKey("questions.id"))
    order_index = Column(Integer, default=0)
    user_answer = Column(Text)
    score = Column(Float)
    feedback = Column(Text)
    answered_at = Column(DateTime)
    
    session = relationship("PracticeSession", back_populates="questions")
    question = relationship("Question")
