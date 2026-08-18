from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from uuid import uuid4
from datetime import datetime, timedelta
from sqlalchemy import text

from jinja2 import Environment, FileSystemLoader

from app.core.deps import get_current_active_user, get_db, require_project
from app.models.user import User
from app.services.question_generator import grade_answer
from app.services.practice_jobs import (
    create_generation_job,
    get_generation_job,
    cancel_generation_job,
)
from app.i18n.i18n import t

router = APIRouter()

jinja_env = Environment(
    loader=FileSystemLoader("app/templates"),
    autoescape=True,
    cache_size=0
)
jinja_env.globals['t'] = t

SESSION_SIZE = 10          # 一次习题会话包含 10 道题
RECENT_ANSWER_HOURS = 24   # 短时间内避免重复做同一道题

# ====== F-16: 错题累积触发新一轮 Teaching 的阈值 ======
TRIGGER_CONSECUTIVE_WRONG = 3   # 同一 concept 连续答错次数阈值
TRIGGER_WINDOW = 10             # 滚动窗口：最近 N 次作答
TRIGGER_WRONG_MIN = 6           # 窗口内答错次数阈值


async def _check_and_trigger_teaching(db, user_id: str, project_id: str, concept_id: str) -> dict | None:
    """F-16：同一 concept 错题累积达到阈值时，创建新一轮 Teaching 会话（幂等）。

    阈值：① 连续答错 >= TRIGGER_CONSECUTIVE_WRONG 次；或
         ② 最近 TRIGGER_WINDOW 次作答中答错 >= TRIGGER_WRONG_MIN 次（且累计答错 >= 3 次）。
    已存在未归档的 practice_trigger 会话时不重复创建。
    返回 {"session_id", "concept_name"} 或 None。
    """
    if not concept_id:
        return None

    # 幂等保护：该 concept 已有未归档的 practice_trigger 会话则不重复创建
    existing = await db.execute(
        text("SELECT id FROM teaching_sessions WHERE trigger_concept_id = :cid AND status = 'active'"),
        {"cid": concept_id}
    )
    if existing.first():
        return None

    # 该 concept 的全部作答记录（新→旧）
    rows = await db.execute(
        text("""SELECT rr.is_correct, rr.reviewed_at, q.prompt, rr.user_answer, rr.ai_feedback
                FROM review_records rr
                JOIN review_schedules rs ON rr.schedule_id = rs.id
                JOIN questions q ON rs.question_id = q.id
                WHERE q.concept_id = :cid AND rs.user_id = :uid
                ORDER BY rr.reviewed_at DESC"""),
        {"cid": concept_id, "uid": user_id}
    )
    records = rows.fetchall()
    if not records:
        return None

    consecutive_wrong = 0
    for r in records:
        if not r[0]:
            consecutive_wrong += 1
        else:
            break

    window = records[:TRIGGER_WINDOW]
    wrong_in_window = sum(1 for r in window if not r[0])
    total_wrong = sum(1 for r in records if not r[0])

    triggered = (
        consecutive_wrong >= TRIGGER_CONSECUTIVE_WRONG
        or (total_wrong >= 3 and wrong_in_window >= TRIGGER_WRONG_MIN)
    )
    if not triggered:
        return None

    concept_row = (await db.execute(text("SELECT name FROM concepts WHERE id = :cid"), {"cid": concept_id})).first()
    concept_name = concept_row[0] if concept_row else ""

    session_id = str(uuid4())
    title = t("practice.trigger-session-title", name=concept_name) if concept_name else t("practice.trigger-session-default")
    now = datetime.utcnow()
    await db.execute(
        text("""INSERT INTO teaching_sessions (id, project_id, title, status, trigger_concept_id, created_at, updated_at)
                VALUES (:id, :pid, :title, 'active', :cid, :now, :now)"""),
        {"id": session_id, "pid": project_id, "title": title, "cid": concept_id, "now": now}
    )

    # 错题背景写入首条 system 消息，作为 Teaching AI 的开局上下文
    lines = [t("practice.trigger-system-hint", name=concept_name)]
    for r in records[:3]:
        lines.append(t("practice.trigger-system-item",
                       prompt=(r[2] or "")[:300],
                       answer=(r[3] or "")[:200],
                       feedback=(r[4] or "")[:300]))
    await db.execute(
        text("""INSERT INTO messages (id, session_id, role, content, is_active, created_at)
                VALUES (:id, :sid, 'system', :content, 1, :now)"""),
        {"id": str(uuid4()), "sid": session_id, "content": "\n".join(lines), "now": now}
    )

    return {"session_id": session_id, "concept_name": concept_name}


def _question_with_context(row) -> dict:
    r = dict(row._mapping)
    import json
    try:
        kps = json.loads(r.get("knowledge_points") or "[]")
    except Exception:
        kps = []
    return {
        "id": r["id"],
        "concept_id": r.get("concept_id"),
        "concept_name": r.get("concept_name") or "",
        "question_type": r["question_type"],
        "prompt": r["prompt"],
        "answer": r["answer"],
        "explanation": r.get("explanation") or "",
        "difficulty": r.get("difficulty") or 1,
        "is_extension": bool(r.get("is_extension")),
        "knowledge_points": kps,
        "rationale": r.get("rationale") or "",
        "session_title": r.get("session_title") or "",
    }


# ====== 题库列表（F-13：所有题目，答案默认折叠，可按题目/考点搜索） ======

@router.get("/bank")
async def bank_questions(project_id: str, q: str = "", current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    """项目题库：按题目内容或考点（概念名）搜索，返回题目列表（含答案）。"""
    await require_project(db, project_id, current_user.id)

    like = f"%{q.strip()}%" if q and q.strip() else None
    if like:
        result = await db.execute(
            text("""SELECT q.*, c.name AS concept_name, ts.title AS session_title
                    FROM questions q
                    LEFT JOIN concepts c ON q.concept_id = c.id
                    LEFT JOIN teaching_sessions ts ON c.session_id = ts.id
                    WHERE ts.project_id = :pid
                      AND (q.prompt LIKE :like OR c.name LIKE :like)
                    ORDER BY q.created_at DESC"""),
            {"pid": project_id, "like": like}
        )
    else:
        result = await db.execute(
            text("""SELECT q.*, c.name AS concept_name, ts.title AS session_title
                    FROM questions q
                    LEFT JOIN concepts c ON q.concept_id = c.id
                    LEFT JOIN teaching_sessions ts ON c.session_id = ts.id
                    WHERE ts.project_id = :pid
                    ORDER BY q.created_at DESC"""),
            {"pid": project_id}
        )
    return [_question_with_context(row) for row in result.fetchall()]


# ====== 习题会话（F-13：一次 session 包含复习范围内 10 道题） ======

def _due_questions_sql() -> str:
    return """
        SELECT q.*, c.id AS concept_id, c.name AS concept_name, ts.title AS session_title
        FROM review_schedules rs
        JOIN questions q ON rs.question_id = q.id
        LEFT JOIN concepts c ON q.concept_id = c.id
        LEFT JOIN teaching_sessions ts ON c.session_id = ts.id
        WHERE rs.user_id = :uid
          AND rs.next_review_at <= :now
          AND ts.project_id = :pid
          AND NOT EXISTS (SELECT 1 FROM review_records rr2
                          JOIN review_schedules rs2 ON rr2.schedule_id = rs2.id
                          WHERE rs2.user_id = rs.user_id AND rs2.question_id = q.id
                            AND rr2.reviewed_at > :cutoff)
          AND NOT EXISTS (SELECT 1 FROM practice_session_questions psq2
                          JOIN practice_sessions ps2 ON psq2.session_id = ps2.id
                          WHERE psq2.question_id = q.id AND ps2.user_id = :uid
                            AND ps2.status = 'active')
        ORDER BY rs.next_review_at
        LIMIT :limit
    """


async def _available_question_count(db, user_id: str, project_id: str, cutoff: datetime) -> int:
    """项目内当前可用的题目数（排除 24h 内已作答、已在活跃会话中的题目）。"""
    result = await db.execute(
        text("""SELECT COUNT(DISTINCT q.id)
                FROM questions q
                LEFT JOIN concepts c ON q.concept_id = c.id
                LEFT JOIN teaching_sessions ts ON c.session_id = ts.id
                WHERE ts.project_id = :pid
                  AND NOT EXISTS (SELECT 1 FROM review_records rr2
                                  JOIN review_schedules rs2 ON rr2.schedule_id = rs2.id
                                  WHERE rs2.user_id = :uid AND rs2.question_id = q.id
                                    AND rr2.reviewed_at > :cutoff)
                  AND NOT EXISTS (SELECT 1 FROM practice_session_questions psq2
                                  JOIN practice_sessions ps2 ON psq2.session_id = ps2.id
                                  WHERE psq2.question_id = q.id AND ps2.user_id = :uid
                                    AND ps2.status = 'active')"""),
        {"uid": user_id, "pid": project_id, "cutoff": cutoff}
    )
    return result.scalar() or 0


@router.post("/sessions")
async def create_session(request: Request, current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    """开始完成习题：从复习范围（今日待复习）选 10 道题；不足则后台出题并返回 job_id。"""
    body = await request.json()
    project_id = body.get("project_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")

    await require_project(db, project_id, current_user.id)

    # 关闭该用户/项目此前未完成的会话
    await db.execute(
        text("UPDATE practice_sessions SET status = 'completed', completed_at = :now WHERE user_id = :uid AND project_id = :pid AND status = 'active'"),
        {"now": datetime.utcnow(), "uid": current_user.id, "pid": project_id}
    )

    now = datetime.utcnow()
    cutoff = now - timedelta(hours=RECENT_ANSWER_HOURS)

    due = await db.execute(
        text(_due_questions_sql()),
        {"uid": current_user.id, "now": now, "pid": project_id, "cutoff": cutoff, "limit": SESSION_SIZE}
    )
    due_rows = due.fetchall()

    session_id = str(uuid4())
    await db.execute(
        text("INSERT INTO practice_sessions (id, user_id, project_id, status, created_at) VALUES (:id, :uid, :pid, 'active', :now)"),
        {"id": session_id, "uid": current_user.id, "pid": project_id, "now": now}
    )
    for idx, row in enumerate(due_rows):
        sq_id = str(uuid4())
        await db.execute(
            text("INSERT INTO practice_session_questions (id, session_id, question_id, order_index) VALUES (:id, :sid, :qid, :idx)"),
            {"id": sq_id, "sid": session_id, "qid": row[0], "idx": idx}
        )
    await db.commit()

    question_count = len(due_rows)
    generating = False
    job_id = None
    # 仅当整个题库的可用题目都不足 10 道时才出题（避免浪费）：
    # 会话页会从题库（含未到期题目）补足剩余名额
    if question_count < SESSION_SIZE:
        avail = await _available_question_count(db, current_user.id, project_id, cutoff)
        if avail < SESSION_SIZE:
            job_id = create_generation_job(project_id, current_user.id)
            generating = True

    return {
        "status": "ok",
        "session_id": session_id,
        "question_count": question_count,
        "generating": generating,
        "job_id": job_id,
    }


@router.post("/sessions/{session_id}/complete")
async def complete_session(session_id: str, current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    await db.execute(
        text("UPDATE practice_sessions SET status = 'completed', completed_at = :now WHERE id = :sid AND user_id = :uid"),
        {"now": datetime.utcnow(), "sid": session_id, "uid": current_user.id}
    )
    await db.commit()
    return {"status": "ok"}


@router.get("/sessions/{session_id}/questions")
async def session_questions(session_id: str, current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    """会话内的题目（含作答状态）。供会话页刷新/轮询使用。"""
    session = await db.execute(
        text("SELECT * FROM practice_sessions WHERE id = :sid AND user_id = :uid"),
        {"sid": session_id, "uid": current_user.id}
    )
    session_row = session.first()
    if not session_row:
        raise HTTPException(status_code=404, detail="Session not found")

    result = await db.execute(
        text("""SELECT psq.id AS sq_id, psq.order_index, psq.user_answer, psq.score, psq.feedback, psq.answered_at,
                       q.*, c.id AS concept_id, c.name AS concept_name, ts.title AS session_title
                FROM practice_session_questions psq
                JOIN questions q ON psq.question_id = q.id
                LEFT JOIN concepts c ON q.concept_id = c.id
                LEFT JOIN teaching_sessions ts ON c.session_id = ts.id
                WHERE psq.session_id = :sid
                ORDER BY psq.order_index"""),
        {"sid": session_id}
    )
    items = []
    for row in result.fetchall():
        item = _question_with_context(row)
        item["sq_id"] = row[0]
        item["order_index"] = row[1]
        item["user_answer"] = row[2]
        item["score"] = row[3]
        item["feedback"] = row[4]
        item["answered_at"] = row[5]
        items.append(item)
    return {
        "session_id": session_id,
        "status": session_row[3],
        "questions": items,
    }


# ====== F-13 / F-14: 作答 + 立即反馈 ======

@router.post("/answers")
async def submit_answer(request: Request, current_user: User = Depends(get_current_active_user), db = Depends(get_db)):
    """提交一道题：AI 对照参考答案赋分（0~100），立即返回评分与反馈。

    同时：写 ReviewRecord（含 score）、更新 ReviewSchedule（简单间隔）、
    更新节点 MasteryScore、记录会话内作答状态。
    HTMX 请求返回 result partial 供页面局部刷新。
    """
    body = {}
    if request.headers.get("content-type", "").startswith("application/json"):
        body = await request.json()
    sq_id = body.get("session_question_id")
    user_answer = (body.get("user_answer") or "").strip()
    if not sq_id:
        form = await request.form()
        sq_id = (form.get("session_question_id") or "").strip()
        user_answer = (form.get("user_answer") or "").strip()
    if not sq_id:
        raise HTTPException(status_code=400, detail="session_question_id required")

    sq_result = await db.execute(
        text("""SELECT psq.*, ps.user_id, ps.project_id, ps.status AS session_status,
                       q.*, c.id AS concept_id, c.name AS concept_name, ts.title AS session_title
                FROM practice_session_questions psq
                JOIN practice_sessions ps ON psq.session_id = ps.id
                JOIN questions q ON psq.question_id = q.id
                LEFT JOIN concepts c ON q.concept_id = c.id
                LEFT JOIN teaching_sessions ts ON c.session_id = ts.id
                WHERE psq.id = :sqid AND ps.user_id = :uid"""),
        {"sqid": sq_id, "uid": current_user.id}
    )
    sq_row = sq_result.first()
    if not sq_row:
        raise HTTPException(status_code=404, detail="Session question not found")
    sq = dict(sq_row._mapping)
    if sq.get("answered_at"):
        raise HTTPException(status_code=400, detail="Question already answered")

    question = {
        "question_type": sq["question_type"],
        "prompt": sq["prompt"],
        "answer": sq["answer"],
    }
    is_correct, score, feedback = await grade_answer(db, question, user_answer)

    now = datetime.utcnow()

    # 会话内作答状态
    await db.execute(
        text("UPDATE practice_session_questions SET user_answer = :ans, score = :score, feedback = :fb, answered_at = :at WHERE id = :sqid"),
        {"ans": user_answer, "score": score, "fb": feedback, "at": now, "sqid": sq_id}
    )

    # 找到对应 schedule（同一 question 的最新 schedule）
    schedule_result = await db.execute(
        text("""SELECT rs.* FROM review_schedules rs
                WHERE rs.user_id = :uid AND rs.question_id = :qid
                ORDER BY rs.next_review_at DESC LIMIT 1"""),
        {"uid": current_user.id, "qid": sq["question_id"]}
    )
    schedule_row = schedule_result.first()

    if schedule_row:
        schedule = dict(schedule_row._mapping)
        # 简单间隔调度：答对间隔翻倍，答错减半（至少 1 天）
        if is_correct:
            new_interval = min(schedule["interval_days"] * 2, 100)
            new_ease = min(schedule["ease_factor"] + 0.1, 3.0)
        else:
            new_interval = max(schedule["interval_days"] / 2, 1)
            new_ease = max(schedule["ease_factor"] - 0.2, 1.3)

        record_id = str(uuid4())
        await db.execute(
            text("""INSERT INTO review_records (id, schedule_id, user_answer, is_correct, score, ai_feedback, reviewed_at)
                   VALUES (:id, :sid, :ans, :correct, :score, :fb, :at)"""),
            {"id": record_id, "sid": schedule["id"], "ans": user_answer,
             "correct": is_correct, "score": score, "fb": feedback, "at": now}
        )
        await db.execute(
            text("""UPDATE review_schedules
                    SET interval_days = :interval, ease_factor = :ease, next_review_at = :next
                    WHERE id = :id"""),
            {"interval": new_interval, "ease": new_ease,
             "next": now + timedelta(days=new_interval), "id": schedule["id"]}
        )
        next_interval = new_interval
    else:
        record_id = None
        next_interval = 1

    # 更新节点 MasteryScore（F-17）：答对 +5%，答错 -5%（同一 concept 关联的全部节点）
    mastery_delta = None
    if sq.get("concept_id"):
        node_result = await db.execute(
            text("SELECT id, mastery_score FROM nodes WHERE concept_id = :cid"),
            {"cid": sq["concept_id"]}
        )
        for node_row in node_result.fetchall():
            if is_correct:
                new_mastery = min((node_row[1] or 0) + 0.05, 1.0)
            else:
                new_mastery = max((node_row[1] or 0) - 0.05, 0.0)
            await db.execute(
                text("UPDATE nodes SET mastery_score = :ms WHERE id = :nid"),
                {"ms": new_mastery, "nid": node_row[0]}
            )
            mastery_delta = 0.05 if is_correct else -0.05

    # F-16: 错题累积到阈值 → 创建新一轮 Teaching 会话（幂等）
    trigger = None
    if not is_correct and sq.get("concept_id"):
        trigger = await _check_and_trigger_teaching(
            db, current_user.id, sq["project_id"], sq["concept_id"]
        )

    await db.commit()

    result = {
        "status": "ok",
        "sq_id": sq_id,
        "session_id": sq["session_id"],
        "project_id": sq["project_id"],
        "is_correct": is_correct,
        "score": round(score, 1),
        "feedback": feedback,
        "user_answer": user_answer,
        "reference_answer": sq["answer"],
        "explanation": sq.get("explanation") or "",
        "is_extension": bool(sq.get("is_extension")),
        "concept_name": sq.get("concept_name") or "",
        "interval_days": next_interval,
        "record_id": record_id,
        "mastery_delta": mastery_delta,
        "trigger": trigger,
    }

    # 下一道未作答题目
    next_result = await db.execute(
        text("""SELECT id FROM practice_session_questions
                WHERE session_id = :sid AND answered_at IS NULL
                ORDER BY order_index LIMIT 1"""),
        {"sid": sq["session_id"]}
    )
    next_row = next_result.first()
    result["next_sq_id"] = next_row[0] if next_row else None
    result["answered_count"] = (await db.execute(
        text("SELECT COUNT(*) FROM practice_session_questions WHERE session_id = :sid AND answered_at IS NOT NULL"),
        {"sid": sq["session_id"]}
    )).scalar()

    if request.headers.get("HX-Request") == "true":
        html = jinja_env.get_template("practice/partials/result.html").render(
            result=result,
            request=request,
            user=current_user,
        )
        return HTMLResponse(content=html)

    return result


# ====== 后台出题 job（可撤销） ======

@router.get("/generate-job/{job_id}")
async def generation_job_status(job_id: str, current_user: User = Depends(get_current_active_user)):
    job = get_generation_job(job_id)
    if not job or job["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/generate-job/{job_id}/cancel")
async def generation_job_cancel(job_id: str, current_user: User = Depends(get_current_active_user)):
    job = cancel_generation_job(job_id)
    if not job or job["user_id"] != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
