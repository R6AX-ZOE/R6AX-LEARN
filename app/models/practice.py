from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, Float, Boolean, Enum
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
    ai_feedback = Column(Text)
    reviewed_at = Column(DateTime, default=datetime.utcnow)
    
    schedule = relationship("ReviewSchedule", back_populates="records")
