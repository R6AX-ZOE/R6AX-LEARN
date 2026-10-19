# Teaching Level（F-07 ~ F-11、F-34）开发记录与探究性学习报告素材

> 本文档整合 R6AX:/Learn 中 **Teaching Level（教 AI 复习）** 功能的开发成果、
> 设计依据与文献调研过程，供撰写探究性学习报告使用。
> 对应功能编号：F-07（Teaching 会话）、F-08（SSE 流式输出）、F-09（Misconception 标记）、
> F-10（Concept 标记）、F-11（Teaching → Integration 沉淀）、F-34（Integration 虚拟图）。
> 上游：`docs/input_to_teaching.md`（F-06 概念提取）；下游：`docs/practice.md`（F-12 ~ F-15）、
> `docs/integration_guide.md`（沉淀规范）。
> 涉及实现：`app/services/teaching_agent.py`（角色 Prompt 与工具定义）、
> `app/routers/teaching.py`（会话 / SSE / 工具循环 / 沉淀）、
> `app/services/teaching_streams.py`（流与 HTTP 解耦）、
> `app/services/ai_service.py:44`（流式工具调用 + 思考模式）、
> `app/templates/teaching/session.html`（会话界面）。

---

## 1. 开发成果总览

### 1.1 功能清单（已完成并验证）

| 功能 | 说明 | 对应文件 |
|------|------|---------|
| Teaching 会话 | 从概念进入"教 AI"会话；首条 assistant 消息邀请用户用自己的话讲解 | `app/routers/teaching.py:798` |
| SSE 流式输出 | 事件类型 `thinking / text / concept / misconception / tool_call / task_complete / done / error`，逐块渲染 | `app/routers/teaching.py:1185`、`app/templates/teaching/session.html:975` |
| 流与连接解耦 | 生成在后台任务中进行，刷新 / 断线重连后先回放 `partial_text`，不丢回复 | `app/services/teaching_streams.py`、`teaching.py:1080` |
| 概念掌握标记 | AI 调用 `mark_concepts_mastered`，概念 `status` 置 `mastered`，关联节点掌握度同步为 0.3 | `app/services/teaching_agent.py:8`、`teaching.py:430` |
| 误解标记 | AI 调用 `mark_misconception`，记录用户主张 + 正确理解，前端出现误解标签 | `app/services/teaching_agent.py:40`、`teaching.py:487` |
| 多轮工具调用循环 | 工具结果回传 AI 续跑，直到 `task_complete`（上限 50 轮），保证工具调用不被吞 | `teaching.py:692`、`teaching.py:733` |
| 分支编辑 | 改写某条用户消息后删除其后的消息并重新生成回复 | `teaching.py:975` |
| 会话进度 | `completed/total` 进度条；全部掌握后会话自动置 `completed` | `teaching.py:1212`、`teaching.py:881` |
| 概念沉淀（F-11） | 勾选已掌握概念 → 挂载式合并进 Integration（同名复用、最近邻挂载、虚拟图节点与内部边同步投影） | `teaching.py:1238`、`app/services/graph_mount.py` |
| 虚拟图（F-34） | AI 在会话中产出结构化"虚拟图"（节点 + properties + 内部边 + 与真实图关联 + RAG 检索）；沉淀时内部边投影为真实边 | `teaching_agent.py:65`、`teaching.py:111`、`teaching.py:144` |
| Practice → Teaching（F-16） | 错题累积触发新会话，标题"复习：{概念名}"，错题背景写入 system 消息 | `app/routers/practice.py:42`、`docs/PRD.md` §4.4 |
| 思考模式 | `thinking` 开启 + `reasoning_effort=high`，reasoning 全量回传给后续调用 | `app/services/ai_service.py:44-63,114` |

### 1.2 关键设计决策

1. **AI 是"聪明的学生"，不是老师**：用户负责讲解，AI 负责倾听、肯定、追问；按 PRD §9.1，
   AI **不主动给答案**，即使被要求代答也只会请用户讲给自己听（防御性引导 Prompt，`teaching_agent.py:436-446`）。
2. **追问不是固定问卷，而是基于上一轮回答的对话追问**：Prompt 给出五类追问句式锚点
   （应用举例 / 与已学联系 / 背后原理 / 条件改变 / 限制边界），要求循序渐进、形成连贯对话
   （`teaching_agent.py:425-434`）。
3. **掌握判定五标准同时充当"讲解质量量规"**：能定义、能解释机制、能举例、能说明边界、能建立联系，
   五条全部满足才允许调用工具标记（`teaching_agent.py:448-454`）；该标准与 F-06 `key_points` 维度同构
   （见 `docs/input_to_teaching.md` §2.4）。
4. **误解"先记录、再引导"**：`mark_misconception` 保存用户原话与正确理解，前端即时显示标签；
   正文继续用追问引导自我修正，符合概念转变理论中"先暴露冲突再重建"的顺序。
5. **固定系统提示 + 动态草稿的消息结构**：不变量（角色、规范、五标准）放在 system prompt 前缀提高缓存命中率，
   每轮变化的概念状态与用户输入追加在最后（`teaching_agent.py:347-541`）。
6. **生成与 HTTP 生命周期解耦**：SSE 只是订阅通道，后台任务结束后必然落库，详见 §5.2。
7. **虚拟图作为"中间层"**：教学对话产生的详细结构先落虚拟图，用户确认后才沉淀到 Integration 真实图谱，
   避免 AI 生成内容直接污染长期知识图谱（F-34/F-35，`teaching_agent.py:464-480`）。
8. **工程边界（可写入报告的局限）**：模型 deepseek-v4-flash、`temperature=0.7`、`max_tokens=4096`、
   `reasoning_effort=high`；Prompt 固定中文不随 locale 切换；掌握即跳到 0.3 掌握度是产品启发式，非实证标定。

---

## 2. 理论定位：为什么"教 AI"能学

Teaching Level 的机制可概括为：**让学习者把知识生成一遍，并由一个只提问、不代答的对话伙伴持续检验其完整性。**
本节按该机制涉及的认知与教学理论逐一给出依据及其对系统的启示。

### 2.1 教中学与门徒效应（Learning by Teaching; Protégé Effect）

Bargh & Schul (1980) 发现"准备向他人讲解"本身即可提升学习者的认知组织；
Fiorella & Mayer (2013, 2014) 的实验区分了**教学预期（teaching expectancy）** 与**实际讲解（explaining）**，
发现两者均有益、实际讲解收益更大；Fiorella & Mayer (2015) 将"教学"列为八大生成学习策略之一；
Kobayashi (2019) 对 28 项研究的元分析确认"准备教 + 实际教"显著优于普通学习（Hedges' g 分别为 0.35 与 0.56），
且当学习者预期教学是**交互式活动**时收益更大。
Chase et al. (2009) 用"可教代理（teachable agent）"证明：**向一个虚拟学生讲解会产生门徒效应**，
学习者愿意投入更多努力。Duran (2017) 的综述进一步将其归纳为可操作的教学机制。

- 对 Teaching 的启示：AI 扮演"聪明的学生"（`teaching_agent.py:418-423`），用户是讲解者；
  这直接对应本产品"不主打 AI 教你、主打你教 AI"的定位（PRD §1.2）。
- 对应实现：首条消息邀请"用自己的话讲解这个概念"（`teaching.py:812-817`）；
  AI 只追问、不代讲（防御性引导）。

### 2.2 生成效应与自我解释（Generation Effect; Self-explanation）

Slamecka & Graf (1978) 的生成效应表明：自己生成的信息比阅读他人给出的信息记得更牢。
Chi et al. (1989, 1994) 发现**自我解释（self-explanation）** 的深度是理解差异的关键，
并通过提示（prompt）可以人为诱发自我解释、提升理解；Bisra et al. (2018) 的元分析
（64 篇研究报告、69 个效应量，总体加权效应量 g = 0.55）确认自我解释提示对学习有中等以上效应。

- 对 Teaching 的启示：对话中的每一轮回答都是一次"被迫生成"；
  追问句式本质上就是自我解释提示的对话化实现。
- 对应实现：追问策略五类问题（`teaching_agent.py:427-432`）；动态 Prompt 中的追问提醒（`teaching_agent.py:504-508`）。

### 2.3 检索练习（Retrieval Practice / Testing Effect）

Roediger & Karpicke (2006) 发现提取练习比重复阅读带来更好的长时保持；
Karpicke & Blunt (2011) 进一步表明检索练习优于概念图复习（在事实与推断题上）。
Dunlosky et al. (2013) 把"练习测试"与"分散练习"列为高效力学习技术。

- 对 Teaching 的启示：会话中不把笔记原文摆给用户看，而是要求凭记忆重构讲解；
  "讲出来"是一次高强度的自由回忆测验。
- 对应实现：会话上下文只含对话历史与概念状态，不注入笔记全文（`teaching_agent.py:312-345`）。

### 2.4 合意困难与"不流畅"（Desirable Difficulties）

Bjork (1994)、Bjork & Bjork (2011) 指出：带来即时表现收益的"流畅"条件往往损害长期保持，
适度增加提取与处理的难度（desirable difficulties）反而促进学习。Koriat & Bjork (2005)
发现学习者会因材料流畅而产生**能力错觉（illusion of competence）**。

- 对 Teaching 的启示：AI 不把答案嚼碎给出，反而追问"为什么/举个例子/边界在哪"，
  用不适感逼迫精细化加工；"讲不出来"正是能力错觉的破灭点。
- 对应实现：防御性引导明确"不要因为用户捣乱就替他把知识点讲完"（`teaching_agent.py:443-446`）；
  PRD §9.1"不主动给答案（除非用户反复卡住）"。

### 2.5 苏格拉底式提问（Socratic Questioning）

Paul & Elder (2006) 将苏格拉底提问归纳为概念澄清、探询假设、追问理由与证据、
变换视角、推演后果、对问题本身反思六类；Overholser (1993) 讨论了系统化提问在心理治疗中的引导机制。

- 对 Teaching 的启示：追问句式与上述类别几乎一一对应（见 §3 映射表）。
- 对应实现：`teaching_agent.py:427-432` 的五类句式 + `key_points` 的定义/原理/例子/适用条件/联系维度。

### 2.6 辅导对话与支架（Tutoring Dialogue; Scaffolding）

Graesser & Person (1994) 与 Graesser, Person & Magliano (1995) 对真人辅导对话的分析表明：
高效辅导以**提问、反馈、提示与脚手架**为主，而非长篇讲授；VanLehn (2011) 的综述指出
辅导效果的关键在"互动程度"；Wood, Bruner & Ross (1976) 提出支架（scaffolding）概念，
Vygotsky (1978) 的最近发展区（ZPD）说明支架应落在学习者现有水平之上一步。

- 对 Teaching 的启示：Prompt 要求"每次追问都应基于用户的上一轮回答，循序渐进，从简单到复杂"
  （`teaching_agent.py:433-434`），即对话式支架而非静态问卷。
- 对应实现：动态 Prompt 注入未掌握概念清单，追问目标从"当前未掌握"中选取
  （`teaching_agent.py:330-345, 497-500, 520`），把问题定位在 ZPD 内。

### 2.7 形成性反馈（Formative Feedback）

Black & Wiliam (1998) 的证据综述确立了形成性评价对学习的促进作用；
Hattie & Timperley (2007) 提出有效反馈要回答"去哪里、现在在哪、下一步怎么走"；
Butler & Roediger (2008) 发现即时反馈能增强测试效应并削弱错误答案的负面影响。

- 对 Teaching 的启示：AI 对每轮讲解先给予肯定与即时标记（concept / misconception 事件），
  再用追问指出"下一步"；误解标签就是立即的纠正性反馈。
- 对应实现：SSE `concept` / `misconception` 事件（`teaching.py:471-502`）、
  前端标签即时渲染（`session.html:1004-1020`）、进度条（`teaching.py:1216-1236`）。

### 2.8 概念转变与误解诊断（Conceptual Change）

Posner, Strike, Hewson & Gertzog (1982) 提出概念转变需要四个条件：对原有概念不满、
新概念可理解、合理、有效；Chi (2008) 区分了信念修正、心理模型转换与类别迁移三类概念转变。
误解研究强调：误解不会因为"被告知正确说法"而自动消失，需要先激活并面对冲突。

- 对 Teaching 的启示：系统把"用户说得不对"显式记录为 Misconception（主张 + 正确理解 + resolved 标记），
  并在对话中持续追问，让用户自己说出修正后的解释，而不是只给标准答案。
- 对应实现：`mark_misconception` 工具（`teaching_agent.py:40-64`、`teaching.py:487-503`）、
  误解标签与侧栏列表（`session.html:654-660`）。

### 2.9 元认知与学习监控（Metacognition）

Flavell (1979) 提出元认知（对自身认知的认知与监控）；Nelson & Narens (1990) 给出元记忆的监控—控制框架；
Bjork, Dunlosky & Kornell (2013) 指出自我调节学习常被能力错觉误导。

- 对 Teaching 的启示：讲不出来即暴露"知道感"与"能讲出"之间的落差；
  会话进度（已掌握/总数）与概念标签把"我到底会不会"外化为可见状态。
- 对应实现：`concepts` 状态列表注入每一轮 Prompt（AI 以此规划追问）、
  进度条与自动 completed 判定（`teaching.py:881-885, 1216-1236`）。

### 2.10 知识外化与概念图（Knowledge Externalization; Concept Maps）

Novak & Gowin (1984) 的概念图方法强调概念节点之间要**带标签的关系**；
Ausubel (1968) 的意义学习强调新知识须与已有认知结构建立实质联系；
Bereiter & Scardamalia (1987) 区分"知识陈述（knowledge telling）"与"知识转化（knowledge transforming）"——
前者只是复述，后者才是重组与建构。

- 对 Teaching 的启示：虚拟图要求节点之间必须有 `parent / prerequisite / related / next / detail / example` 边
  （`teaching_agent.py:113-135`），迫使 AI 与用户把讲解重组成结构网络，而非零散段落；
  沉淀进 Integration 后形成长期可复用图谱。
- 对应实现：虚拟图工具（`teaching_agent.py:65-238`）与挂载式合并（`app/services/graph_mount.py`）。

### 2.11 可教代理与学习伙伴（Teachable Agents; Learning Companions）

Chan & Baskin (1988) 最早提出"学习伙伴（learning companion）"范式；
Biswas et al. (2005) 的 Teachable Agents 系列研究证明：学生教一个虚拟角色时，
会更主动地组织知识、监控理解。Palincsar & Brown (1984) 的互惠教学
（提问、澄清、总结、预测）也说明"问与答的角色轮换"本身即教学策略。

- 对 Teaching 的启示：本系统的 AI 是一个**只提问的可教代理**，其"理解"由用户负责建立；
  AI 的追问相当于互惠教学中的提问与澄清环节。
- 对应实现：角色设定（`teaching_agent.py:416-423`）与工具化标记（用"是否掌握"驱动对话终止条件）。

### 2.12 相关但不直接实现的理论

- 交错练习与间隔重复（Rohrer 2012; Benjamin & Tullis 2010）：由 Practice Level 承担，见 `docs/practice.md`。
- 认知负荷与分段（Sweller 1988; Mayer 2009）：追问"一次一个焦点"隐含分段原则，但系统未显式限制每轮问题数量。
- 刻意练习（Ericsson et al. 1993）：可作为"高频追问 + 即时反馈"的上位解释，但系统无难度自适应。
- 心流 / 动机（Csikszentmihalyi 1990）：门徒效应的动机成分（Chase et al. 2009）部分覆盖。

---

## 3. 理论 → 实现映射表（调研 → Prompt/代码）

| 理论依据 | 在 Teaching 实现中的体现 | 代码位置 |
|---------|------------------------|---------|
| 教中学 / 门徒效应（Bargh & Schul 1980; Fiorella & Mayer 2013; Kobayashi 2019; Chase et al. 2009） | 用户向"聪明的学生"讲解；AI 是学习者不是老师 | `teaching_agent.py:416-423` |
| 生成效应 / 自我解释（Slamecka & Graf 1978; Chi et al. 1989; Bisra et al. 2018） | 首条消息要求"用自己的话讲解"；追问即自我解释提示 | `teaching.py:812-817`、`teaching_agent.py:425-434` |
| 检索练习（Roediger & Karpicke 2006; Dunlosky et al. 2013） | 不注入笔记原文，强制凭记忆重构讲解 | `teaching_agent.py:312-345` |
| 合意困难（Bjork 1994; Bjork & Bjork 2011） | AI 不主动给答案；防御性引导拒绝代答 | `teaching_agent.py:436-446` |
| 苏格拉底六类问题（Paul & Elder 2006） | 五类追问句式：举例应用 / 已学联系 / 背后原理 / 条件改变 / 限制边界 | `teaching_agent.py:427-432` |
| 辅导对话与支架（Graesser & Person 1994; Wood et al. 1976; VanLehn 2011） | "基于上一轮回答、循序渐进、形成连贯对话" | `teaching_agent.py:433-434, 504-508` |
| 最近发展区（Vygotsky 1978） | 每轮注入未掌握概念清单，追问目标取自其中 | `teaching_agent.py:330-345, 497-500, 520` |
| 形成性反馈（Black & Wiliam 1998; Hattie & Timperley 2007; Butler & Roediger 2008） | 肯定 + 即时 concept / misconception 标记 + 继续追问 | `teaching.py:471-502`、`session.html:1004-1020` |
| 概念转变（Posner et al. 1982; Chi 2008） | 记录误解主张与正确理解，先暴露冲突再引导修正 | `teaching_agent.py:40-64`、`teaching.py:487-503` |
| 元认知与监控（Flavell 1979; Nelson & Narens 1990; Koriat & Bjork 2005） | 概念状态外显、进度条、全掌握后会话自动完成 | `teaching.py:881-885, 1216-1236` |
| 概念图 / 知识转化（Novak & Gowin 1984; Bereiter & Scardamalia 1987） | 虚拟图强制节点带关系边；沉淀为真实图谱结构 | `teaching_agent.py:113-135`、`graph_mount.py` |
| 可教代理 / 学习伙伴（Chan & Baskin 1988; Biswas et al. 2005） | AI 角色为积极学习者；以"是否掌握"为对话目标 | `teaching_agent.py:416-423` |
| 掌握五标准（概念教学结构，见 `docs/input_to_teaching.md` §2.4） | 定义 / 机制 / 例子 / 边界 / 联系，全部满足才允许标记 | `teaching_agent.py:448-454` |
| 工程约束（结构化工具调用） | 工具调用结果落库 + XML artifact 可见；`task_complete` 强制收敛 | `teaching_agent.py:8-305`、`teaching.py:692-796` |

> 报告写作提示：表中最右列即"理论条目 → 可观测实现"的因果链，可直接作为报告的"设计—理论一致性"证据；
> 注意区分**已在 Prompt 中显式写入的理论**（苏格拉底、五标准、防御性引导）与
> **仅作为设计背景的理论**（检索练习、合意困难），后者系统未做显式机制约束。

---

## 4. Prompt / Agent 设计说明

### 4.1 消息结构：不变量 + 历史 + 动态草稿

`TeachingAgent.process_user_input`（`teaching_agent.py:321`）组装：

```
[system] 固定系统提示（Integration 规范 + 角色设定 + 追问策略 + 防御性引导
         + 掌握五标准 + 工具规则 + 虚拟图流程 + 层级识别）
[history] 会话消息历史（仅 is_active=1，按时间排序）
[user]   动态草稿（当前概念状态 + 用户刚说的话 + 本轮提醒）
```

- 固定前缀可提高 KV 缓存命中率（`teaching_agent.py:539-541` 注释）；
- 概念状态以"未掌握 / 已掌握"列表形式每轮刷新（`teaching_agent.py:336-345`），
  AI 据此选择追问对象；
- 动态草稿重复强调追问策略、工具规则、防御性引导与虚拟图规范（`teaching_agent.py:496-537`），
  属于"关键约束二次注入"的工程实践。

### 4.2 追问策略（理论对齐）

Prompt 中显式列出的追问句式与理论来源：

| Prompt 句式（`teaching_agent.py:427-432`） | 对应理论类别 |
|-------------------------------------------|-------------|
| "你能举个例子说明这个概念在实际中如何应用吗？" | 概念澄清 + 具体例子（Paul & Elder；Rawson et al. 2014） |
| "这个概念和之前学过的哪些知识有关联？" | 变换视角 / 已学锚定（Paul & Elder；Ausubel 1963） |
| "为什么会出现这种情况？背后的原理是什么？" | 追问理由与证据（Paul & Elder） |
| "如果条件改变了，结果会怎样？" | 推演后果与影响（Paul & Elder） |
| "这个概念的限制条件是什么？在什么情况下不适用？" | 对问题本身的反思 / 适用边界（Paul & Elder；概念教学结构） |

### 4.3 掌握判定五标准（"讲解质量量规"）

`teaching_agent.py:448-454` 要求五条全部满足才允许调用 `mark_concepts_mastered`：

1. 能清晰定义概念的核心含义；
2. 能解释工作原理或机制；
3. 能举出恰当例子说明应用场景；
4. 能说明限制条件或适用范围；
5. 能与其他相关知识建立联系。

五标准与概念教学结构（定义性属性 / 正反例 / 适用条件）以及 F-06 的 `key_points` 维度一致，
可作为报告中对"用户讲解质量"进行 0~2 分编码的量规来源（见 §6.2）。

### 4.4 误解标记与概念标记的工具语义

| 工具 | 触发条件 | 落库效果 | 代码位置 |
|------|---------|---------|---------|
| `mark_concepts_mastered` | 五标准全满足 | `concepts.status='mastered'`；若已有节点则 `mastery_score=0.3`；SSE `concept` | `teaching_agent.py:11-39`、`teaching.py:430-485` |
| `mark_misconception` | 讲解存在明显错误 | 写入 `misconceptions(user_claim, ai_correction, resolved=False)`；SSE `misconception` | `teaching_agent.py:40-64`、`teaching.py:487-503` |
| `task_complete` | 完成所有必要工具调用后 | 结束工具循环，防止"AI 意外停止"；SSE `task_complete` | `teaching_agent.py:288-304`、`teaching.py:705-708` |

> 注意：`mark_concepts_mastered` 若概念名不在当前会话概念列表中会返回错误并附未掌握清单
> （`teaching.py:444-450`）；这使概念成为"封闭集合"，与 F-06 的项目级去重共同防止概念发散。

### 4.5 防御性引导（对抗无效对话）

Prompt 预判了五类无效输入（闲聊、乱码、捣乱、要求代答、角色扮演）并规定三件事
（`teaching_agent.py:436-446`、动态版 `518-522`）：

1. 一句话友好接住，不说教；
2. 立刻从"未掌握概念"中选一个，追问一个具体知识点；
3. 最迟一轮内回到知识点讲解；禁止因此调用标记工具或替用户把知识讲完。

### 4.6 虚拟图：把讲解外化为结构

工具契约（`teaching_agent.py:65-238`）要求：

- 节点 `label ≤ 10 字`，`properties` 为 `[关系, 名称]` 二元组列表；
- `edges` 必填，支持 `parent / prerequisite / related / next / detail / example`，**不允许孤立节点**；
- 创建前先用 `search_virtual_graphs_rag` 检索项目内已有结构，避免重复；
- 沉淀时内部边原样投影到真实图谱（`sync_virtual_graph_to_real`），
  实现"虚拟图 = 结构草稿、Integration = 长期知识"的分层。

### 4.7 可调优注意事项（不改变代码逻辑的前提下）

- Prompt 文本可继续迭代（git 版本可回溯），但**工具名、参数 schema、JSON 输出契约不要改**，
  否则 `_execute_tool` / `_run_tool_batch` 的解析会失效；
- 五标准、追问句式、防御性引导是三个可独立消融（ablation）的 Prompt 组件，
  适合作为报告中的对比实验自变量；
- 记录每次实验的 Prompt 全文与模型参数（temperature / reasoning_effort / max_tokens），
  因为思考模式下输出具有随机性；
- 若要研究"给不给答案"的边界，建议只在 Prompt 层面调整，不要修改工具语义与落库逻辑。

---

## 5. 工程实现要点（供报告的技术部分）

### 5.1 会话生命周期

```
概念提取（F-06）创建 TeachingSession(status=active) + concepts(status=learning)
  → 用户发送消息：POST /api/teaching/sessions/{id}/messages（10 秒内同内容幂等）
  → 前端订阅：GET /api/teaching/stream/{id}（SSE）
    → 后台任务 _run_teaching_stream：
       1. 取最后一条待回复 user 消息（刷新重连时幂等检查避免双写）
       2. agent.process_user_input → DeepSeek 流式（thinking 开启）
       3. 首轮工具批量执行 _run_tool_batch
       4. 未 task_complete → _run_tool_continuations 最多 50 轮
       5. 工具调用以 XML artifact 追加到 assistant 消息内容（刷新后仍可见）
  → GET /sessions/{id}/progress：全部 concept 为 mastered/promoted 时自动置 completed
  → POST /sessions/{id}/promote：勾选概念 → 挂载式合并进图谱（F-11）
```

### 5.2 SSE 与生成解耦（可靠性设计）

- `teaching_streams.ensure_stream`：同一会话已有生成任务时，新连接**附加订阅**并回放
  `partial_text`（`teaching.py:1185-1210`）——刷新页面不丢回复；
- 事件类型：`thinking / text / concept / misconception / tool_call / task_complete / done / error`；
- 幂等：存在待回复 user 消息才启动生成；若已存在 `parent_id` 指向该消息的 assistant 回复，
  直接广播 `done`（`teaching.py:1102-1111`）。

### 5.3 数据模型（`app/models/teaching.py`）

| 表 | 关键字段 | 研究用途 |
|----|---------|---------|
| `teaching_sessions` | `source_note_id`（来源笔记）、`trigger_concept_id`（F-16 错题触发）、`status` | 区分"新学会话"与"复习触发会话" |
| `messages` | `role`、`content`（含工具 XML artifact）、`parent_id`、`branch_id`、`is_active`、`created_at` | 对话过程分析主数据：轮数、字数、追问编码 |
| `concepts` | `name`、`description`（掌握时写入 AI 总结）、`user_explanation`、`status` | 掌握率、讲解覆盖率 |
| `misconceptions` | `concept_name`、`user_claim`、`ai_correction`、`resolved` | 误解类型与修正分析 |

### 5.4 分支编辑

`PUT /sessions/{id}/messages/{mid}`（`teaching.py:975-1053`）：更新目标消息后**删除其后所有消息**
（按 created_at），再用同一 Agent 重新生成回复；新回复 `parent_id` 指向被编辑消息，
保证 SSE 幂等检查识别"已有回复"。报告可将该功能作为"反事实重讲"研究工具：
同一条讲解改写后观察 AI 追问路径如何变化。

### 5.5 沉淀与闭环

- **F-11**：`mastered` 概念 → `merge_or_create_node`（同名复用、mastery 取大）→ `mount_node`
  （embedding 最近邻挂载 related 边）→ `concept.status='promoted'`；虚拟图内部边投影为真实边
  （`teaching.py:1238-1370`）；
- **F-16**：Practice 判定错题达到阈值（连续 3 次 / 近 10 次错 ≥ 6 次）→ 幂等创建
  TeachingSession（title="复习：{概念名}"，`trigger_concept_id` 标记，错题背景写入 system 消息）
  → 用户回到 Teaching 再讲一遍（`practice.py:42-110`）。

---

## 6. 面向探究性学习报告的研究设计建议

> 本节是"研究脚手架"，可直接作为报告"研究设计"章节素材。
> 系统天然产出对话过程数据，适合做**描述性编码研究**、**小样本对照实验**与**设计研究（DBR）**。

### 6.1 研究问题与假设（建议）

- **RQ1（描述性）**：AI 追问类型分布如何？一次"讲清一个概念"平均需要多少轮？
  用户自我解释的深度随时间如何变化？
- **RQ2（对照）**：与"阅读 AI 生成的标准讲解"相比，向 AI 讲解（Teaching 条件）
  是否带来更好的即时后测与延迟后测表现？
- **RQ3（相关）**：用户自我解释深度（五标准量规）与概念 `mastered` 结果、
  后续 Practice 正确率是否相关？
- **RQ4（误解）**：被标记 `misconception` 的概念在后续练习中正确率是否更低？
  误解修正后是否回升？
- **RQ5（Prompt 消融）**：移除"防御性引导"或"苏格拉底追问句式"后，
  AI 追问质量与用户解释深度是否下降？
- **H1**：Teaching 条件在迁移题上的即时与延迟后测优于阅读条件；
- **H2**：掌握五标准量规得分与概念最终 mastered 率正相关，与 misconception 数负相关；
- **H3**：含"未掌握前置知识点"的追问能提升后续相关概念的掌握速度（与 Practice 交错设计呼应）。

### 6.2 评价量规（建议）

**A. 用户讲解质量**（每个概念 0~2 分 × 5 维，来源：掌握五标准）

| 维度 | 判据 |
|------|------|
| 定义 | 是否给出概念核心含义与关键属性 |
| 机制 | 是否解释"为什么/如何成立" |
| 例子 | 是否给出恰当正例（及反例） |
| 边界 | 是否说明限制条件与不适用情形 |
| 联系 | 是否与已学概念建立实质关联 |

**B. AI 追问质量**（每轮追问 0~2 分 × 5 维）

| 维度 | 判据 |
|------|------|
| 关联性 | 是否基于用户上一轮回答，而非固定问卷 |
| 单一焦点 | 一轮是否只追问一个关键点 |
| 类别覆盖 | 是否在会话中覆盖澄清/假设/理由/视角/后果/边界（Paul & Elder 2006） |
| 生成诱导 | 是否迫使自我解释，而非要求再认 |
| 不代答 | 是否避免直接给出完整答案（遵守防御性引导） |

**C. 会话结果指标**：追问轮数、用户平均字数、mastered 率、misconception 数、
会话完成耗时、沉淀（promoted）概念数。

### 6.3 实验方案（建议）

1. **材料**：选取同一课程中 6~10 个难度匹配的概念，每个概念配一段标准讲解（对照材料）；
2. **条件**：Teaching 条件（向 AI 讲解）vs 阅读条件（阅读同内容标准讲解），
   同一被试内跨概念交叉平衡以控制概念难度与顺序效应；Prompt 版本（对齐/消融）可作被试间因素；
3. **测量**：即时后测（回忆 + 近迁移）、1 周延迟后测（保持）、讲解编码（§6.2 量规）；
4. **编码**：2~3 名评分者独立双盲编码，计算 Cohen's κ 或 ICC，分歧讨论定分；
5. **分析**：配对比较（Wilcoxon 符号秩检验）；量规分与结果指标做 Spearman 相关；
   对话文本做扎根理论/主题分析（追问类型、误解类型）；
6. **过程记录**：模型版本、Prompt 全文（git 可回溯）、参数（temperature=0.7、reasoning_effort=high）、
   完整对话日志与工具调用 artifact 均存档。

### 6.4 系统内可用数据

- `messages`：user / assistant 全文 + 时间戳 → 轮数、篇幅、追问编码、响应延迟；
- `messages.content` 中的 `<tool_call>` XML → 工具调用序列（标记时机、虚拟图创建时机）；
- `concepts.status` / `description`：掌握结果与 AI 总结；
- `misconceptions`：用户主张、AI 更正、未解决标记（注意 `resolved` 当前未被更新，见 §6.6）；
- `teaching_sessions`：会话来源（笔记 / 错题触发）与状态；
- `virtual_graphs` / `virtual_graph_nodes` / `virtual_graph_edges`：知识结构外化产物；
- `review_records` / `review_schedules`：后续 Practice 表现（F-12 ~ F-17，见 `docs/practice.md`）。

### 6.5 效度、信度与伦理

- **内容效度**：追问句式与五标准均来自已发表文献（Paul & Elder 2006；Chi et al. 1994；
  Fiorella & Mayer 2015），非自造标准；
- **信度**：双人编码 + 一致性系数；同一会话重复运行可估计 LLM 输出稳定性；
- **生态效度**：对话发生在真实学习产品中，材料来自用户自己的笔记；
- **控制**：明确记录模型版本与参数；消融实验必须固定其余 Prompt 组件；
- **伦理**：使用本人或公开学习材料；报告中不得包含 API key、账号与隐私数据；
  对话记录引用前应 anonymize。

### 6.6 已知局限（可直接写入报告的"局限与展望"）

1. **掌握判定未校准**：五标准由 LLM 自判，无金标；PRD 验收目标是"标记准确率 ≥ 80%"，
   建议报告中人工复核一批 mastered 案例，报告误判率；
2. **掌握度跃迁是启发式**：标记掌握后节点掌握度直接设为 0.3（`teaching.py:468`），
   非实证标定；
3. **`misconceptions.resolved` 无更新路径**：只写入 `False`，后续修正与否不落库（`teaching.py:496`）；
4. **`concepts.user_explanation` 未被写入**：字段存在且被 Practice 出题读取
   （`question_generator.py:125`），但 Teaching 流程从未填充（可按 report 列为改进点）；
5. **首条消息是固定模板**：`create_session` 的欢迎语不包含概念名与错题背景
   （`teaching.py:812-817`）；`TeachingAgent.start_session` 已实现但未被调用（`teaching_agent.py:599`）；
6. **无追问类型调度**：AI 自由追问，Prompt 无"每类问题至少一次"的显式覆盖要求，
   追问质量依赖模型能力；
7. **Prompt 不随界面语言切换**：教学 Prompt 固定中文；
8. **工具调用以 XML 混入消息正文**：便于回显但不利结构化统计，需正则解析；
9. **分支编辑是破坏式删除**：改写消息会删除其后所有消息（`teaching.py:989`），
   历史分支不可追溯；
10. **无自动化测试覆盖**：Teaching 链路依赖真实 API key 手工验证（见 §7）；
11. **文档与实现存在偏差**：PRD §8.2 称"沉淀时创建初始 ReviewSchedule（1 天后到期）"，
    但实际 `promote` 端点不创建复习计划，`review_schedules` 在 Practice 批量出题时创建
    （`question_generator.py:310`）；报告引用流程描述时应以代码为准。

---

## 7. 验证与测试现状

- 仓库当前无针对 `teaching_agent` 的自动化单元测试；README 说明测试为本地冒烟脚本（未入库）；
- 端到端可用性依赖真实 DeepSeek key 手工验证：创建会话 → 讲解 → 观察
  `thinking / text / concept / misconception / tool_call / task_complete / done` 事件序列 → 沉淀 → 图谱出现节点；
- 建议报告实测时记录：每轮响应耗时、追问轮数、标记准确率（人工复核）、
  虚拟图生成成功率、刷新重连是否丢回复——这些数据即构成报告的"结果"章节原材料。

---

## 8. 参考文献

### 8.1 教中学与可教代理

1. Bargh, J. A., & Schul, Y. (1980). On the cognitive benefits of teaching. *Journal of Educational Psychology*, 72(5), 593–604.
2. Fiorella, L., & Mayer, R. E. (2013). The relative benefits of learning by teaching and teaching expectancy. *Contemporary Educational Psychology*, 38(4), 281–288. https://doi.org/10.1016/j.cedpsych.2013.06.001
3. Fiorella, L., & Mayer, R. E. (2014). Role of expectations and explanations in learning by teaching. *Contemporary Educational Psychology*, 39(2), 75–85. https://doi.org/10.1016/j.cedpsych.2014.01.001
4. Fiorella, L., & Mayer, R. E. (2015). *Learning as a generative activity: Eight learning strategies that promote understanding*. Cambridge University Press.
5. Kobayashi, K. (2019). Learning by preparing-to-teach and teaching: A meta-analysis. *Japanese Psychological Research*, 61(3), 192–203. https://doi.org/10.1111/jpr.12221
6. Duran, D. (2017). Learning-by-teaching: Evidence and implications as a pedagogical mechanism. *Innovations in Education and Teaching International*, 54(5), 476–484.
7. Roscoe, R. D., & Chi, M. T. H. (2007). Understanding tutor learning: Knowledge-building and knowledge-telling in peer tutors' explanations and questions. *Review of Educational Research*, 77(4), 534–574.
8. Chase, C. C., Chin, D. B., Oppezzo, M. A., & Schwartz, D. L. (2009). Teachable agents and the protégé effect: Increasing the effort towards learning. *Journal of Science Education and Technology*, 18(4), 334–352.
9. Biswas, G., Leelawong, K., Schwartz, D., & Vye, N. (2005). Learning by teaching: A new agent paradigm for educational software. *Applied Artificial Intelligence*, 19(3–4), 363–392.
10. Chan, T.-W., & Baskin, A. B. (1988). "Studying with the prince": The computer as a learning companion. *Proceedings of the International Conference on Intelligent Tutoring Systems (ITS 1988)*, 194–200.

### 8.2 生成、自我解释与检索

11. Slamecka, N. J., & Graf, P. (1978). The generation effect: Delineation of a phenomenon. *Journal of Experimental Psychology: Human Learning and Memory*, 4(6), 592–604.
12. Chi, M. T. H., Bassok, M., Lewis, M. W., Reimann, P., & Glaser, R. (1989). Self-explanations: How students study and use examples in learning to solve problems. *Cognitive Science*, 13(2), 145–182.
13. Chi, M. T. H., De Leeuw, N., Chiu, M.-H., & LaVancher, C. (1994). Eliciting self-explanations improves understanding. *Cognitive Science*, 18(3), 439–477.
14. Bisra, K., Liu, Q., Nesbit, J. C., Salimi, F., & Winne, P. H. (2018). Inducing self-explanation: A meta-analysis. *Educational Psychology Review*, 30(3), 703–725.
15. Roediger, H. L., III, & Karpicke, J. D. (2006). Test-enhanced learning: Taking memory tests improves long-term retention. *Psychological Science*, 17(3), 249–255.
16. Karpicke, J. D., & Blunt, J. R. (2011). Retrieval practice produces more learning than elaborative studying with concept mapping. *Science*, 331(6018), 772–775.
17. Dunlosky, J., Rawson, K. A., Marsh, E. J., Nathan, M. J., & Willingham, D. T. (2013). Improving students' learning with effective learning techniques: Promising directions from cognitive and educational psychology. *Psychological Science in the Public Interest*, 14(1), 4–58.
18. Bjork, R. A. (1994). Memory and metamemory considerations in the training of human beings. In J. Metcalfe & A. Shimamura (Eds.), *Metacognition: Knowing about knowing* (pp. 185–205). MIT Press.
19. Bjork, E. L., & Bjork, R. A. (2011). Making things hard on yourself, but in a good way: Creating desirable difficulties to enhance learning. In M. A. Gernsbacher, R. W. Pew, L. M. Hough, & J. R. Pomerantz (Eds.), *Psychology and the real world* (pp. 56–64). Worth.

### 8.3 提问、辅导对话与反馈

20. Paul, R., & Elder, L. (2006). *The thinker's guide to the art of Socratic questioning*. Foundation for Critical Thinking.
21. Overholser, J. C. (1993). Elements of the Socratic method: I. Systematic questioning. *Psychotherapy: Theory, Research, Practice, Training*, 30(1), 67–74.
22. Graesser, A. C., & Person, N. K. (1994). Question asking during tutoring. *American Educational Research Journal*, 31(1), 104–137.
23. Graesser, A. C., Person, N., & Magliano, J. (1995). Collaborative dialogue patterns in naturalistic one-to-one tutoring. *Applied Cognitive Psychology*, 9(6), 495–522.
24. VanLehn, K. (2011). The relative effectiveness of human tutoring, intelligent tutoring systems, and other tutoring systems. *Educational Psychologist*, 46(4), 197–221.
25. Wood, D., Bruner, J. S., & Ross, G. (1976). The role of tutoring in problem solving. *Journal of Child Psychology and Psychiatry*, 17(2), 89–100.
26. Black, P., & Wiliam, D. (1998). Assessment and classroom learning. *Assessment in Education: Principles, Policy & Practice*, 5(1), 7–74.
27. Hattie, J., & Timperley, H. (2007). The power of feedback. *Review of Educational Research*, 77(1), 81–112.
28. Butler, A. C., & Roediger, H. L., III (2008). Feedback enhances the positive effects and reduces the negative effects of multiple-choice testing. *Memory & Cognition*, 36(3), 604–616.
29. Palincsar, A. S., & Brown, A. L. (1984). Reciprocal teaching of comprehension-fostering and comprehension-monitoring activities. *Cognition and Instruction*, 1(2), 117–175.

### 8.4 概念转变、元认知与知识外化

30. Posner, G. J., Strike, K. A., Hewson, P. W., & Gertzog, W. A. (1982). Accommodation of a scientific conception: Toward a theory of conceptual change. *Science Education*, 66(2), 211–227.
31. Chi, M. T. H. (2008). Three types of conceptual change: Belief revision, mental model transformation, and categorical shift. In S. Vosniadou (Ed.), *International handbook of research on conceptual change* (pp. 61–82). Routledge.
32. Flavell, J. H. (1979). Metacognition and cognitive monitoring: A new area of cognitive-developmental inquiry. *American Psychologist*, 34(10), 906–911.
33. Nelson, T. O., & Narens, L. (1990). Metamemory: A theoretical framework and new findings. *Psychology of Learning and Motivation*, 26, 125–173.
34. Koriat, A., & Bjork, R. A. (2005). Illusions of competence in monitoring one's knowledge during study. *Journal of Experimental Psychology: Learning, Memory, and Cognition*, 31(2), 187–194.
35. Bjork, R. A., Dunlosky, J., & Kornell, N. (2013). Self-regulated learning: Beliefs, techniques, and illusions. *Annual Review of Psychology*, 64, 417–444.
36. Novak, J. D., & Gowin, D. B. (1984). *Learning how to learn*. Cambridge University Press.
37. Ausubel, D. P. (1968). *Educational psychology: A cognitive view*. Holt, Rinehart & Winston.
38. Bereiter, C., & Scardamalia, M. (1987). *The psychology of written composition*. Lawrence Erlbaum.
39. Vygotsky, L. S. (1978). *Mind in society: The development of higher psychological processes*. Harvard University Press.

### 8.5 项目内文档

40. `docs/PRD.md`（§1.1 产品定位、§4.1 F-07~F-11/F-34、§8.1~8.4 交互流程、§9 Prompt 设计原则）；
41. `docs/input_to_teaching.md`（F-06 概念提取：key_points 与掌握五标准的同构关系）；
42. `docs/practice.md`（Practice 层：检索练习、间隔调度与 F-16 闭环）；
43. `docs/integration_guide.md`（虚拟图与挂载式沉淀规范）。
