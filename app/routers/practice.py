from fastapi import APIRouter, Depends, HTTPException
from uuid import uuid4
from datetime import datetime, timedelta
from sqlalchemy import text

from app.core.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.practice import Question, ReviewSchedule, ReviewRecord
from app.schemas.practice import QuestionResponse, ReviewScheduleResponse, ReviewRecordCreate, ReviewRecordResponse

router = APIRouter()

@router.get("/questions/{concept_id}", response_model=list[QuestionResponse])
async def list_questions(concept_id: str, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    questions = await db.execute("SELECT * FROM questions WHERE concept_id = :concept_id", {"concept_id": concept_id})
    return questions.fetchall()

@router.get("/today", response_model=list[ReviewScheduleResponse])
async def get_today_reviews(current_user: User = Depends(get_current_user), db = Depends(get_db)):
    now = datetime.utcnow()
    schedules = await db.execute(
        "SELECT * FROM review_schedules WHERE user_id = :user_id AND next_review_at <= :now",
        {"user_id": current_user.id, "now": now}
    )
    return schedules.fetchall()

@router.post("/reviews", response_model=ReviewRecordResponse)
async def submit_review(record: ReviewRecordCreate, current_user: User = Depends(get_current_user), db = Depends(get_db)):
    schedule = await db.execute(text("SELECT * FROM review_schedules WHERE id = :schedule_id"), {"schedule_id": record.schedule_id})
    schedule = schedule.first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Review schedule not found")

    new_record = ReviewRecord(
        id=str(uuid4()),
        schedule_id=record.schedule_id,
        user_answer=record.user_answer,
        is_correct=record.is_correct,
        ai_feedback=record.ai_feedback
    )
    db.add(new_record)

    if record.is_correct:
        # 更新复习间隔
        new_interval = min(schedule.interval_days * 2, 100)
        new_ease = min(schedule.ease_factor + 0.1, 3.0)
        await db.execute(
            text("UPDATE review_schedules SET interval_days = :interval, ease_factor = :ease, next_review_at = :next WHERE id = :id"),
            {"interval": new_interval, "ease": new_ease, "next": datetime.utcnow() + timedelta(days=new_interval), "id": record.schedule_id}
        )

        # 答题正确，上调节点掌握度 5%
        # 通过 question -> concept -> node 找到节点
        question_result = await db.execute(text("SELECT concept_id FROM questions WHERE id = :qid"), {"qid": schedule.question_id})
        question_row = question_result.first()
        if question_row:
            concept_id = question_row[0]
            node_result = await db.execute(text("SELECT id, mastery_score FROM nodes WHERE concept_id = :cid"), {"cid": concept_id})
            node_row = node_result.first()
            if node_row:
                new_mastery = min(node_row[1] + 0.05, 1.0)
                await db.execute(
                    text("UPDATE nodes SET mastery_score = :ms WHERE id = :nid"),
                    {"ms": new_mastery, "nid": node_row[0]}
                )
    else:
        new_interval = max(schedule.interval_days / 2, 1)
        new_ease = max(schedule.ease_factor - 0.2, 1.3)
        await db.execute(
            text("UPDATE review_schedules SET interval_days = :interval, ease_factor = :ease, next_review_at = :next WHERE id = :id"),
            {"interval": new_interval, "ease": new_ease, "next": datetime.utcnow() + timedelta(days=new_interval), "id": record.schedule_id}
        )

    await db.commit()
    await db.refresh(new_record)
    return new_record
