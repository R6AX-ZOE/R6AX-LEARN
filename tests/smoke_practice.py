"""F-12~F-15 冒烟测试（新版界面/逻辑）：强制空 API key，走确定性降级出题路径。"""
import os
import sys
import asyncio
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/test_f12_f15.db"
os.environ["DEEPSEEK_API_KEY"] = ""  # 强制走降级出题（确定性、快速）
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

# ---- 造数据：项目 + 会话 + 概念（mastered）----
conn = sqlite3.connect("data/test_f12_f15.db")
conn.execute("INSERT OR IGNORE INTO projects (id, user_id, name, description, created_at, updated_at) VALUES ('p1','admin','P','',datetime('now'),datetime('now'))")
conn.execute("INSERT OR IGNORE INTO teaching_sessions (id, project_id, title, status, created_at, updated_at) VALUES ('s1','p1','概念A','active',datetime('now'),datetime('now'))")
conn.execute("INSERT OR IGNORE INTO concepts (id, session_id, name, description, user_explanation, status) VALUES ('c1','s1','概念A','测试概念描述','用户讲解内容','mastered')")
conn.commit()

# ---- 练习首页（hub）：只有开始入口 + 题库入口链接，题库在独立页面 ----
r = client.get("/practice/p1")
assert r.status_code == 200, r.status_code
html = r.text
assert "开始完成习题" in html or "Start Practice" in html
assert "/bank" in html  # 题库入口链接
assert "bank-list" not in html  # 题库列表不在 hub 页面
assert "sessions-in-progress" not in html  # key 不在页面，改为检查文案
print("[ok] GET /practice/p1 (hub, no bank list)")

# ---- 题库独立页面 ----
r = post("/api/practice/sessions", json={"project_id": "p1"})
data = r.json()
sid_a = data["session_id"]
job_id = data["job_id"]

# 等出题完成（空 API key 走降级，很快）
done = False
for _ in range(60):
    j = client.get(f"/api/practice/generate-job/{job_id}").json()
    if j["status"] in ("done", "cancelled", "error"):
        done = True
        break
    time.sleep(0.3)
assert done

r = client.get("/practice/p1/bank")
assert r.status_code == 200, r.status_code
html = r.text
assert "bank-list" in html and "bank-answer" in html
print("[ok] GET /practice/p1/bank (standalone page)")

# 题库搜索 partial（htmx）
r = client.get("/practice/p1/bank-search", params={"q": "概念A"})
assert r.status_code == 200
assert "bank-answer" in r.text
print("[ok] GET /practice/p1/bank-search (partial)")

# ---- 会话 A：先答 2 道题再完成（为撤销测试准备：剩余可用 8 道 < 10） ----
html = client.get(f"/practice/session/{sid_a}").text
import re
sq_ids_a = re.findall(r'session_question_id" value="([^"]+)"', html)
assert len(sq_ids_a) == 10, len(sq_ids_a)

r = post("/api/practice/answers",
                data={"session_question_id": sq_ids_a[0], "user_answer": "我的答案：特征值就是特征方程的解"},
                headers={"HX-Request": "true"})
assert r.status_code == 200, r.text
assert "得分" in r.text or "Score" in r.text
assert "我的答案：特征值就是特征方程的解" in r.text  # 评审后显示原答案
print("[ok] POST /api/practice/answers (HTMX partial, immediate feedback + original answer)")

r = post("/api/practice/answers", json={"session_question_id": sq_ids_a[1], "user_answer": "x"})
assert r.status_code == 200, r.text
res = r.json()
assert res["status"] == "ok" and 0 <= res["score"] <= 100
print(f"[ok] POST /api/practice/answers (JSON) -> score={res['score']}, interval={res['interval_days']}")

# 已作答题目不能重复作答
r = post("/api/practice/answers", json={"session_question_id": sq_ids_a[1], "user_answer": "again"})
assert r.status_code == 400, r.text
print("[ok] duplicate answer rejected")

r = post(f"/api/practice/sessions/{sid_a}/complete")
assert r.status_code == 200
print("[ok] POST /api/practice/sessions/{id}/complete")

# ---- 首页：已完成会话出现在题库入口下方，未完成会话在题库入口上方 ----
r = client.get("/practice/p1")
html = r.text
assert "未完成的习题" in html or "Sessions in Progress" in html
assert "已完成的习题" in html or "Completed Sessions" in html
i_inprog = html.find("未完成的习题")
i_bank = html.find("题库")
i_completed = html.find("已完成的习题")
assert -1 < i_inprog < i_bank < i_completed, (i_inprog, i_bank, i_completed)
print("[ok] hub shows in-progress (above bank) + completed (below bank) sessions")

# ---- 撤销出题 job（cancel）：可用题目 8 道 < 10 -> 触发后台出题 -> 撤销 ----
r = post("/api/practice/sessions", json={"project_id": "p1"})
data = r.json()
sid_b = data["session_id"]
assert data["generating"] is True and data["job_id"], data
job_b = data["job_id"]
r = post(f"/api/practice/generate-job/{job_b}/cancel")
assert r.status_code == 200, r.text
job = r.json()
assert job["status"] in ("cancelling", "cancelled", "done")
print("[ok] cancel generation -> cancelled")
# 已生成的题目保留在题库
r = client.get("/api/practice/bank", params={"project_id": "p1"})
assert len(r.json()) >= 10
print("[ok] cancel generation -> questions remain in bank")

# ---- 会话 B：题目应补足到 10 道 ----
r = client.get(f"/practice/session/{sid_b}")
assert r.status_code == 200, r.status_code
html = r.text
assert "习题" in html
sq_ids = re.findall(r'session_question_id" value="([^"]+)"', html)
unanswered = re.findall(r'id="md-editor-([^"]+)"', html)
print(f"[ok] GET /practice/session/{sid_b} -> {len(sq_ids)} forms, {len(unanswered)} editors")
assert len(sq_ids) >= 8, f"expected >= 8 questions, got {len(sq_ids)}"
assert len(unanswered) >= 8

# ---- 会话 B 作答（走 AI 判题降级路径）----
sq_id = sq_ids[0]
r = post("/api/practice/answers", json={"session_question_id": sq_id, "user_answer": "x"})
assert r.status_code == 200, r.text
res = r.json()
assert res["status"] == "ok" and 0 <= res["score"] <= 100
assert res["interval_days"] >= 1
print(f"[ok] POST /api/practice/answers -> score={res['score']}, interval={res['interval_days']}")

# ---- 会话问题 API ----
r = client.get(f"/api/practice/sessions/{sid_b}/questions")
assert r.status_code == 200
qdata = r.json()
assert qdata["questions"][0]["user_answer"] == "x"
print("[ok] GET /api/practice/sessions/{id}/questions")

# ---- 结束会话 ----
r = post(f"/api/practice/sessions/{sid_b}/complete")
assert r.status_code == 200
print("[ok] POST /api/practice/sessions/{id}/complete")

print("\nALL SMOKE TESTS PASSED")
