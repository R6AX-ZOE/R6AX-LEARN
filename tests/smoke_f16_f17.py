"""F-16~F-17 冒烟测试：错题累积触发新一轮 Teaching（F-16）+ 答题结果更新 MasteryScore（F-17）。

强制空 API key，走确定性路径：fill 题规则判分，答"42"必对、答其他必错。
"""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/test_f16_f17.db"
os.environ["DEEPSEEK_API_KEY"] = ""  # 强制走规则判分 / 降级路径
os.environ["JWT_SECRET"] = "5a1f7d3e9b2c4f6a8d0e1b3c5d7f9a2b4c6e8d0f1a3b5c7d9e0f2a4b6c8d"

from fastapi.testclient import TestClient

from app.main import app
from app.core.database import init_db, AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.user import User
from sqlalchemy import select

import sqlite3


async def _init():
    await init_db()
    async with AsyncSessionLocal() as session:
        r = await session.execute(select(User).where(User.username == "admin"))
        if not r.first():
            session.add(User(id="admin", username="admin", password_hash=get_password_hash("admin")))
            await session.commit()


asyncio.get_event_loop().run_until_complete(_init())

client = TestClient(app)

# ---- CSRF 防护：先取 cookie，后续不安全请求带 X-CSRF-Token ----
client.get("/login")
_csrf = client.cookies.get("csrf_token")


def post(url, **kw):
    headers = dict(kw.get("headers") or {})
    headers.setdefault("X-CSRF-Token", _csrf)
    kw["headers"] = headers
    return client.post(url, **kw)


# ---- 登录 ----
r = post("/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
assert r.status_code in (200, 302), r.status_code
assert client.cookies.get("access_token"), "no token"

# ---- 造数据：项目 + 会话 + 概念 + 题目(fill) + 调度 + 图谱节点 ----
conn = sqlite3.connect("data/test_f16_f17.db")
conn.execute("INSERT OR IGNORE INTO projects (id, user_id, name, description, created_at, updated_at) VALUES ('p1','admin','P','',datetime('now'),datetime('now'))")
conn.execute("INSERT OR IGNORE INTO teaching_sessions (id, project_id, title, status, created_at, updated_at) VALUES ('s1','p1','概念A','active',datetime('now'),datetime('now'))")
conn.execute("INSERT OR IGNORE INTO concepts (id, session_id, name, description, user_explanation, status) VALUES ('c1','s1','特征值','测试概念描述','用户讲解内容','mastered')")
conn.execute("INSERT OR IGNORE INTO questions (id, concept_id, question_type, prompt, answer, explanation, difficulty, created_at) VALUES ('q1','c1','fill','特征方程 |A-λI|=0 的解叫____？','42','',1,datetime('now'))")
conn.execute("INSERT OR IGNORE INTO review_schedules (id, user_id, question_id, next_review_at, interval_days, ease_factor) VALUES ('rs1','admin','q1',datetime('now'),1.0,2.5)")
conn.execute("INSERT OR IGNORE INTO practice_sessions (id, user_id, project_id, status, created_at) VALUES ('ps1','admin','p1','active',datetime('now'))")
conn.execute("INSERT OR IGNORE INTO practice_session_questions (id, session_id, question_id, order_index) VALUES ('sq1','ps1','q1',0)")
conn.execute("INSERT OR IGNORE INTO graphs (id, project_id, name, created_at, updated_at) VALUES ('g1','p1','图谱',datetime('now'),datetime('now'))")
conn.execute("INSERT OR IGNORE INTO nodes (id, graph_id, concept_id, label, mastery_score) VALUES ('n1','g1','c1','特征值',0.5)")
conn.commit()


def reset_question():
    conn.execute("UPDATE practice_session_questions SET answered_at = NULL, score = NULL, feedback = NULL, user_answer = NULL WHERE id = 'sq1'")
    conn.commit()


def answer(text):
    return post("/api/practice/answers", json={"session_question_id": "sq1", "user_answer": text}).json()


# ---- F-16: 连续答错 3 次触发 ----
for i in range(3):
    res = answer("错误答案")
    assert res["status"] == "ok" and res["is_correct"] is False, res
    reset_question()
assert res["trigger"] is not None, res
trigger = res["trigger"]
assert trigger["concept_name"] == "特征值"
print(f"[ok] F-16: 3 consecutive wrong answers -> trigger session {trigger['session_id']}")

# 会话已创建（trigger_concept_id 标记 + 复习标题）
row = conn.execute("SELECT trigger_concept_id, title, status FROM teaching_sessions WHERE id = ?", (trigger["session_id"],)).fetchone()
assert row and row[0] == "c1" and row[1] == "复习：特征值" and row[2] == "active", row
print(f"[ok] F-16: teaching session created with trigger_concept_id, title='{row[1]}'")

# system 消息带错题背景
sys_msg = conn.execute("SELECT content FROM messages WHERE session_id = ? AND role = 'system' AND is_active = 1", (trigger["session_id"],)).fetchone()
assert sys_msg and "特征值" in sys_msg[0] and "错误答案" in sys_msg[0] and "题目" in sys_msg[0], sys_msg
print("[ok] F-16: system message carries wrong-answer context")

# F-17: 节点掌握度 3 次答错 0.5 -> 0.35
ms = conn.execute("SELECT mastery_score FROM nodes WHERE id = 'n1'").fetchone()[0]
assert abs(ms - 0.35) < 1e-9, ms
assert res["mastery_delta"] == -0.05, res
print(f"[ok] F-17: node mastery 0.5 -> {ms}, mastery_delta={res['mastery_delta']}")

# ---- F-16 幂等：再次答错不重复创建 ----
res = answer("又错一次")
assert res["trigger"] is None, res
reset_question()
count = conn.execute("SELECT COUNT(*) FROM teaching_sessions WHERE trigger_concept_id = 'c1'").fetchone()[0]
assert count == 1, count
print("[ok] F-16: idempotent - no duplicate session")

# ---- 答对：掌握度 +5%，且不触发 ----
res = answer("42")
assert res["is_correct"] is True and res["trigger"] is None, res
reset_question()
# 前 4 次答错 0.5 -> 0.30，答对 +0.05 -> 0.35
ms = conn.execute("SELECT mastery_score FROM nodes WHERE id = 'n1'").fetchone()[0]
assert abs(ms - 0.35) < 1e-9, ms
assert res["mastery_delta"] == 0.05, res
print(f"[ok] F-17: correct answer -> mastery {ms}, delta={res['mastery_delta']}")

# ---- F-17 边界：mastery 封顶 1.0 / 触底 0.0 ----
conn.execute("UPDATE nodes SET mastery_score = 1.0 WHERE id = 'n1'")
conn.commit()
res = answer("42")
assert res["is_correct"] is True
reset_question()
ms = conn.execute("SELECT mastery_score FROM nodes WHERE id = 'n1'").fetchone()[0]
assert ms == 1.0, ms
print("[ok] F-17: mastery capped at 1.0")

conn.execute("UPDATE nodes SET mastery_score = 0.0 WHERE id = 'n1'")
conn.commit()
res = answer("错")
assert res["is_correct"] is False and res["trigger"] is None, res
reset_question()
ms = conn.execute("SELECT mastery_score FROM nodes WHERE id = 'n1'").fetchone()[0]
assert ms == 0.0, ms
print("[ok] F-17: mastery floored at 0.0")

# ---- Practice 首页横幅（F-16 展示） ----
r = client.get("/practice/p1")
assert r.status_code == 200
html = r.text
assert "建议重新讲一遍" in html or "Suggested Re-teach" in html
assert f"/api/teaching/sessions/{trigger['session_id']}" in html
print("[ok] F-16: hub page shows re-teach banner with session link")

# ---- 触发的 Teaching 会话页可访问 ----
r = client.get(f"/api/teaching/sessions/{trigger['session_id']}")
assert r.status_code == 200, r.status_code
assert "复习：特征值" in r.text
print("[ok] F-16: triggered teaching session page renders")

# ---- 无 concept_id 的作答不报错（无节点保护）----
conn.execute("INSERT OR IGNORE INTO questions (id, concept_id, question_type, prompt, answer, explanation, difficulty, created_at) VALUES ('q2',NULL,'fill','无概念题？','1','',1,datetime('now'))")
conn.execute("INSERT OR IGNORE INTO review_schedules (id, user_id, question_id, next_review_at, interval_days, ease_factor) VALUES ('rs2','admin','q2',datetime('now'),1.0,2.5)")
conn.execute("INSERT OR IGNORE INTO practice_session_questions (id, session_id, question_id, order_index) VALUES ('sq2','ps1','q2',1)")
conn.commit()
res = post("/api/practice/answers", json={"session_question_id": "sq2", "user_answer": "x"}).json()
assert res["status"] == "ok" and res["mastery_delta"] is None and res["trigger"] is None, res
print("[ok] F-16/F-17: question without concept -> safe skip (no crash, no delta)")

print("\nALL F-16/F-17 SMOKE TESTS PASSED")
