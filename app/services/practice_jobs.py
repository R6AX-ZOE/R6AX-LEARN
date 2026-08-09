"""Practice Level 后台出题 job 管理器（F-12 约束：出题不在 Teaching 对话内）。

- 会话创建时若复习范围内题目不足，启动一个后台出题 job；
- 用户可撤销：撤销后已生成的题目保留在题库；
- job 状态通过 GET /api/practice/generate-job/{id} 轮询。
- 独立线程 + 独立事件循环运行，保证在任意 ASGI 环境（含 TestClient）下都能执行。
"""
import asyncio
import threading
from uuid import uuid4

from app.core.database import AsyncSessionLocal
from app.services.question_generator import SET_TOTAL, generate_question_set

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _snapshot(job: dict) -> dict:
    return {
        "id": job["id"],
        "user_id": job["user_id"],
        "status": job["status"],
        "generated": job["generated"],
        "total": job["total"],
        "error": job.get("error"),
    }


def create_generation_job(project_id: str, user_id: str) -> str:
    """创建后台出题 job（独立线程运行），返回 job_id。"""
    job_id = str(uuid4())
    job = {
        "id": job_id,
        "project_id": project_id,
        "user_id": user_id,
        "status": "running",
        "generated": 0,
        "total": SET_TOTAL,
        "error": None,
        "_cancelled": False,
    }
    with _lock:
        _jobs[job_id] = job
    threading.Thread(target=_run_job_thread, args=(job,), daemon=True).start()
    return job_id


def _run_job_thread(job: dict):
    asyncio.run(_run_job(job))


async def _run_job(job: dict):
    try:
        async with AsyncSessionLocal() as db:
            def cancel_check() -> bool:
                return job["_cancelled"]

            def on_question_generated(q: dict):
                job["generated"] += 1

            await generate_question_set(
                db,
                project_id=job["project_id"],
                user_id=job["user_id"],
                should_cancel=cancel_check,
                on_question_generated=on_question_generated,
            )
            if job["_cancelled"]:
                job["status"] = "cancelled"
            else:
                job["status"] = "done"
    except Exception as e:
        print(f"[practice_jobs] generation job failed: {e}")
        job["status"] = "error"
        job["error"] = str(e)


def get_generation_job(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
    return _snapshot(job) if job else None


def cancel_generation_job(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        job["_cancelled"] = True
        if job["status"] == "running":
            job["status"] = "cancelling"
    return _snapshot(job)
