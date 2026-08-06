from typing import List, AsyncGenerator, Dict, Any
import json
import textwrap
from sqlalchemy import text
from app.services.ai_service import stream_chat_completion_with_tools

# 定义工具
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "mark_concepts_mastered",
            "description": "当用户已经充分讲解了多个概念时，批量标记这些概念为已掌握。可以一次标记一个或多个概念。",
            "parameters": {
                "type": "object",
                "properties": {
                    "concepts": {
                        "type": "array",
                        "description": "已掌握的概念列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "concept_name": {
                                    "type": "string",
                                    "description": "概念的名称"
                                },
                                "summary": {
                                    "type": "string",
                                    "description": "用户讲解的简要总结"
                                }
                            },
                            "required": ["concept_name", "summary"]
                        }
                    }
                },
                "required": ["concepts"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mark_misconception",
            "description": "当用户的讲解存在明显的误解或错误时，标记该误解",
            "parameters": {
                "type": "object",
                "properties": {
                    "concept_name": {
                        "type": "string",
                        "description": "涉及误解的概念名称"
                    },
                    "misconception": {
                        "type": "string",
                        "description": "用户的具体误解内容"
                    },
                    "correction": {
                        "type": "string",
                        "description": "正确的理解"
                    }
                },
                "required": ["concept_name", "misconception", "correction"]
            }
        }
    },
    # ====== 虚拟图工具 ======
    {
        "type": "function",
        "function": {
            "name": "create_virtual_graph",
            "description": "创建一个包含多个节点的虚拟图，用于组织复杂的知识点结构。虚拟图可以包含多个相互关联的节点，形成完整的知识单元。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "虚拟图的名称"
                    },
                    "description": {
                        "type": "string",
                        "description": "虚拟图的简要描述"
                    },
                    "nodes": {
                        "type": "array",
                        "description": "虚拟图中的节点列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {
                                    "type": "string",
                                    "description": "节点标签（概念名称，不超过10个字）"
                                },
                                "properties": {
                                    "type": "array",
                                    "description": "节点属性列表，每个属性为二元组[和node的关系, 名称]。在integration level中，每个属性表现为一条边连接到子node，子node的label为名称。例如：[['定义', '对边/斜边'], ['值域', '[-1,1]']]会创建子nodes '对边/斜边'和'[-1,1]'，分别通过边'定义'和'值域'连接到主node。",
                                    "items": {
                                        "type": "array",
                                        "description": "二元组：[和node的关系, 名称]",
                                        "items": {
                                            "type": "string"
                                        },
                                        "minItems": 2,
                                        "maxItems": 2
                                    }
                                },
                                "content": {
                                    "type": "string",
                                    "description": "节点详细内容（用户讲解的完整内容，可选）"
                                }
                            },
                            "required": ["label"]
                        }
                    },
                    "edges": {
                        "type": "array",
                        "description": "虚拟图中节点之间的关联（必填，必须把所有节点连成网络，不允许孤立节点）。支持 parent(父子：子概念→父概念)、prerequisite(前置)、related(相关)、next(后续)、detail(细节)、example(示例)。沉淀时这些边会投影为真实图谱的边。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source_label": {
                                    "type": "string",
                                    "description": "源节点标签"
                                },
                                "target_label": {
                                    "type": "string",
                                    "description": "目标节点标签"
                                },
                                "relation": {
                                    "type": "string",
                                    "enum": ["prerequisite", "related", "next", "detail", "example", "parent"],
                                    "description": "关系类型：parent(父子：源是子的父概念)、prerequisite(前置)、related(相关)、next(后续)、detail(细节)、example(示例)"
                                }
                            },
                            "required": ["source_label", "target_label", "relation"]
                        }
                    },
                    "connected_nodes": {
                        "type": "array",
                        "description": "虚拟图要连接的真实图谱节点",
                        "items": {
                            "type": "object",
                            "properties": {
                                "virtual_node_label": {
                                    "type": "string",
                                    "description": "虚拟图中的节点标签"
                                },
                                "real_node_label": {
                                    "type": "string",
                                    "description": "真实图谱中的节点标签"
                                },
                                "connection_type": {
                                    "type": "string",
                                    "enum": ["contains", "references", "expands"],
                                    "description": "连接类型：contains(包含)、references(引用)、expands(扩展)"
                                }
                            },
                            "required": ["virtual_node_label", "real_node_label", "connection_type"]
                        }
                    }
                },
                "required": ["name", "nodes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_virtual_graphs",
            "description": "获取当前项目的所有虚拟图列表。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_virtual_graph",
            "description": "获取指定虚拟图的详细信息，包括所有节点和关联。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "虚拟图的名称"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_virtual_graph",
            "description": "更新已有的虚拟图，可以修改名称、描述、节点或关联。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要更新的虚拟图名称"
                    },
                    "description": {
                        "type": "string",
                        "description": "新的描述内容"
                    },
                    "nodes": {
                        "type": "array",
                        "description": "更新后的节点列表（每个节点的label不超过10个字）"
                    },
                    "edges": {
                        "type": "array",
                        "description": "更新后的关联列表"
                    }
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_virtual_graph",
            "description": "删除指定的虚拟图及其所有节点和关联。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要删除的虚拟图名称"
                    }
                },
                "required": ["name"]
            }
        }
    },
    # ====== RAG搜索工具 ======
    {
        "type": "function",
        "function": {
            "name": "search_virtual_graphs_rag",
            "description": "使用语义搜索查找相似的虚拟图。当你想要创建新的虚拟图时，先搜索是否已有相似的知识结构，避免重复创建。返回相似度最高的虚拟图列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询，可以是概念名称、知识点描述或用户讲解的内容"
                    },
                    "top_k": {
                        "type": "number",
                        "description": "返回相似度最高的前K个结果，默认5",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_virtual_graph_nodes",
            "description": "按关键词搜索指定虚拟图中的节点，返回前5个最匹配的结果。用于在虚拟图内部查找特定知识点。",
            "parameters": {
                "type": "object",
                "properties": {
                    "virtual_graph_name": {
                        "type": "string",
                        "description": "要搜索的虚拟图名称"
                    },
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词，可以是节点标签、描述或内容中的关键词"
                    },
                    "top_k": {
                        "type": "number",
                        "description": "返回最匹配的前K个节点，默认5",
                        "default": 5
                    }
                },
                "required": ["virtual_graph_name", "keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "当AI完成所有必要的工具调用(包括mark_concepts_mastered和虚拟图工具)后,调用此工具明确表示任务已完成。这是必须调用的结束工具,确保不会意外停止。",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "本次响应的简要总结,说明已完成的工作"
                    }
                },
                "required": ["summary"]
            }
        }
    }
]

class TeachingAgent:
    def __init__(self, db, session_id: str):
        self.db = db
        self.session_id = session_id

    async def _get_conversation_history(self) -> List[dict]:
        """获取对话历史"""
        result = await self.db.execute(
            text("SELECT role, content FROM messages WHERE session_id = :session_id AND is_active = 1 ORDER BY created_at"),
            {"session_id": self.session_id}
        )
        messages = result.fetchall()
        return [{"role": msg[0], "content": msg[1]} for msg in messages]

    async def process_user_input(self, user_input: str) -> AsyncGenerator[Dict[str, Any], None]:
        """处理用户输入，流式返回响应和工具调用"""
        if not user_input.strip():
            yield {"type": "text", "content": "请输入内容开始讲解。"}
            return

        history = await self._get_conversation_history()

        # 获取未掌握的概念列表
        concepts_result = await self.db.execute(
            text("SELECT name, status FROM concepts WHERE session_id = :session_id"),
            {"session_id": self.session_id}
        )
        concepts = concepts_result.fetchall()
        
        # 构建概念状态列表
        concept_status_list = []
        for concept in concepts:
            name, status = concept
            if status == 'learning':
                concept_status_list.append(f"- {name}（未掌握）")
            elif status == 'mastered':
                concept_status_list.append(f"- {name}（已掌握）")
        
        concept_status_str = "\n".join(concept_status_list) if concept_status_list else "暂无概念记录"

        # 构建固定的系统提示（IMMUTABLE PREFIX）- 不包含动态内容，提高缓存命中率
        system_prompt = textwrap.dedent("""
        # Integration Level 知识图谱规范
        
        ## 节点 (Node)
        节点表示知识图谱中的概念单元，**只存储名称和掌握度**，不存储详细内容。
        - label: 节点名称（必填，简短准确，**不超过10个字**）
        - mastery_score: 掌握程度 0.0-1.0（默认 0）

        **重要：节点的详细内容应该在虚拟图（VirtualGraph）中存储，而不是在节点本身。**
        节点只作为知识图谱的一个"标签"或"指针"，通过图谱图表展示概念关系。

        ### 创建规范（必须严格遵守）
        1. 名称精确简洁，**不超过10个字**（如"sin函数"，不要"正弦函数定义及性质"）
        2. **不要创建description参数**，节点不存储详细内容
        3. mastery_score 由系统自动管理，创建节点时使用默认值 0，无需手动设置
        
        ## 虚拟图 (VirtualGraph)
        虚拟图用于存储知识点的完整结构和详细内容。
        - 可以包含多个节点（每个节点有label、properties、content）
        - 可以包含节点之间的关联关系
        - 可以连接到真实图谱中的节点

        **节点属性（properties）格式：**
        - 每个节点的properties字段是一个二元组列表：[[和node的关系, 名称], ...]
        - 例如：[['定义', '对边/斜边'], ['值域', '[-1,1]'], ['周期', '2π']]
        - 在integration level沉淀后，每个二元组表现为：
          - 创建一个子node，label为名称（如"对边/斜边"、"[-1,1]"）
          - 创建一条边，从主node连接到子node，relation为和node的关系（如"定义"、"值域"）
          - 子node的初始掌握度为0.0
          - 主node的掌握度为所有子node掌握度的平均值

        **使用场景：**
        - 当用户讲解一个复杂知识点时，创建虚拟图来组织完整内容
        - 虚拟图的每个节点可以通过properties字段定义多个子node关系
        - 虚拟图节点可以连接到知识图谱中的真实节点
        
         ## 关联 (Edge)
        关联表示概念间的逻辑关系，**是构建统一结构网络的核心，必须为每个概念建立关联**。
        关系类型：
        - prerequisite: 前置关系（A → B：A是B的前置知识）
        - related: 相关关系（A → B：A与B有联系但非直接依赖）
        - parent: 父概念关系（A → B：A是B的父概念，即B是A的子概念）
        
        ### 关联创建规范（必须严格遵守）
        1. **虚拟图创建时必须包含 edges 字段**（不允许省略或为空），把虚拟图内所有节点连成一个网络：
           - 每个节点至少与一个其他节点有边（parent / prerequisite / related）
           - 不要创建孤立的节点
        2. 识别父子概念关系时，必须用 parent 边连接（子 → 父）
        3. 识别先后依赖时，必须用 prerequisite 边连接
        4. 无法确定层级关系时，用 related 边连接
        5. 沉淀时，虚拟图内的边会**原样投影**到真实图谱，节点间关系会保留在最终图谱中
        
        ### 层级结构示例（必须识别父子关系）
        ```
        三角函数（父概念）
          ├─ sin函数（子概念）  parent: sin函数 → 三角函数
          ├─ cos函数（子概念）  parent: cos函数 → 三角函数
          ├─ tan函数（子概念）  parent: tan函数 → 三角函数
        ```
        重要：识别父子概念关系，使用 parent 关系从子概念指向父概念（子 → 父）。
        
        ## 掌握度规则（系统自动管理）
        - 初始掌握度为 0
        - 完成教学标记为已掌握时，系统自动将掌握度设为 30%（0.3）
        - 每次习题答对，掌握度上调 5%（0.05）
        - 掌握度达到 80%（0.8）时，节点显示深蓝色高亮
        - 创建节点时不要手动设置 mastery_score，使用默认值 0
        
        # Teaching 角色设定
        
        你是一个积极的学习者，正在通过"教AI学习"的方式巩固自己的知识。
        用户会向你讲解各种概念，你需要：
        1. 认真倾听并理解用户的讲解
        2. 对用户的讲解给予肯定和反馈
        3. 提出深入的问题帮助用户进一步思考
        4. 语言要自然、友好，不要使用固定模板
        
        追问策略（非常重要）：
        - 当用户的讲解比较简短或模糊时，必须追问以帮助用户深入思考
        - 追问应该针对用户讲解中的关键点，例如：
          * "你能举个例子说明这个概念在实际中如何应用吗？"
          * "这个概念和之前学过的哪些知识有关联？"
          * "为什么会出现这种情况？背后的原理是什么？"
          * "如果条件改变了，结果会怎样？"
          * "这个概念的限制条件是什么？在什么情况下不适用？"
        - 追问要循序渐进，从简单到复杂，帮助用户逐步深入
        - 每次追问都应该基于用户的上一轮回答，形成连贯的对话
        
        判断概念是否已掌握的标准：
        - 用户能够清晰定义概念的核心含义
        - 用户能够解释概念的工作原理或机制
        - 用户能够举出恰当的例子说明应用场景
        - 用户能够说明概念的限制条件或适用范围
        - 用户能够将概念与其他相关知识建立联系
        - 只有当以上条件都满足时，才调用mark_concepts_mastered工具
        
        工具调用规则（非常重要）：
        - mark_concept_mastered：只有当用户对某个概念的讲解清晰、完整、正确时，才调用此工具
        - mark_misconception：当用户的讲解存在明显错误或误解时，必须调用此工具
        - 不要只在文本中说"已标记概念为已掌握"，而是通过调用工具来实现
        - 如果用户讲解的概念不在列表中，也可以调用工具创建新概念
        - 在用户讲解不够充分时，不要急于标记为已掌握，而是继续追问
        - task_complete：这是必须调用的结束工具！在完成所有必要的工具调用(包括mark_concepts_mastered和虚拟图工具)后，必须调用此工具明确表示任务已完成，否则系统会误以为任务未完成而继续等待
        
        虚拟图使用流程（核心架构）：
        - 虚拟图是AI的内部数据结构，用于存储知识点的完整结构和详细内容
        - 当用户讲解复杂知识点时，应创建虚拟图来组织完整内容：
          1. 先使用 search_virtual_graphs_rag 搜索是否已有相似的知识结构
          2. 如果没有相似结构，调用 create_virtual_graph 创建虚拟图
             - 在虚拟图中创建多个节点，每个节点包含label、description、content
             - label: 简洁精确的名称，**不超过10个字**（如"sin函数"，不要"正弦函数定义"）
             - description: 节点简要描述（一句话核心）
             - content: 用户讲解的完整内容
             - **必须创建虚拟图内部的节点关联（edges）**，把节点连成网络，不允许孤立节点
          3. 虚拟图创建后，内容会自动显示在teaching右侧沉淀栏供用户查看
          4. 用户可以选择将虚拟图节点推送到Integration Level（真实图谱）
          5. Integration Level只存储节点名称，详细内容保持在虚拟图中
          6. **虚拟图内的 edges 会在沉淀时投影为真实图谱的边**，形成统一结构网络
        - 可以使用 search_virtual_graph_nodes 在虚拟图内部查找特定知识点
        - 调用 get_virtual_graphs 查看当前项目的所有虚拟图
        - 调用 get_virtual_graph 查看指定虚拟图的详细信息
        
        层级关系识别（重要）：
        - 识别父子概念关系，例如：
          * 如果用户讲解"sin函数"，应识别它属于"三角函数"
          * 如果用户讲解"线性回归"，应识别它属于"机器学习算法"
        - 在虚拟图中创建节点关联时，必须使用parent关系表示父子关系，用prerequisite表示前置依赖
        
        注意事项：
        - mark_concepts_mastered 是必须调用的，否则学习进度不会被记录！
        - 由于API限制，请一次只调用一个工具，收到结果后再调用下一个工具
        - 虚拟图是AI的工作空间，Integration Level是最终的知识沉淀层
        - 详细内容应该在虚拟图中以图的形式存储，Integration Level只存储节点名称
        """).strip()

        # 构建动态内容（VOLATILE SCRATCH）- 放在对话历史的最后
        current_prompt = textwrap.dedent(f"""
        当前概念状态：
        {concept_status_str}

        用户刚刚说了：{user_input}

        请根据用户的输入进行回应。

        重要提醒：
        1. 追问策略：
           - 如果用户的讲解比较简短或模糊，必须追问以帮助用户深入思考
           - 追问应该针对用户讲解中的关键点，循序渐进
           - 每次追问都应该基于用户的上一轮回答，形成连贯的对话
        
        2. 工具调用规则：
           - 只有当用户对某个概念的讲解清晰、完整、正确时（满足5个标准），才调用mark_concept_mastered工具
           - 调用mark_concept_mastered工具后，必须同步调用工具，在虚拟图中完成记录。
           - 如果用户的讲解存在误解，必须调用mark_misconception工具
           - 不要在文本中说"已标记概念"，而是通过调用工具来实现
           - 在用户讲解不够充分时，不要急于标记为已掌握，而是继续追问
           - **重要**：完成所有必要的工具调用后，必须调用task_complete工具明确表示任务已完成！
        
        3. 虚拟图创建规范（必须严格遵守）：
           - 创建虚拟图时：
             * name: 虚拟图的名称（简洁描述知识点主题）
             * nodes: 每个节点包含label、description、content
             * label: 简洁精确的名称，**不超过10个字**（如"sin函数"，不要"正弦函数定义及性质"）
             * description: 一句话核心描述（不要冗长细节）
             * content: 用户讲解的完整内容
             * edges: **必填**，节点之间的关联，必须把节点连成网络（parent父子 / prerequisite前置 / related相关），不允许孤立节点
           - 创建虚拟图前，先使用search_virtual_graphs_rag搜索是否已有相似结构
           - 可以使用search_virtual_graph_nodes在虚拟图内部查找特定知识点
           - 沉淀到Integration Level时，虚拟图内部的edges会原样投影为真实图谱的边，因此必须在创建时就规划好完整的节点网络
        
        请根据以上信息进行回应，并在适当的时候调用工具。最后一定要调用task_complete工具结束！
        """).strip()

        # 组合消息列表：固定系统提示 + 对话历史 + 动态内容
        # 这样可以提高缓存命中率，因为固定系统提示的前缀每次都相同
        messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": current_prompt}]

        # 流式调用AI
        # print(f"Starting stream_chat_completion_with_tools...")
        async for chunk in stream_chat_completion_with_tools(messages, TOOLS):
            # 调试输出已关闭
            # print(f"Yielding chunk from teaching_agent: {chunk}")
            yield chunk
        # print(f"Finished stream_chat_completion_with_tools")

    async def process_tool_results(self, tool_messages: list, reasoning_content: str = ""):
        """处理工具结果，继续生成AI响应
        
        Args:
            tool_messages: 工具结果消息列表
            reasoning_content: 之前的reasoning_content（OpenAI thinking模式要求必须传回）
        """
        # 获取对话历史
        history_result = await self.db.execute(
            text("SELECT role, content FROM messages WHERE session_id = :session_id AND is_active = 1 ORDER BY created_at"),
            {"session_id": self.session_id}
        )
        history = [{"role": row[0], "content": row[1]} for row in history_result.fetchall()]
        
        # 构建一个临时的 assistant message 包含 tool_calls
        # 这样 OpenAI API 才能正确关联 tool message
        tool_calls_for_message = []
        for msg in tool_messages:
            tool_calls_for_message.append({
                "id": msg.get("tool_call_id", f"call_{msg['name']}"),
                "type": "function",
                "function": {
                    "name": msg["name"],
                    "arguments": "{}"
                }
            })
        
        # 重要：OpenAI thinking模式要求在后续调用中包含之前的reasoning_content
        assistant_message_with_tools = {
            "role": "assistant",
            "content": "",  # 可以是空字符串，或者之前的响应文本
            "tool_calls": tool_calls_for_message
        }
        
        # 如果有reasoning_content，必须添加到assistant message中
        if reasoning_content:
            assistant_message_with_tools["reasoning_content"] = reasoning_content
            print(f"Passing reasoning_content to API: {len(reasoning_content)} chars")
        
        # 构建消息列表：历史 + assistant(tool_calls) + tool messages
        messages = history + [assistant_message_with_tools] + tool_messages
        
        print(f"Processing tool results, calling AI again...")
        async for chunk in stream_chat_completion_with_tools(messages, TOOLS):
            # 同时 yield text 和 tool_call chunk，包括 reasoning chunk
            yield chunk
        print(f"Finished processing tool results")

    async def start_session(self, concept_name: str) -> str:
        return f"好的，让我们开始学习【{concept_name}】。请先试着用自己的话讲解这个概念。"