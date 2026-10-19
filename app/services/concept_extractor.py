"""F-06: 从 Input Level 笔记中提取 Teaching Level 的"可教概念"（Concept Extractor AI）。

提炼规则依据以下学习科学理论构建（详见 docs/input_to_teaching.md）：
1. 教学转置（didactic transposition; Chevallard 1985）：把"笔记知识"转置为"可教知识"，
   产物是可讲解的教学对象，而不是关键词或摘要。
2. 概念性知识 vs 事实性知识（Anderson & Krathwohl 2001; Gagné et al. 2005）：
   只提取有明确定义、可讲解的概念/原理/方法，不提取孤立事实。
3. 生成学习与教中学（Wittrock 1974, 1989; Fiorella & Mayer 2013, 2015; Kobayashi 2019）：
   提取产物必须能支撑学习者"用自己的话讲出来"。
4. 概念教学结构（Klausmeier & Goodwin 1977; Tennyson & Cocchiarella 1986;
   Vinner & Hershkowitz 1980）：key_points 覆盖定义/原理/例子/适用条件/联系。
5. 认知负荷与粒度（Miller 1956; Cowan 2001; Sweller 1988; Mayer 2009）：
   3~8 个概念、每概念 2~4 个关键点，避免学科级宽泛或符号级琐碎。
6. 最小可教/可复用学习对象（Reigeluth & Stein 1983; Wiley 2002; IEEE LOM 2002）：
   概念应自包含、独立、可复用。
7. 已知知识锚定与最近发展区（Ausubel 1963; Vygotsky 1978; Doignon & Falmagne 1985）：
   跳过项目内已有概念，避免重复教学。

输出契约：{"concepts": [{name, description, key_points}]}；解析失败返回空列表（调用方兜底）。
"""
from typing import List, Dict, Any
from .ai_service import chat_completion
import json
import re
import itertools


def _as_concepts(data: Any) -> list[dict[str, str]]:
    """把解析结果规整为 name/description/key_points 三元组列表，过滤无名称条目。"""
    if not isinstance(data, dict):
        return []
    concepts = data.get("concepts")
    if not isinstance(concepts, list):
        return []
    result = []
    for c in concepts:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        key_points = c.get("key_points")
        result.append({
            "name": name.strip(),
            "description": str(c.get("description") or "").strip(),
            "key_points": [str(kp) for kp in key_points] if isinstance(key_points, list) else [],
        })
    return result


def _repair_truncated(text: str) -> list[dict[str, str]]:
    """输出被截断时修复重解析：

    1. 从最后一个完整概念对象的 '}' 处截断并补齐 ']}'；
    2. 若截断发生在字符串/数组中间，尝试补闭引号与剩余括号（']} }' 组合）。
    """
    if not text:
        return []
    # 1) 按完整对象截断
    for idx in range(len(text) - 1, -1, -1):
        if text[idx] != "}":
            continue
        prefix = text[:idx + 1].rstrip()
        if prefix.endswith(","):
            prefix = prefix[:-1].rstrip()
        for closer in ("]}", "]\n}"):
            try:
                return _as_concepts(json.loads(prefix + closer, strict=False))
            except (json.JSONDecodeError, ValueError):
                continue
    # 2) 语法补闭：补引号 + 剩余的 ] / } 组合
    closers = [""]
    for i in range(1, 5):
        closers.extend("".join(combo) for combo in itertools.product("]}", repeat=i))
    for quote in ('"', ""):
        for closer in closers:
            try:
                return _as_concepts(json.loads(text.rstrip() + quote + closer, strict=False))
            except (json.JSONDecodeError, ValueError):
                continue
    return []


def _extract_concepts_json(text: str) -> list[dict[str, str]]:
    """容错解析 AI 返回的概念 JSON：

    1. 剥离 Markdown 代码围栏；
    2. 截取第一个 '{' 到最后一个 '}'；
    3. 标准解析（strict=False 容忍字符串内换行）；
    4. 被截断时用 _repair_truncated 补齐重解析。
    """
    if not text:
        return []
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    candidates = [text]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.insert(0, text[start:end + 1])
    for candidate in candidates:
        try:
            return _as_concepts(json.loads(candidate, strict=False))
        except (json.JSONDecodeError, ValueError):
            continue
    return _repair_truncated(candidates[0])

async def extract_concepts(note_content: str, note_title: str = "", existing_concepts: List[Dict[str, str]] = None) -> List[Dict[str, str]]:
    """从笔记内容中提取可教的概念列表

    Args:
        note_content: 笔记内容
        note_title: 笔记标题
        existing_concepts: 项目中已存在的概念列表，避免重复提取
    """

    # 构建已有概念信息
    existing_concepts_text = ""
    if existing_concepts and len(existing_concepts) > 0:
        existing_concepts_text = "\n\n项目中已存在的概念（请勿重复提取以下概念）：\n"
        for i, concept in enumerate(existing_concepts, 1):
            existing_concepts_text += f"{i}. {concept.get('name', '')} - {concept.get('description', '')}\n"

    prompt = f"""
你是一位教学设计师（Concept Extractor AI），负责把学习者的原始笔记转化为**可教的概念**——即教学会话中可供学习者讲解的单元。
{existing_concepts_text}
请分析以下笔记，提取出**可教的概念**列表。

笔记标题：{note_title}

笔记内容：
{note_content[:3000]}

提炼规则（依据学习科学）：
1. 【概念性】只提取**有明确定义**的概念性/程序性知识（定义、原理、方法、模型等），不要提取孤立的事实、年份、数值、人物生平或无关细节。
2. 【可教性】每个概念必须能通过"用自己的话讲清楚"的检验：能讲清它是什么、为什么成立、怎么使用；讲不出来的条目不要提取。
3. 【独立性】每个概念是**自包含的最小可教单元**，脱离笔记上下文也能被独立讲解。
4. 【粒度】避免两类极端：
   - 太宽泛：学科级或章节级主题（如"线性代数""第三章内容"）；
   - 太琐碎：符号写法、细枝末节的数值或无关信息。
   粒度自检标准：它能否用 2~4 个关键点讲清楚。
5. 【数量】提取 3~8 个核心概念为宜。
6. 【讲解支架】每个概念给出：
   - "description"：一句话说清"是什么"；
   - "key_points"：2~4 个讲解时必须覆盖的关键点，优先从以下维度选取——定义/本质属性、原理或机制（为什么）、典型例子或反例、适用条件与边界、与已学概念的联系。
7. 【去重】**切勿重复提取已存在的概念**；与已有概念高度相似的请跳过。概念名称应简洁、术语规范，便于后续检索与合并。

输出格式：
只返回一个 JSON 对象，不要输出任何其他内容。JSON 必须**完整闭合**：宁可在笔记内容很多时只提取 3 个核心概念，也要保证输出完整、不要截断。description 不超过 40 字，key_points 每条不超过 15 字。
{{
  "concepts": [
    {{
      "name": "概念名称（简洁明了）",
      "description": "概念的简短描述",
      "key_points": ["关键点1", "关键点2"]
    }}
  ]
}}
"""

    messages = [
        {"role": "system", "content": "你是一位教学设计师与知识提炼专家（Concept Extractor AI），服务于'教中学'学习平台。"},
        {"role": "user", "content": prompt}
    ]
    
    try:
        response = await chat_completion(messages, temperature=0.3, max_tokens=8192)
        return _extract_concepts_json(response)
    except Exception as e:
        print(f"Concept extraction error: {e}")
        if 'response' in locals() and response:
            print(f"Raw response (first 300 chars): {str(response)[:300]!r}")
        return []