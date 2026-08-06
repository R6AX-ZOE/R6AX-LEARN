# Practice Level（F-12 ~ F-15）开发记录与探究性学习报告素材

> 本文档整合了 R6AX:/Learn 中**间隔练习（Practice Level）**功能的开发成果、
> 设计依据与文献调研过程，供撰写探究性学习报告使用。
> 对应功能编号：F-12（Teaching → Practice 出题）、F-13（做题界面）、
> F-14（AI 判主观题）、F-15（基础调度）。

---

## 1. 开发成果总览

### 1.1 功能清单（已完成并验证）

| 功能 | 说明 | 对应文件 |
|------|------|---------|
| 题库独立页面 | 全部题目列表，答案默认折叠，可按题目/考点搜索（htmx 局部刷新） | `app/routers/pages.py`、`app/templates/practice/bank.html` |
| 习题会话 | 一次会话 10 道题（复习范围）；单题展示，上一题/下一题导航；未完成/已完成会话在首页分列展示 | `app/templates/practice/session.html`、`today.html` |
| 题目生成（6 简单 + 4 拓展） | AI 先产出"出题思路"（blueprint），再逐题设计；每道题带涉及知识点（含未掌握的前置知识点）与设计理由（rationale） | `app/services/question_generator.py` |
| 可撤销后台出题 | 题目不足时后台 job 出题，前端显示进度并可撤销；撤销后已生成的题目保留在题库 | `app/services/practice_jobs.py` |
| AI 评审赋分 | 客观题（选择/填空）规则判分；主观题（简答/编程）AI 对照参考答案赋分（0~100），提交后立即反馈；反馈中显示原答案 | `app/services/question_generator.py`（grade_answer） |
| 基础调度 | 答对间隔翻倍（上限 100 天），答错减半（下限 1 天）；24 小时内作答过的题目不重复进入新会话 | `app/routers/practice.py` |
| Markdown 编辑器 | 复用带 KaTeX/Mermaid 的 markdown 编辑器（编辑/预览），宽屏时编辑与预览并排实时刷新 | `app/static/js/markdown-render.js`、`app/templates/components/markdown_editor.html` |
| 数据模型 | questions 增加 is_extension / knowledge_points / rationale；review_records 增加 score；新增 practice_sessions / practice_session_questions 表 | `app/models/practice.py`、`app/core/database.py` |
| 测试 | 端到端冒烟测试（登录 → 出题 → 会话 → 作答 → 反馈 → 撤销 → 会话记录），以及无头浏览器（Edge+Selenium）验证 | `tests/smoke_practice.py` |

### 1.2 关键设计决策

1. **题目生成不在 Teaching 对话内完成**：出题由 Practice Level 显式触发（后台 job + 进度 + 撤销），
   避免阻塞教学对话（SSE 流），也符合 PRD §9.1 中 Question Generator AI 与 Teaching AI 的角色分离。
2. **一套题 = 6 道简单题 + 4 道拓展题**：简单题覆盖布鲁姆的 Remember/Understand/Apply 层级；
   拓展题覆盖 Analyze/Evaluate/Create 层级，必须涉及多个知识点，且可包含**尚未掌握的前置知识点**
   （刻意困难设计，见 §2.4）。
3. **每道题携带出题思路（rationale）**：记录设计意图与期望思维链，用户可在做题时展开查看，
   也便于后续 A/B 测试与 prompt 调优。
4. **立即反馈闭环**：提交后即时评审（0~100 分 + 错因解释 + 原答案 + 参考答案），
   符合检索练习"作答后必须核对"的原则。
5. **应对思考模型的工程问题**：DeepSeek 思考模型（deepseek-v4-flash）在长提示词下
   reasoning 消耗不稳定，曾出现"输出预算被思考耗尽返回空串"；通过加大 max_tokens、
   失败重试、`asyncio.wait_for` 硬超时与降级兜底共同保证可用性。

---

## 2. 文献调研与设计依据（参考文献过程）

> 调研方法：围绕"如何设计基于学习科学的间隔练习与题目生成"进行网络检索，
> 选取认知科学实证研究、教学设计工具网站等来源，提取可用于 Prompt 设计的原理，
> 并逐一映射到出题/判题 Prompt 与产品交互中。

### 2.1 六大学习策略（The Learning Scientists）

**来源**：Sumeracki, M., & Weinstein, Y. (2016). *Six Strategies for Effective Learning*.
The Learning Scientists. https://www.learningscientists.org/blog/2016/8/18-1
（配套：*Learn how to Study Using... Retrieval Practice*，
https://www.learningscientists.org/blog/2016/6/23-1）

**核心内容**（基于数十年认知研究，每项均有实证支持）：
1. **Spacing（间隔）**：Benjamin, A. S., & Tullis, J. (2010). What makes distributed practice effective?
2. **Retrieval Practice（检索练习）**：Roediger, H. L., Putnam, A. L., & Smith, M. A. (2011).
   Ten benefits of testing and their applications to educational practice.
3. **Elaboration（精加工）**：McDaniel, M. A., & Donnelly, C. M. (1996). Learning with analogy
   and elaborative interrogation.
4. **Interleaving（交错）**：Rohrer, D. (2012). Interleaving helps students distinguish among similar concepts.
5. **Concrete Examples（具体例子）**：Rawson, K. A., et al. (2014). The power of examples.
6. **Dual Coding（双编码）**：Mayer, R. E., & Anderson, R. B. (1992). The instructive animation.

**在产品中的落地**：
- 检索练习 → 出题 Prompt 要求"强迫回忆与重构而非再认"；答题后立即给出反馈核对
- 间隔 → F-15 基础调度（答对翻倍、答错减半）
- 精加工 → 简单题模板"说明原理/机制，为什么成立"
- 交错 → 拓展题必须关联多个知识点；一套题内交错不同概念
- 具体例子 → 简单题模板"举实际例子、找反例、说明适用边界"
- 双编码 → 答案编辑器支持 KaTeX 公式、Mermaid 图、代码块（多通道表达）

### 2.2 布鲁姆认知目标分类（Bloom's Taxonomy）

**来源**：University of Arkansas, Teaching Innovation & Pedagogical Support (2014).
*Bloom's Taxonomy Verb Chart*. https://tips.uark.edu/blooms-taxonomy/
（注意：原文中旧版动词表，新版 2001 修订版层次为 Remember / Understand / Apply /
Analyze / Evaluate / Create）

**核心内容**：六个认知层级对应的可测量行为动词
（如 Remember: define/list/recall；Understand: explain/classify/compare；
Apply: solve/use/demonstrate；Analyze: differentiate/examine；
Evaluate: judge/critique/justify；Create: design/construct/formulate）。

**在产品中的落地**：
- 简单题 → 明确限定在 Remember / Understand / Apply（复述定义、解释机制、直接应用）
- 拓展题 → 明确要求 Analyze / Evaluate / Create（比较辨析、批判评估、设计构造）
- 出题 Prompt 中直接写入该分层约束，确保 6+4 的结构性差异

### 2.3 苏格拉底式提问（Socratic Questioning）

**来源**：Changing Minds (n.d.). *Socratic Questions*.
https://www.changingminds.org/techniques/questioning/socratic_questions.htm

**核心内容**：苏格拉底提问的六种类型——
1. 概念澄清（conceptual clarification）
2. 质疑假设（probing assumptions）
3. 追问理由与证据（probing rationale, reasons and evidence）
4. 变换视角（questioning viewpoints and perspectives）
5. 推演后果与影响（probe implications and consequences）
6. 对问题本身的反思（questions about the question）

**在产品中的落地**：拓展题 Prompt 引入上述六类提问方式，
例如"批判性思考：常见误解如何识别并避免"（质疑假设）、
"若前提条件改变结论如何变化"（推演后果）、
"迁移到新领域"（变换视角）。

### 2.4 迁移理论（Transfer of Learning）与刻意困难（Desirable Difficulties）

**来源（检索）**：Wikipedia, *Transfer of learning*（近迁移/远迁移 near vs. far transfer）；
学习科学中对"desirable difficulties"的讨论（以 Bjork 的 desirable difficulties 概念为理论背景）。

**核心内容**：
- 近迁移：把知识应用于相似情境；远迁移：应用于截然不同的新领域，更难但更有价值
- 刻意困难：适度增加学习难度（如引入未学过的前置知识）可促进深层加工与长时记忆

**在产品中的落地**：
- 拓展题明确要求"迁移到与课本完全不同的新领域（工程/生活/其他学科）"
- 拓展题允许并鼓励包含"未掌握的前置知识点"，题面会显式标注，促使用户自解释与主动补课

### 2.5 其他参考资料

- 项目 PRD：`docs/PRD.md`（F-12~F-15 原始需求、PRD §9 AI Prompt 设计原则）
- 项目设计规范：`DESIGN.md`（Apple 风格界面，用于保持各 Level UI 一致性）
- 集成规范：`docs/integration_guide.md`

---

## 3. Prompt 设计映射表（调研 → 实现）

| 调研依据 | 生成/判题 Prompt 中的体现 |
|---------|--------------------------|
| 检索练习（Roediger & Putnam 2011） | "题目必须强迫用户从记忆中重构知识，而不是再认" |
| 精加工（McDaniel & Donnelly 1996） | 简单题模板："说明它成立的原理或机制（为什么？）" |
| 交错练习（Rohrer 2012） | "一套题内交错涉及多个概念"；拓展题 knowledge_points 含多个知识点 |
| 具体例子（Rawson et al. 2014） | "要求举真实例子、构造反例、指出适用边界" |
| 双编码（Mayer & Anderson 1992） | 允许并要求用公式/伪代码/图示作答；编辑器支持 KaTeX+Mermaid |
| 布鲁姆层级（U. Arkansas 动词表） | 简单题=Remember/Understand/Apply；拓展题=Analyze/Evaluate/Create |
| 苏格拉底六问（changingminds.org） | 拓展题的批判、假设质疑、后果推演、多视角 |
| 远迁移/刻意困难 | 拓展题跨领域迁移 + 未掌握前置知识点 |
| 间隔效应（Benjamin & Tullis 2010） | F-15 简单时间间隔调度（P1 升级 FSRS） |

---

## 4. 工程实现要点（供报告的技术部分）

### 4.1 出题流水线（F-12）

```
用户点击"开始完成习题"
  → POST /api/practice/sessions
    → 从复习范围（到期题目）选题，不足 10 道时启动后台出题 job（可撤销）
  → generate_question_set()
    → 选定主概念（题库中最少的概念）+ 其余概念作为上下文
    → AI 一次性产出 blueprint + 10 道题（6 简单 + 4 拓展）JSON
    → 校验/降级补齐 → 逐题落库（questions + review_schedules）
```

关键点：
- 出题语言跟随当前 locale（zh_CN / en-US），`_lang_hint()` 注入 Prompt
- JSON 解析容错（`_extract_json` 处理 ```json 围栏与杂音）
- AI 失败/输出为空时降级为模板题，保证流程不中断
- 后台 job 使用独立线程 + 独立事件循环（`asyncio.run`），保证任意 ASGI 环境可执行

### 4.2 AI 评审（F-14）

- choice/fill：归一化（去空白、小写）规则判分，fill 支持 `||` 多答案
- short/code：AI 对照参考答案按四档评分（90-100 / 70-89 / 50-69 / 0-49），
  is_correct = score ≥ 60；反馈必须说明错因与差距
- 工程保障：`asyncio.wait_for(..., timeout=60)` 硬超时；前端 `hx-on::send-error`/
  `hx-on::response-error` 兜底提示，避免"评审中消失但无结果"

### 4.3 基础调度（F-15）

```
答对：interval × 2（上限 100 天），ease + 0.1，节点掌握度 +5%
答错：interval ÷ 2（下限 1 天），ease - 0.2，节点掌握度 -5%
```
- 新会话选题排除 24 小时内已作答的题目（避免短时间重复）
- 会话补题同样遵守该排除规则

### 4.4 界面与交互

- 首页（`/practice/{project_id}`）：开始习题入口 + 未完成会话（题库上方）+ 已完成会话（题库下方）+ 题库入口
- 会话页：一次一题，上一题/下一题导航；题目渲染为 HTML（Markdown+KaTeX+Mermaid）；
  答案用 markdown 编辑器（宽屏并排预览）；提交后 HTMX 局部刷新显示评分、反馈、原答案、参考答案
- 题库页（`/practice/{project_id}/bank`）：答案默认折叠（`<details>`），按题目/考点搜索
- 出题进度：轮询 `GET /api/practice/generate-job/{id}`，显示 n/10 进度条，可撤销

---

## 5. 验证与测试

- `tests/smoke_practice.py`：端到端冒烟测试（TestClient）
  覆盖：hub/题库页/搜索 partial → 会话创建与后台出题 → 10 题会话 → HTMX 作答
  （含原答案回显断言）→ 重复作答拒绝 → 会话完成 → 撤销出题且题目保留 → 会话记录展示顺序
- 无头浏览器（Edge + Selenium）验证：提交答案 → "AI 评审中" → `htmx:beforeSwap/afterSwap`
  (200) → 结果出现；并据此定位了"评审超时无反馈"问题（见 §1.2.5）
- 真实 DeepSeek key 端到端验证：一套 10 题（6 简单 + 4 拓展）约 40~70 秒生成完毕，
  拓展题样例：构造满足谱信息的矩阵（Create 层级）、证明不同特征值对应特征向量线性无关
  （Analyze/Prove 层级，含未掌握前置知识点标注）

---

## 6. 参考文献列表

1. Sumeracki, M., & Weinstein, Y. (2016). Six Strategies for Effective Learning.
   The Learning Scientists. https://www.learningscientists.org/blog/2016/8/18-1
2. Smith, M., & Weinstein, Y. (2016). Learn how to Study Using... Retrieval Practice.
   The Learning Scientists. https://www.learningscientists.org/blog/2016/6/23-1
3. Benjamin, A. S., & Tullis, J. (2010). What makes distributed practice effective?
   Cognitive Psychology, 61, 228-247.
4. Roediger, H. L., Putnam, A. L., & Smith, M. A. (2011). Ten benefits of testing and their
   applications to educational practice. In J. Mestre & B. Ross (Eds.), Psychology of learning
   and motivation: Cognition in education. Elsevier.
5. McDaniel, M. A., & Donnelly, C. M. (1996). Learning with analogy and elaborative
   interrogation. Journal of Educational Psychology, 88, 508-519.
6. Rohrer, D. (2012). Interleaving helps students distinguish among similar concepts.
   Educational Psychology Review, 24, 355-367.
7. Rawson, K. A., Thomas, R. C., & Jacoby, L. L. (2014). The power of examples.
   Educational Psychology Review, 27, 483-504.
8. Mayer, R. E., & Anderson, R. B. (1992). The instructive animation.
   Journal of Educational Psychology, 4, 444-452.
9. University of Arkansas TIPS (2014). Bloom's Taxonomy Verb Chart.
   https://tips.uark.edu/blooms-taxonomy/
10. Changing Minds. Socratic Questions.
    https://www.changingminds.org/techniques/questioning/socratic_questions.htm
11. Wikipedia. Transfer of learning（近迁移/远迁移概念）.
12. R6AX:/Learn PRD（docs/PRD.md）与 DESIGN.md、docs/integration_guide.md（项目内文档）。
