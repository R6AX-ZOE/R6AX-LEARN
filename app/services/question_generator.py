"""F-12: 题目生成（Question Generator AI）+ F-14: AI 阅卷（Practice AI）。

出题设计（Prompt 依据以下学习科学与出题理论构建）：
1. **六大学习策略**（Learning Scientists; Roediger & Putnam 2011; Rohrer 2012;
   McDaniel & Donnelly 1996; Rawson et al. 2014; Mayer & Anderson 1992）：
   - 检索练习（retrieval practice）：题目要求"回忆+重构"而非再认
   - 间隔与交错（spacing / interleaving）：一套题内交错多个知识点
   - 精加工（elaboration）：追问"为什么"，要求类比与机制解释
   - 具体例子（concrete examples）：要求举实例、找反例
   - 双编码（dual coding）：允许用图/公式/伪代码作答
2. **布鲁姆认知目标分类**（Bloom's taxonomy, 动词表, University of Arkansas）：
   简单题覆盖 Remember/Understand/Apply 层级；
   拓展题覆盖 Analyze/Evaluate/Create 层级。
3. **苏格拉底式提问**（changingminds.org 六类苏格拉底问题）：
   概念澄清、质疑假设、追问证据与理由、多视角、后果与影响、对问题本身的反思。
4. **迁移理论（near/far transfer）**：拓展题要求把概念迁移到陌生情境，
   并涉及尚未掌握的前置知识点（刻意困难，desirable difficulties），
   促使用户自解释、主动补课。

生成约束：
- 题目生成**不在** Teaching 会话对话流程内完成，
  由 Practice Level 显式触发（会话创建时的后台 job，可撤销）。
- 一套题目 = 6 道简单题 + 4 道拓展题，先产出"出题思路"（blueprint）再逐题设计。
- 一道题可涉及多个知识点（含未掌握的前置知识点）。
- 输出结构化 JSON；解析失败时降级为纯文本简答题。
- 题目语言跟随当前界面 locale（zh_CN / en_US）。
"""
import json
import re
from datetime import datetime, timedelta
from typing import Callable, Optional
from uuid import uuid4

from sqlalchemy import text

from app.i18n.i18n import get_current_locale
from app.services.ai_service import chat_completion

SIMPLE_COUNT = 6
EXTENSION_COUNT = 4
SET_TOTAL = SIMPLE_COUNT + EXTENSION_COUNT

GENERATE_SYSTEM_PROMPT = """你是教学设计师（Question Generator AI），为学习平台设计复习题。出题必须遵循以下经认知科学验证的学习理论：

【理论依据】
A. 检索练习（retrieval practice; Roediger & Putnam 2011）：题目必须强迫用户从记忆中"重构"知识，而不是再认；避免只问"什么是 X"式的复述，多问"为什么""如何""如果……会怎样"。
B. 精加工（elaboration; McDaniel & Donnelly 1996）：要求解释机制、找类比、把新知识与旧知识建立联系（"它为什么成立？"）。
C. 交错练习（interleaving; Rohrer 2012）：一套题内交错涉及多个概念/知识点，帮助用户区分相近概念。
D. 具体例子（concrete examples; Rawson et al. 2014）：要求举真实例子、构造反例、指出适用边界。
E. 双编码（dual coding; Mayer & Anderson 1992）：允许并要求用公式、伪代码、图示等方式作答。
F. 布鲁姆认知目标分类（Bloom's taxonomy）：
   - 简单题落在 Remember / Understand / Apply 层级（定义、复述、解释、直接应用）；
   - 拓展题落在 Analyze / Evaluate / Create 层级（比较、拆解、批判、评价、设计、创造）。
G. 苏格拉底式提问（six types of Socratic questions）：概念澄清、质疑假设、追问理由与证据、变换视角、推演后果与影响、对问题本身的反思。
H. 迁移理论（near/far transfer）：拓展题必须把概念迁移到陌生情境（领域迁移、组合应用、设计新方案），并刻意引入"尚未掌握的前置知识点"，制造适度的认知困难（desirable difficulties），促使用户自解释与主动补课。

【出题流程】
1. 先设计整套"出题思路"（blueprint）：说明目标概念、要交错的知识点、涉及的未掌握前置知识点、以及 6+4 道题的认知层次布局；
2. 再逐题设计：每道题都带 knowledge_points（涉及的知识点列表，含未掌握的前置知识点）与 rationale（该题的出题思路：设计意图 + 期望的思维链）。

【题型】choice（选择题，prompt 内必须含完整选项 A.~D.，answer 为正确选项字母）、fill（填空题，answer 多个可接受答案用 || 分隔）、short（简答题）、code（编程题，仅当概念适合代码实现）。

【输出】只返回一个 JSON 对象，不要输出任何其他内容：
{
  "blueprint": "整套出题思路",
  "questions": [
    {
      "type": "choice|fill|short|code",
      "is_extension": false,
      "prompt": "题目内容（含选项）",
      "answer": "参考答案（文本）",
      "explanation": "解析，说明为什么这样答、常见误区",
      "difficulty": 1,
      "knowledge_points": ["知识点1", "未掌握的前置知识点"],
      "rationale": "该题的出题思路与期望思维链"
    }
  ]
}
其中 questions 恰好包含 6 道 is_extension=false 的简单题和 4 道 is_extension=true 的拓展题，共 10 道。"""

GRADE_SYSTEM_PROMPT = """你是阅卷者（Practice AI）。用户用 Markdown/公式/代码回答了复习题，请对照参考答案评分。

评分标准：
1. 满分 100，依据答案对参考答案核心要点的覆盖程度、推理正确性、表达完整性分档给分：
   - 90~100：核心要点全覆盖，推理严密，表述清晰；
   - 70~89：覆盖大部分要点，有少量遗漏或小错误；
   - 50~69：只覆盖部分要点，或有明显概念性偏差；
   - 0~49：基本答非所问或严重错误。
2. 意思正确即可给分，不必逐字相同；代码题看思路与正确性，部分正确按比例给分；
3. is_correct 判定：score >= 60 为 true；
4. 反馈必须解释错因或肯定要点，并指出与参考答案的差距（不只给分数）；
5. 反馈必须使用用户当前界面语言书写；
6. 只返回一个 JSON 对象（不要输出任何其他内容）：
{
  "score": 85,
  "is_correct": true,
  "feedback": "反馈内容"
}"""


def _extract_json(text: str) -> Optional[dict]:
    """从 AI 输出中提取 JSON 对象，容错 ```json 包裹与前后杂音。"""
    if not text:
        return None
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    for candidate in (text, text[text.find("{"):text.rfind("}") + 1]):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _lang_hint() -> str:
    return "zh-CN（简体中文）" if get_current_locale() == "zh_CN" else "en-US（English）"


def _concept_context(concepts: list[dict]) -> str:
    lines = []
    for c in concepts:
        desc = (c.get("description") or "").strip()
        exp = (c.get("user_explanation") or "").strip()
        lines.append(f"- {c.get('name', '')}: 描述={desc or '无'}；用户讲解={exp or '无'}")
    return "\n".join(lines) if lines else "（项目内暂无已掌握概念）"


async def generate_question_set(
    db,
    project_id: str,
    user_id: str,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_question_generated: Optional[Callable[[dict], None]] = None,
) -> list[dict]:
    """为一个项目的已掌握概念生成一套题：6 简单 + 4 拓展。

    - 主概念：项目中已掌握概念里题目最少的那个（平衡题库）；
    - 其余已掌握概念作为交错/关联上下文；
    - 每道题生成后立即落库（Question + ReviewSchedule），
      便于"撤销后已出完的题目仍保留在题库"。
    - should_cancel 返回 True 时停止后续题目的落库。
    Returns: 实际生成的题目 dict 列表。
    """
    concepts_result = await db.execute(
        text("""SELECT c.* FROM concepts c
                JOIN teaching_sessions ts ON c.session_id = ts.id
                WHERE ts.project_id = :pid AND c.status IN ('mastered', 'promoted')"""),
        {"pid": project_id}
    )
    concepts = [dict(row._mapping) for row in concepts_result.fetchall()]
    if not concepts:
        return []

    # 主概念 = 已有题目最少的概念；其余作为上下文
    counts = {}
    for c in concepts:
        res = await db.execute(
            text("SELECT COUNT(*) FROM questions WHERE concept_id = :cid"),
            {"cid": c["id"]}
        )
        counts[c["id"]] = res.scalar() or 0
    concepts.sort(key=lambda c: (counts[c["id"]], c["name"]))
    primary = concepts[0]

    user_prompt = (
        f"主概念：{primary['name']}\n"
        f"主概念描述：{primary.get('description') or ''}\n"
        f"主概念的用户讲解记录：{primary.get('user_explanation') or ''}\n\n"
        f"项目内其他已掌握概念（用于交错与关联，也可作为拓展题的知识点）：\n"
        f"{_concept_context(concepts[1:])}\n\n"
        f"请用 {_lang_hint()} 设计一套题（6 道简单题 + 4 道拓展题）。"
        f"拓展题必须涉及多个知识点，且可以包含用户尚未掌握的前置知识点。"
    )

    # deepseek 思考模型：reasoning 消耗不稳定，偶发把输出预算耗尽返回空串。
    # 加大预算 + 失败重试，仍失败则走兜底题目。
    raw = None
    for attempt in range(3):
        try:
            raw = await chat_completion(
                messages=[
                    {"role": "system", "content": GENERATE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=16384,
            )
        except Exception as e:
            print(f"[question_generator] AI 出题失败（第 {attempt + 1} 次）: {e}")
            raw = None
        data = _extract_json(raw) if raw else None
        if data and data.get("questions"):
            break
        print(f"[question_generator] 出题输出为空或解析失败（第 {attempt + 1} 次），重试...")

    if data is None:
        data = {}

    # 校验：简单题 6 道、拓展题 4 道；不足则降级补齐
    questions = []
    for q in (data.get("questions") or []):
        qtype = q.get("type", "short")
        if qtype not in ("choice", "fill", "short", "code"):
            qtype = "short"
        prompt = (q.get("prompt") or "").strip()
        answer = (q.get("answer") or "").strip()
        if not prompt or not answer:
            continue
        questions.append({
            "question_type": qtype,
            "prompt": prompt,
            "answer": answer,
            "explanation": (q.get("explanation") or "").strip(),
            "difficulty": max(1, min(5, int(q.get("difficulty", 2) or 2))),
            "is_extension": bool(q.get("is_extension")),
            "knowledge_points": (q.get("knowledge_points") or []),
            "rationale": (q.get("rationale") or "").strip(),
        })

    simple = [q for q in questions if not q["is_extension"]][:SIMPLE_COUNT]
    extension = [q for q in questions if q["is_extension"]][:EXTENSION_COUNT]
    questions = simple + extension

    # 兜底：AI 失败/缺题时补齐 6 简单 + 4 拓展（保证一套 10 道可跑通）
    base_answer = (primary.get("description") or
                   f"能清晰定义 {primary['name']} 的核心含义并举例说明。")
    fallback_simple = [
        (f"请用自己的话解释：{primary['name']}。", 2),
        (f"请举一个 {primary['name']} 的实际应用例子，并说明其适用条件。", 2),
        (f"与 {primary['name']} 相似或容易混淆的概念有哪些？如何区分它们？", 3),
        (f"请说明 {primary['name']} 成立的原理或机制（为什么它是对的？）。", 3),
        (f"若 {primary['name']} 的某个前提条件被改变，结论会如何变化？", 3),
        (f"请用图示、公式或伪代码表述 {primary['name']} 的核心思想。", 2),
    ]
    fallback_extension = [
        (f"综合题：将 {primary['name']} 与你已学的其他知识点联系起来，设计一个能同时用到它们的场景，并说明各自的角色。", 4),
        (f"批判性思考：{primary['name']} 的常见误解或错误应用有哪些？如何识别并避免？", 4),
        (f"迁移题：把 {primary['name']} 应用到与课本完全不同的新领域（如工程/生活/其他学科），你会怎么做？需要哪些额外的前置知识？", 5),
        (f"设计题：基于 {primary['name']} 设计一个更复杂的问题或方案，给出你的解决思路与步骤。", 5),
    ]

    simple = [q for q in questions if not q["is_extension"]]
    extension = [q for q in questions if q["is_extension"]]

    def _fallback(prompt_text: str, difficulty: int, is_ext: bool) -> dict:
        return {
            "question_type": "short",
            "prompt": prompt_text,
            "answer": base_answer,
            "explanation": "请对照你的讲解记录复习该概念。",
            "difficulty": difficulty,
            "is_extension": is_ext,
            "knowledge_points": [primary["name"]],
            "rationale": "降级兜底题" + ("（拓展：多知识点迁移/设计）" if is_ext else "（检索练习基础题）"),
        }

    for i in range(SIMPLE_COUNT - len(simple)):
        prompt_text, diff = fallback_simple[len(simple)]
        simple.append(_fallback(prompt_text, diff, False))
    for i in range(EXTENSION_COUNT - len(extension)):
        prompt_text, diff = fallback_extension[len(extension)]
        extension.append(_fallback(prompt_text, diff, True))

    questions = (simple + extension)[:SET_TOTAL]

    now = datetime.utcnow()
    created = []
    for idx, q in enumerate(questions):
        if should_cancel and should_cancel():
            break
        created_q = await _insert_question(db, primary["id"], user_id, q, now, idx)
        if created_q:
            created.append(created_q)
            if on_question_generated:
                on_question_generated(created_q)

    await db.commit()
    return created


async def _insert_question(db, concept_id: str, user_id: str, q: dict, now: datetime, idx: int) -> Optional[dict]:
    question_id = str(uuid4())
    await db.execute(
        text("""INSERT INTO questions (id, concept_id, question_type, prompt, answer, explanation,
                                       difficulty, is_extension, knowledge_points, rationale, created_at)
               VALUES (:id, :cid, :qtype, :prompt, :answer, :explanation,
                       :difficulty, :is_ext, :kps, :rationale, :created)"""),
        {
            "id": question_id,
            "cid": concept_id,
            "qtype": q["question_type"],
            "prompt": q["prompt"],
            "answer": q["answer"],
            "explanation": q["explanation"],
            "difficulty": q["difficulty"],
            "is_ext": 1 if q["is_extension"] else 0,
            "kps": json.dumps(q.get("knowledge_points") or [], ensure_ascii=False),
            "rationale": q.get("rationale") or "",
            "created": now,
        }
    )
    # 初始复习计划：第一题立即可练，其余按天错开（简单时间间隔，PRD §8.2）
    schedule_id = str(uuid4())
    await db.execute(
        text("""INSERT INTO review_schedules (id, user_id, question_id, next_review_at, interval_days, ease_factor)
               VALUES (:id, :uid, :qid, :next, :interval, :ease)"""),
        {
            "id": schedule_id,
            "uid": user_id,
            "qid": question_id,
            "next": now + timedelta(days=idx),
            "interval": 1.0,
            "ease": 2.5,
        }
    )
    return {
        "id": question_id,
        "schedule_id": schedule_id,
        "question_type": q["question_type"],
        "prompt": q["prompt"],
        "answer": q["answer"],
        "explanation": q["explanation"],
        "difficulty": q["difficulty"],
        "is_extension": q["is_extension"],
        "knowledge_points": q.get("knowledge_points") or [],
        "rationale": q.get("rationale") or "",
    }


async def grade_answer(db, question: dict, user_answer: str) -> tuple[bool, float, str]:
    """判定一道题的对错并赋分（0~100）。

    - choice / fill：规则判定（归一化精确匹配），满分 100
    - short / code：AI 阅卷对照参考答案赋分（F-14）
    Returns: (is_correct, score, feedback)
    """
    qtype = question["question_type"]
    reference = (question.get("answer") or "").strip()

    if qtype in ("choice", "fill"):
        user_norm = _normalize(user_answer)
        accepted = [a.strip() for a in reference.split("||")]
        is_correct = any(_normalize(a) == user_norm for a in accepted if a)
        score = 100.0 if is_correct else 0.0
        feedback = "" if is_correct else f"参考答案：{reference}"
        return is_correct, score, feedback

    if not user_answer.strip():
        return False, 0.0, ""

    # DeepSeek 思考模型在慢速/限流时会重试很久，导致前端"评审中"长时间无结果。
    # 限制单次评审调用时长（含重试兜底），超时立即返回降级结果。
    import asyncio
    try:
        raw = await asyncio.wait_for(
            chat_completion(
                messages=[
                    {"role": "system", "content": GRADE_SYSTEM_PROMPT},
                    {"role": "user", "content": (
                        f"题目：{question.get('prompt', '')}\n"
                        f"参考答案：{reference}\n"
                        f"用户答案（Markdown）：{user_answer}\n\n"
                        f"请用 {_lang_hint()} 评分并给出反馈。"
                    )},
                ],
                temperature=0.2,
                max_tokens=4096,
            ),
            timeout=60,
        )
        data = _extract_json(raw) or {}
        if not data:
            # 输出为空/解析失败时重试一次
            raw = await asyncio.wait_for(
                chat_completion(
                    messages=[
                        {"role": "system", "content": GRADE_SYSTEM_PROMPT},
                        {"role": "user", "content": (
                            f"题目：{question.get('prompt', '')}\n"
                            f"参考答案：{reference}\n"
                            f"用户答案（Markdown）：{user_answer}\n\n"
                            f"请用 {_lang_hint()} 评分并给出反馈。"
                        )},
                    ],
                    temperature=0.2,
                    max_tokens=4096,
                ),
                timeout=60,
            )
            data = _extract_json(raw) or {}
        score = float(data.get("score", 0) or 0)
        score = max(0.0, min(100.0, score))
        is_correct = bool(data.get("is_correct")) or score >= 60
        feedback = (data.get("feedback") or "").strip()
        return is_correct, score, feedback
    except Exception as e:
        print(f"[practice] AI 判题失败: {e}")
        return False, 0.0, "AI 判题暂时不可用，请自行对照参考答案。"


def _normalize(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()
