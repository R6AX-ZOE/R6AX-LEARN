# Input → Teaching 概念提取（F-06）开发记录与探究性学习报告素材

> 本文档整合 R6AX:/Learn 中 **Input Level（原始笔记）→ Teaching Level（可教概念）** 之间
> **知识点提炼方法**的开发成果、理论依据与文献调研过程，供撰写探究性学习报告使用。
> 对应功能编号：F-06（Note 内容提取）。
> 涉及实现：`app/services/concept_extractor.py`（提炼 Prompt）、
> `app/routers/input.py:316`（`POST /api/input/notes/{id}/extract-concepts`）、
> `app/models/teaching.py:41`（Concept 模型）。

---

## 1. 开发成果总览

### 1.1 功能清单

| 功能 | 说明 | 对应文件 |
|------|------|---------|
| 笔记一键提炼 | 笔记卡片"提取概念"按钮 → AI 产出 3~8 个可教概念（name / description / key_points） | `app/routers/input.py:316`、`app/services/concept_extractor.py` |
| 教学会话承载 | 提取结果自动创建 TeachingSession（`source_note_id` 指向来源笔记），概念以 `status=learning` 落库 | `app/routers/input.py:417`、`app/models/teaching.py:8` |
| 项目级去重 | 提取前查询项目内已有概念（排除当前笔记来源），作为"请勿重复提取"清单注入 Prompt | `app/routers/input.py:389` |
| 幂等查看 | 同一笔记已提取过时直接回显已保存概念，不重复调用 AI | `app/routers/input.py:327` |
| 重新提取 | `re_extract=true`：删除该笔记旧会话与概念后重新提炼 | `app/routers/input.py:378` |
| 讲解支架 | 每个概念携带 2~4 个 `key_points`，教学会话按"定义/原理/例子/适用条件/联系"追问 | `app/services/concept_extractor.py`、`app/services/teaching_agent.py:448` |
| Prompt 理论对齐 | Prompt 显式写入"概念性 / 可教性 / 独立性 / 粒度 / 数量 / 去重"六类判据（见 §4） | `app/services/concept_extractor.py` |

### 1.2 关键设计决策

1. **提炼产物是"可教单元"，不是关键词、摘要或大纲**——只有能支撑"用自己的话讲清楚"的条目才会成为概念（对应 F-06 与产品"教中学"定位，见 `docs/PRD.md` §1.1）。
2. **提炼与教学分离**：F-06 只负责生成"讲什么"（概念 + 关键点），"怎么讲、讲没讲清"由 Teaching Agent 负责；两者是不同 agent、不同 Prompt（PRD §9.1）。
3. **概念自带讲解支架（key_points）**：让"教中学"有明确的追问锚点，避免 AI 追问漫无目的。
4. **项目级去重而非笔记级去重**：跨笔记、跨会话的概念不重复进入教学，使每个概念只被"教"一次。
5. **结构化输出 + 兜底**：要求纯 JSON（`{"concepts": [...]}`），解析失败返回空列表，由调用方给出"未能提取出概念"提示，流程不中断。
6. **工程边界（可写入报告的局限）**：笔记仅取前 3000 字符、`temperature=0.3`、去重只靠 Prompt 指令（未做 embedding 语义去重）、提炼 Prompt 目前不随界面语言切换。

---

## 2. 理论定位：这是哪一类"知识提炼"

把"笔记 → 可教概念"视为一次**教学转置（didactic transposition）**：
它不是把笔记压缩成摘要，而是把"学习者拥有的书面知识"重新组织为"可以被讲解、被追问、被检验的最小教学单元"。
以下理论分别支撑该流程的不同环节。

### 2.1 教学转置理论（Didactic Transposition）

Chevallard (1985) 提出：知识要进入教学，必须经历"学者知识（savoir savant）→ 可教知识（savoir à enseigner）→ 被教知识（savoir enseigné）"的转置；转置过程伴随**去语境化与再语境化**，并由此产生新的教学对象。Verret (1975) 最早提出"教学转置"概念。

- 对 F-06 的启示：笔记（个人书面知识）≠ 可教知识；提炼要做"去语境化"（把嵌入笔记上下文的段落变成自包含概念）与"再语境化"（补出讲解所需的关键点）。
- 对应产物：`Concept(name/description/key_points)` 就是转置后的教学对象。

### 2.2 生成学习与"教中学"（Generative Learning; Learning by Teaching）

Wittrock (1974, 1989) 的生成学习理论认为，学习是学习者主动生成意义（转述、总结、建立联系）的过程，而非信息接收。Fiorella & Mayer (2013, 2014) 的实验表明：**带着"要教别人"的预期学习（teaching expectancy）** 优于为考试而学；Fiorella & Mayer (2015) 把"教学（teaching）"列为八大生成学习策略之一。Kobayashi (2019) 对相关研究的元分析确认"准备教学 + 实际教学"均能显著提升学习效果。

- 对 F-06 的启示：提炼出的概念必须是"学习者将要讲给别人听"的对象，因此判据不是"信息是否重要"，而是"能否被讲出来、被追问"。
- 对应规则：可教性判据（能否用自己的话讲清"是什么/为什么/怎么用"）。

### 2.3 概念性知识 vs 事实性知识（知识类型学）

Anderson & Krathwohl (2001) 修订版布鲁姆分类在"认知过程"维度之外增加了**知识维度**：事实性知识、概念性知识、程序性知识、元认知知识。Gagné et al. (2005) 同样区分"言语信息"与"智慧技能（概念、规则、问题解决）"，其中"概念"指能按共同属性对事物进行分类的能力。

- 对 F-06 的启示："概念应该是**有明确定义**的知识点，不是简单的事实陈述"有明确理论依据：事实性知识只需记忆与复述，不经过"讲解—追问—纠错"的教学循环；概念性/程序性知识才需要被理解、举例与运用。
- 对应规则：概念性判据。

### 2.4 概念教学的结构：定义、属性、样例、适用条件

概念教学研究给出了概念学习的完整结构：

- Klausmeier & Goodwin (1977)：概念学习需要掌握**定义性属性（defining attributes）**，并通过**正例与反例**辨析形成概念；
- Tennyson & Cocchiarella (1986)：经实证检验的概念教学设计理论，强调"概念定义 + 最佳样例 + 匹配样例 + 无关属性排除"；
- Vinner & Hershkowitz (1980)：学习者头脑中的"概念意象（concept image）"常与"概念定义（concept definition）"不一致，教学必须同时触及定义、性质、例子与反例。

- 对 F-06 的启示：`key_points` 的维度应当是"定义/本质属性、原理或机制、典型例子与反例、适用条件与边界、与已学概念的联系"，而不是任意要点罗列。这与 Teaching Agent 判定"是否掌握"的五条标准（`app/services/teaching_agent.py:448-454`）同构。
- 对应规则：key_points 维度规则（理论对齐版新增）。

### 2.5 认知负荷与粒度（Cognitive Load; Working Memory）

Miller (1956) 的"7±2"与 Cowan (2001) 的"4±1"表明工作记忆容量有限；Sweller (1988)、Sweller, Ayres & Kalyuga (2011) 的认知负荷理论指出，材料内部元素的交互强度（element interactivity）决定学习难度——**太宽泛**的概念元素交互过高、无法一次讲完；**太琐碎**的知识点几乎是孤立元素、不值得作为独立教学单元。Mayer (2009) 多媒体学习原则中的"分段原则（segmenting）"与"预训练原则（pre-training）"要求把复杂内容切分为学习者可逐段处理的小块。

- 对 F-06 的启示："3~8 个核心概念、每概念 2~4 个关键点、避免太宽泛或太琐碎"正是工作记忆约束下的粒度设计；也解释了为什么是"提取 3~8 个"而不是"提取全部知识点"。

### 2.6 最小可教/可复用单元（Elaboration Theory; Learning Objects）

Reigeluth & Stein (1983) 的细化理论主张教学从一个简单、完整的"概要（epitome）"出发，由简到繁逐层细化；Wiley (2002) 与 IEEE LOM (2002) 提出的学习对象（learning objects）强调**粒度适中、自包含、可复用**。

- 对 F-06 的启示："每个概念是独立的、可讲解的单元"即"最小可教单元"；同一概念被提炼一次后可跨笔记、跨会话复用（这就是去重规则的意义）。

### 2.7 已知知识锚定与去重（Meaningful Learning; ZPD; Knowledge Spaces）

Ausubel (1963, 1968) 的意义学习理论强调：影响学习最重要的因素是学习者已经知道什么，新知识必须与已有认知结构建立实质联系；Vygotsky (1978) 的最近发展区（ZPD）指出教学应落在"现有水平"与"潜在发展水平"之间；Doignon & Falmagne (1985) 的知识空间理论用"知识状态 + 前置关系"刻画学习者的知识结构。

- 对 F-06 的启示：提取前注入"项目内已有概念"清单并跳过重复项，实质是**把原有概念当作新概念的锚点**，避免在最近发展区之外重复教学；这也是 Input 层与已有 Teaching/Integration 层贯通的数据依据。
- 对应规则：去重判据。

### 2.8 大概念与可教尺度（Big Ideas）

Wiggins & McTighe (2005) 的"逆向设计"主张围绕"大概念（big ideas）"组织教学，而非覆盖零散内容。

- 对 F-06 的启示："避免太宽泛或太琐碎"是两个方向的边界：宽泛到学科名（"线性代数"）无法作为一次讲解单元，琐碎到符号写法则没有教学价值；提炼应取二者之间的"可教尺度"。

### 2.9 自我解释与追问接口（Self-explanation）

Chi et al. (1989) 发现善于自我解释（self-explanation）的学习者理解更深；Dunlosky et al. (2013) 的系统综述把"自我解释/精细提问"列为中等效力的学习技术。

- 对 F-06 的启示：`key_points` 为教学会话提供"追问锚点"，而追问迫使学习者自我解释——提炼质量直接决定追问质量（可作为报告中的因果假设）。

### 2.10 相关但不直接实现的理论

- 刻意困难（Bjork 1994）：主要用于 Teaching 与 Practice 层（见 `docs/practice.md` §2.4）；对提炼层的启示是"不要把知识提前嚼碎到无需思考"。
- 认知任务分析（Clark et al. 2008；van Merriënboer & Kirschner 2018）：工业界"知识分解 / 学习任务分解"的方法学，可作为"知识点提炼"在教学设计职业实践中的对应物。
- 元认知（Flavell 1979）：学习者通过"讲不出来"暴露知识缺口，与 F-06 → Teaching 闭环的目标一致。

---

## 3. 理论 → 实现映射表（调研 → Prompt/代码）

| 理论依据 | 在提炼规则/实现中的体现 | 代码位置 |
|---------|------------------------|---------|
| 教学转置（Chevallard 1985） | 产物是可教概念（name/description/key_points），不是摘要 | `concept_extractor.py` 输出契约 |
| 概念性 vs 事实性知识（Anderson & Krathwohl 2001; Gagné et al. 2005） | "只提取有明确定义的概念性/程序性知识，不提取孤立事实" | Prompt 规则 1 |
| 教中学/生成学习（Wittrock 1974; Fiorella & Mayer 2013; Kobayashi 2019） | "必须能用'用自己的话讲解'检验" | Prompt 规则 2 |
| 学习对象/最小可教单元（Wiley 2002; IEEE LOM 2002） | "自包含的最小可教单元，不依赖笔记上下文" | Prompt 规则 3 |
| 认知负荷/分段（Sweller 1988; Mayer 2009） | 3~8 个概念；每概念 key_points 2~4 个 | Prompt 规则 5、6 |
| 概念教学结构（Klausmeier & Goodwin 1977; Tennyson & Cocchiarella 1986; Vinner & Hershkowitz 1980） | key_points 维度 = 定义/原理/例子/适用条件/联系 | Prompt 规则 6 |
| 大概念（Wiggins & McTighe 2005）+ 元素交互（Sweller） | "不要学科级宽泛，也不要符号级琐碎，用 2~4 个关键点自检" | Prompt 规则 4 |
| 意义学习/ZPD/知识空间（Ausubel 1963; Vygotsky 1978; Doignon & Falmagne 1985） | 注入项目已有概念并跳过重复；跨笔记只教一次 | Prompt 规则 7 + `input.py:389` |
| 概念掌握五标准（概念教学结构） | Teaching 追问维度与判定标准同构 | `teaching_agent.py:448-454, 520` |
| 结构化输出（工程约束） | 解析失败返回 `[]`，调用方提示、流程不中断 | `concept_extractor.py:62-68` |

---

## 4. Prompt 设计说明（理论对齐版）

### 4.1 输入/输出契约

- 输入：`note_content`（截取前 3000 字符）、`note_title`、`existing_concepts`（项目内已有概念 name/description 列表）；
- 输出：`{"concepts": [{"name": str, "description": str, "key_points": [str]}]}`；解析失败 → `[]`；
- 调用参数：`temperature=0.3`（低温度，保证术语稳定与可复现）。

### 4.2 规则与理论依据逐条对照

| 提炼规则 | 理论依据 |
|---------|---------|
| 1. 概念性（有明确定义，不提取事实/数值/人物） | Anderson & Krathwohl (2001); Gagné et al. (2005) |
| 2. 可教性（能用"用自己的话讲解"检验） | Wittrock (1974, 1989); Fiorella & Mayer (2013); Kobayashi (2019) |
| 3. 独立性（自包含的最小可教单元） | Wiley (2002); IEEE LOM (2002); Reigeluth & Stein (1983) |
| 4. 粒度（不宽泛、不琐碎，2~4 关键点自检） | Sweller (1988); Mayer (2009); Wiggins & McTighe (2005) |
| 5. 数量 3~8 | Miller (1956); Cowan (2001); Sweller et al. (2011) |
| 6. key_points 维度（定义/原理/例子/适用条件/联系） | Klausmeier & Goodwin (1977); Tennyson & Cocchiarella (1986); Vinner & Hershkowitz (1980) |
| 7. 去重（跳过项目已有概念） | Ausubel (1963); Vygotsky (1978); Doignon & Falmagne (1985) |

### 4.3 原版 → 理论对齐版的差异（Prompt 版本对照，便于报告做实验）

| 维度 | 原版 | 理论对齐版 |
|------|-----------|-----------------|
| 概念性 | "有明确定义的知识点，不是简单的事实陈述" | 明确"概念性/程序性知识 ≠ 事实性陈述（提出者/年份/数值等）"，并给出反例 |
| 可教性 | "独立的、可讲解的单元" | 明确"用自己的话讲清是什么/为什么/怎么用"作为检验标准 |
| 粒度 | "避免太宽泛或太琐碎" | 给出宽泛（学科名）与琐碎（符号写法）两类反例 + "2~4 个关键点自检" |
| key_points | "讲解这个概念时需要覆盖的 2~4 个关键点" | 明确优先维度（定义/原理/例子/适用条件/联系），与 Teaching 追问标准同构 |
| 去重 | "切勿重复提取已存在的概念" | 补充"概念名简洁、术语规范，便于后续检索与合并" |
| 输出 | JSON 示例 | 同一 JSON 契约，强调"只返回 JSON，不要其他内容" |
| 代码逻辑 | —— | 无变化：函数签名、截断、temperature、解析与兜底全部保持 |

> 报告写作提示：原版/对齐版两版 Prompt 构成天然的**对照实验条件**（见 §6.3），可用于验证"显式嵌入认知科学判据是否提升提炼质量"。

### 4.4 调优注意事项（不改变代码逻辑的前提下）

- 可调整措辞与数量阈值（如 3~8 的范围）观察输出分布，但保持 JSON 字段不变；
- 若做 A/B，建议在报告中记录每次 Prompt 的完整文本（git 版本可回溯）；
- 不建议把 `key_points` 改为自由文本：结构化字段是后续 Teaching/Practice 复用的前提。

---

## 5. 工程实现要点

### 5.1 提炼流水线

```
用户点击笔记卡片"提取概念"（HTMX）
  → POST /api/input/notes/{note_id}/extract-concepts
    → 若已提取且未要求重提取：回显已保存概念（幂等）
    → 删除旧数据（re_extract=true 时）
    → 查询项目内已有概念（排除本笔记来源）作为去重清单
    → extract_concepts(note.content[:3000], note.title, existing_concepts)
      → chat_completion(temperature=0.3) → json.loads → concepts[]
    → 创建 TeachingSession（title="从「{note.title}」提取的概念"）
    → 逐条写入 concepts（status=learning）
  → 返回概念卡片（含 2~4 个 key_points）+ "开始教学"按钮
```

### 5.2 数据模型与现状

- `TeachingSession.source_note_id` 把会话与来源笔记绑定，支持"已提取"判定与回显；
- `Concept(name, description, status)` 是 Teaching 层的最小教学单元，`status` 从 `learning` 开始，由 Teaching Agent 在用户讲清后置为 `mastered`；
- `key_points` 仅存在于**首次提取响应**中（用于卡片展示与讲解支架），`concepts` 表未持久化该字段；二次查看（幂等回显分支）只显示 name/description——报告可将其列为"下一步改进点"。

### 5.3 与 Teaching 层的衔接

- 提取完成后用户从卡片进入会话；Teaching Agent 的追问维度与 key_points 同构：定义、原理、例子、适用条件、与已学概念的联系（`teaching_agent.py:440, 520`）；
- 判定掌握的五条标准（`teaching_agent.py:448-454`）构成"可教性"的下游检验：提炼阶段提出的"可教"，最终由教学对话验证。

---

## 6. 面向探究性学习报告的研究设计建议

> 本节是"研究脚手架"，可直接作为报告的"研究设计"章节素材。系统本身会产生过程数据，适合做小样本准实验与作品评价。

### 6.1 研究问题与假设

- **RQ1（描述性）**：LLM 能否把不同体裁的笔记稳定转置为符合"概念性/可教性/独立性/粒度"判据的教学单元？
- **RQ2（对照）**：在 Prompt 中显式嵌入认知科学判据（对齐版）相比朴素指令（原版），提炼质量是否提升？
- **RQ3（相关性）**：提炼质量（量规分数）与后续 Teaching 表现（追问轮数、mastered 率、误区数）是否相关？
- **H1**：对齐版在"概念性、key_points 覆盖度、去重"三个维度上优于原版；
- **H2**：量规总分与概念最终 mastered 率正相关，与误区数负相关。

### 6.2 评价量规（建议）

对每个提取出的概念按维度 0~2 分评分（0=不符合，1=部分符合，2=符合）：

| 维度 | 判据 |
|------|------|
| 概念性 | 是否为有明确定义的概念/原理/方法，而非事实、数值、人名 |
| 可教性 | 能否"用自己的话讲清是什么/为什么/怎么用" |
| 独立性 | 脱离笔记上下文是否仍可讲解 |
| 粒度 | 是否介于"学科级宽泛"与"符号级琐碎"之间 |
| key_points | 是否覆盖 2~4 个有效维度（定义/原理/例子/适用条件/联系） |
| 忠实性 | 是否忠于笔记内容、无幻觉（对照笔记人工核查） |
| 去重 | 是否与项目内已有概念重复 |

汇总指标：概念数是否在 3~8；各维度均分；幻觉率；重复率。

### 6.3 实验方案（建议）

1. **材料**：选取 3~5 篇不同学科/体裁的笔记（含至少一篇以事实陈述为主、一篇高度碎片化），每篇 500~3000 字；
2. **条件**：原版 Prompt vs 理论对齐版 Prompt（同一模型、`temperature=0.3`、同一笔记），可交叉平衡顺序以控制顺序效应；
3. **评分**：2~3 名评分者用 §6.2 量规独立双盲评分；计算评分者一致性（Cohen's κ 或 ICC），对分歧讨论定分；
4. **对照分析**：配对比较两版得分（小样本可用 Wilcoxon 符号秩检验）；对"提取失败/幻觉"案例做质性分析；
5. **纵向关联（可选）**：把提取出的概念继续完成 Teaching 会话，记录追问轮数、mastered 概念数、misconception 数，与量规分数做相关分析（Spearman）；
6. **过程记录**：Prompt 全文、模型版本（deepseek-v4-flash）、每次调用时间与原始输出均存档（可引用 git 提交版本）。

### 6.4 系统内可用数据

- `concepts` 表：name / description / status（learning → mastered）；
- `teaching_sessions`：提取产生的会话及练习触发的复习会话；
- `messages`：Teaching 追问过程（可统计"讲清一个概念平均需要几轮追问"）；
- `misconceptions`：误解数量与类型（可用于分析提炼遗漏/失真的影响）；
- `questions.knowledge_points`：Practice 层对知识点的引用（提炼质量对出题的连锁影响）。

### 6.5 效度、信度与伦理

- **内容效度**：量规条目均来自已发表的概念教学/认知负荷理论，避免自造标准；
- **信度**：双人评分 + 一致性系数；同一笔记重复运行两次可估计 LLM 输出稳定性；
- **生态效度**：笔记与 Prompt 均来自真实使用场景；
- **伦理**：使用本人/公开学习材料；报告中不要包含 API key、个人隐私与完整用户数据。

### 6.6 已知局限（可直接写入报告的"局限与展望"）

1. 笔记截断 3000 字符，长笔记首尾覆盖不完整；
2. `key_points` 未落库，二次查看会丢失（仅首次响应展示）；
3. 去重仅依赖 Prompt 指令 + 名称字符串，无 embedding 语义去重（`embedding_service.py` 尚未用于提炼去重）；
4. JSON 解析为严格 `json.loads`，AI 若用 Markdown 代码围栏包裹输出会直接解析失败并返回空列表（无 `_extract_json` 容错，对照 `question_generator.py:101`）；
5. 单模型、单次调用、无重试与自我校验；
6. 提炼 Prompt 固定中文，未接入 i18n locale。

---

## 7. 验证与测试现状

- 提取链路的端到端可用性依赖真实 DeepSeek key 手工验证（当前仓库无自动化测试覆盖 `concept_extractor`）；
- 建议报告实测时记录：每篇笔记的提取耗时、概念数分布、幻觉案例、两版 Prompt 对照结果——这些数据即构成报告的"结果"章节。

---

## 8. 参考文献

1. Chevallard, Y. (1985). *La transposition didactique : Du savoir savant au savoir enseigné*. Grenoble: La Pensée Sauvage.
2. Verret, M. (1975). *Le temps des études*. Paris: Honoré Champion.
3. Wittrock, M. C. (1974). Learning as a generative process. *Educational Psychologist*, 11(2), 87–95.
4. Wittrock, M. C. (1989). Generative processes of comprehension. *Educational Psychologist*, 24(4), 345–376.
5. Fiorella, L., & Mayer, R. E. (2013). The relative benefits of learning by teaching and teaching expectancy. *Contemporary Educational Psychology*, 38(4), 281–288. https://doi.org/10.1016/j.cedpsych.2013.06.001
6. Fiorella, L., & Mayer, R. E. (2014). Role of expectations and explanations in learning by teaching. *Contemporary Educational Psychology*, 39(2), 75–85. https://doi.org/10.1016/j.cedpsych.2014.01.001
7. Fiorella, L., & Mayer, R. E. (2015). *Learning as a generative activity: Eight learning strategies that promote understanding*. Cambridge University Press.
8. Kobayashi, K. (2019). Learning by preparing-to-teach and teaching: A meta-analysis. *Japanese Psychological Research*, 61(3), 192–203. https://doi.org/10.1111/jpr.12221
9. Anderson, L. W., & Krathwohl, D. R. (Eds.). (2001). *A taxonomy for learning, teaching, and assessing: A revision of Bloom's taxonomy of educational objectives*. Longman.
10. Gagné, R. M., Wager, W. W., Golas, K. C., & Keller, J. M. (2005). *Principles of instructional design* (5th ed.). Wadsworth.
11. Klausmeier, H. J., & Goodwin, W. (1977). *Learning and human abilities: Educational psychology* (4th ed.). Harper & Row.
12. Tennyson, R. D., & Cocchiarella, M. J. (1986). An empirically based instructional design theory for teaching concepts. *Review of Educational Research*, 56(1), 40–71.
13. Vinner, S., & Hershkowitz, R. (1980). Concept images and common cognitive paths in the development of some simple geometrical concepts. In R. Karplus (Ed.), *Proceedings of the Fourth International Conference for the Psychology of Mathematics Education* (pp. 177–184). Berkeley, CA.
14. Miller, G. A. (1956). The magical number seven, plus or minus two: Some limits on our capacity for processing information. *Psychological Review*, 63(2), 81–97.
15. Cowan, N. (2001). The magical number 4 in short-term memory: A reconsideration of mental storage capacity. *Behavioral and Brain Sciences*, 24(1), 87–114.
16. Sweller, J. (1988). Cognitive load during problem solving: Effects on learning. *Cognitive Science*, 12(2), 257–285.
17. Sweller, J., Ayres, P., & Kalyuga, S. (2011). *Cognitive load theory*. Springer.
18. Mayer, R. E. (2009). *Multimedia learning* (2nd ed.). Cambridge University Press.
19. Reigeluth, C. M., & Stein, F. S. (1983). The elaboration theory of instruction. In C. M. Reigeluth (Ed.), *Instructional-design theories and models: An overview of their current status* (pp. 335–381). Lawrence Erlbaum.
20. Wiley, D. A. (2002). Connecting learning objects to instructional design theory: A definition, a metaphor, and a taxonomy. In D. A. Wiley (Ed.), *The instructional use of learning objects*. AECT.
21. IEEE (2002). *IEEE standard for learning object metadata* (IEEE Std 1484.12.1-2002).
22. Ausubel, D. P. (1963). *The psychology of meaningful verbal learning*. Grune & Stratton.
23. Ausubel, D. P. (1968). *Educational psychology: A cognitive view*. Holt, Rinehart & Winston.
24. Vygotsky, L. S. (1978). *Mind in society: The development of higher psychological processes*. Harvard University Press.
25. Doignon, J.-P., & Falmagne, J.-C. (1985). Spaces for the assessment of knowledge. *International Journal of Man-Machine Studies*, 23(2), 175–196.
26. Doignon, J.-P., & Falmagne, J.-C. (1999). *Knowledge spaces*. Springer.
27. Wiggins, G., & McTighe, J. (2005). *Understanding by design* (2nd ed.). ASCD.
28. Chi, M. T. H., Bassok, M., Lewis, M. W., Reimann, P., & Glaser, R. (1989). Self-explanations: How students study and use examples in learning to solve problems. *Cognitive Science*, 13(2), 145–182.
29. Dunlosky, J., Rawson, K. A., Marsh, E. J., Nathan, M. J., & Willingham, D. T. (2013). Improving students' learning with effective learning techniques: Promising directions from cognitive and educational psychology. *Psychological Science in the Public Interest*, 14(1), 4–58.
30. Bjork, R. A. (1994). Memory and metamemory considerations in the training of human beings. In J. Metcalfe & A. Shimamura (Eds.), *Metacognition: Knowing about knowing* (pp. 185–205). MIT Press.
31. Clark, R. E., Feldon, D., van Merriënboer, J. J. G., Yates, K., & Early, S. (2008). Cognitive task analysis. In J. M. Spector, M. D. Merrill, J. J. G. van Merriënboer, & M. P. Driscoll (Eds.), *Handbook of research on educational communications and technology* (3rd ed., pp. 577–593). Routledge.
32. van Merriënboer, J. J. G., & Kirschner, P. A. (2018). *Ten steps to complex learning* (3rd ed.). Routledge.
33. Flavell, J. H. (1979). Metacognition and cognitive monitoring: A new area of cognitive-developmental inquiry. *American Psychologist*, 34(10), 906–911.
34. 项目内文档：`docs/PRD.md`（F-06、§9 Prompt 设计原则）、`docs/practice.md`（Practice 层理论映射样例）、`app/services/teaching_agent.py`（掌握判定五标准）。
