from typing import List, Dict, Any
from .ai_service import chat_completion
import json

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
你是一个专业的教学设计师和知识提炼专家。

请分析以下笔记内容，从中提取出**可教的概念**列表。
{existing_concepts_text}
笔记标题：{note_title}

笔记内容：
{note_content[:3000]}

提取规则：
1. 概念应该是**有明确定义**的知识点，不是简单的事实陈述
2. 每个概念应该是**独立的、可讲解的**单元
3. 避免太宽泛或太琐碎的概念
4. 提取3-8个核心概念为宜
5. 对每个概念提供简短的描述和关键点
6. **切勿重复提取已存在的概念**，如果笔记内容中包含已存在的概念，请跳过它们

输出格式：
请以JSON格式输出，包含一个"concepts"数组，每个元素包含：
- "name": 概念名称（简洁明了）
- "description": 概念的简短描述
- "key_points": 讲解这个概念时需要覆盖的2-4个关键点

示例输出：
{{
  "concepts": [
    {{
      "name": "特征值",
      "description": "线性代数中，特征值是一个标量，满足Ax=λx",
      "key_points": ["特征值的定义", "特征方程", "特征值的性质"]
    }}
  ]
}}
"""

    messages = [
        {"role": "system", "content": "你是一个专业的教学设计师和知识提炼专家。"},
        {"role": "user", "content": prompt}
    ]
    
    try:
        response = await chat_completion(messages, temperature=0.3)
        data = json.loads(response)
        return data.get("concepts", [])
    except Exception as e:
        print(f"Concept extraction error: {e}")
        return []