from pydantic import BaseModel

class QuestionResponse(BaseModel):
    id: str
    concept_id: str
    question_type: str
    prompt: str
    answer: str
    explanation: str
    difficulty: float
    
    class Config:
        from_attributes = True

class ReviewScheduleResponse(BaseModel):
    id: str
    user_id: str
    question_id: str
    next_review_at: str
    interval_days: float
    ease_factor: float
    
    class Config:
        from_attributes = True

class ReviewRecordCreate(BaseModel):
    schedule_id: str
    user_answer: str
    is_correct: bool
    ai_feedback: str = ""

class ReviewRecordResponse(BaseModel):
    id: str
    schedule_id: str
    user_answer: str
    is_correct: bool
    ai_feedback: str
    reviewed_at: str
    
    class Config:
        from_attributes = True
