# R6AX:/LEARN 自学辅助软件 — 产品需求文档 (PRD)

> **版本**: R6AX:/Learn — PRD v1.1（与当前实现对齐）

> 架构：**Jinja2 + HTMX + FastAPI + SQLite + Docker**（Python 3.11）。
> 本文档与代码同步维护；涉及实现细节（表结构、接口路径、配置项）以 `app/` 下代码为准。

---

## 1. 产品定位

### 1.1 一句话定义
**R6AX:/Learn** 是一个基于"教中学（Learning by Teaching）"理念的 AI 辅助学习平台。

用户通过**主动向 AI 讲解知识**来复习巩固。AI 扮演"聪明的学生"或"苏格拉底式提问者"，通过追问、质疑、要求举例，逼用户把模糊知识磨成清晰、能讲出来的知识。

学习循环的完整闭环：
```
教 AI（短期强化理解）
  → 沉淀到图谱（结构化）
    → 做练习（间隔重复抗遗忘）
      → 触发新一轮教 AI（巩固薄弱点）
```

### 1.2 核心差异点
- **不主打"AI 教你"**（市面上到处都是）
- **主打"你教 AI"**——教学过程本身就是复习（费曼学习法）
- **四层知识结构**：Input（原始笔记）→ Teaching（讲解加工）→ Practice（间隔重复）→ Integration（结构化图谱）
- **闭环设计**：四层互为输入输出，不是单向流水线

### 1.3 目标用户
- 正在自学的学生 / 研究者 / 工程师
- 已经有原始笔记 / 课程材料
- 觉得"看懂了但讲不出来"和"学完就忘"是痛点
- 想要长期、可持续的知识积累，而不是一次性刷题

### 1.4 不做什么（MVP 不做）
- 多用户社交 / 共享 / 协作
- 移动端原生 App（响应式 web 即可）
- 复杂的 LLM 微调 / 本地模型
- 多语言 i18n 多于 2 种（MVP：zh-CN + en-US）

---

## 2. 信息架构

### 2.1 四层知识模型

```
┌──────────────────────────────────────────────┐
│  Integration（图式关联）                       │  ← 高度结构化、强关联
│  - Project → Graph → Node → Edge              │
│  - 用户最终沉淀的"知识图谱"                     │
│  - 节点带"掌握度"（来自 Practice 历史）         │
├──────────────────────────────────────────────┤
│  Teaching（教 AI 复习）            【P0】     │  ← 短期强化
│  - 教学会话 / 概念树 / 错题本                   │
│  - AI 苏格拉底式追问                            │
├──────────────────────────────────────────────┤
│  Practice（间隔重复做题）           【P0】    │  ← 长期抗遗忘
│  - Question / ReviewSchedule / ReviewRecord  │
│  - 用户做错 / 时间到 → 触发新一轮 Teaching    │
├──────────────────────────────────────────────┤
│  Input（原始笔记）                             │  ← 基础素材
│  - Project → Directory → Note                 │
│  - 用户"学"的内容                              │
└──────────────────────────────────────────────┘
```

**核心数据流（双向闭环）**：
```
Input Note  ──抽取──▶  Teaching Concept  ──沉淀──▶  Integration Node
   ▲                       │                              │
   │                       │ 出题                          │ 薄弱点
   │                       ▼                              ▼
   └─────── 复习触发 ────  Practice Question  ◀──────────┘
                           (错题自动重排)
```

### 2.2 关键概念

| 概念 | 含义 | 归属层级 |
|------|------|---------|
| **User** | 平台用户 | 全局 |
| **Project** | 学习项目（一个学科 / 一门课 / 一个主题） | 四层都有 |
| **Directory** | 项目内的目录 / 章节 | Input |
| **Note** | 一篇原始笔记 | Input |
| **TeachingSession** | 一次"教 AI"的完整会话 | Teaching |
| **Concept** | 用户在 Teaching 中讲清楚的一个概念 | Teaching |
| **Misconception** | 用户讲错 / 讲不清的点 | Teaching |
| **Question** | 一道复习题（可由 AI 从 Concept 生成） | Practice |
| **ReviewSchedule** | 复习调度计划（下次复习时间） | Practice |
| **ReviewRecord** | 用户对 Question 的一次作答记录 | Practice |
| **Graph** | 知识图谱（一个项目可有多张图，通常按目录一张） | Integration |
| **Node** | 图谱中的节点（≈ 一个 Concept） | Integration |
| **Edge** | 节点之间的边（Prerequisite / Parent / Related） | Integration |
| **MasteryScore** | 用户对节点的掌握度 0~1 | Integration |
| **VirtualGraph** | 教学会话中 AI 产出的"虚拟图"中间层（节点 + 内部边 + RAG 检索） | Teaching → Integration |

---

## 3. 用户旅程

### 3.1 第一次使用（Onboarding）
```
1. 管理员创建账号（`scripts/admin.py create_user`，用户名 + 密码）
2. 创建第一个 Project（例："高等代数"）
3. 引导：先去 Input Level 写一篇笔记
4. 引导：把笔记里的概念"提取"出来进入 Teaching Level
5. 引导：完成第一次"教 AI"会话
6. 引导：把掌握的概念"沉淀"到 Integration 图谱
7. 引导：去 Practice 开始一轮练习（复习题由后台批量生成）
```

### 3.2 日常使用：学习新内容
```
Input Level:
  - 打开 Project
  - 选 / 创建 Directory（例：第 3 章 特征值）
  - 创建 Note（例：特征值定义）
  - 写笔记（支持 Markdown + KaTeX）
  - 写完后，点 "提取到 Teaching" 按钮
```

### 3.3 日常使用：复习（核心场景 A：教 AI）
```
Teaching Level:
  - 系统拉取 Note 内容作为"讲解素材"
  - AI 启动 prompt："请讲解【特征值】，我会追问"
  - 用户讲（文字输入）
  - AI 追问 / 质疑 / 要求举例
  - 用户答错 → AI 标记为 Misconception
  - 用户答对 / 讲清楚 → AI 标记为 Concept
  - 一轮讲完后：
      - 用户选"哪些 Concept 要进 Integration"
      - AI 帮润色节点描述
  - 用户点"沉淀"→ Integration 图谱更新
  - 出题不在对话内进行：沉淀后由 Practice 会话创建时按需批量生成复习题（见 F-12）
```

### 3.4 日常使用：复习（核心场景 B：做练习）
```
Practice Level:
  - 每天 / 每次进入，系统列出"今日待复习"
  - 每道题基于某个 Concept（链接到 Integration 节点）
  - 用户作答（多种题型：选择 / 填空 / 简答 / 编程）
  - 系统判对错（AI 判主观题 / 规则判客观题）
  - 答对 → 拉长复习间隔
  - 答错 → 缩短间隔 + 自动生成"未掌握"标记
  - 错误累积到一定阈值 → 触发对应 Concept 的新一轮 Teaching
  - 答对 / 答错后 → 更新对应 Integration 节点的 MasteryScore
```

### 3.5 长期使用：回顾图谱
```
Integration Level:
  - 打开 Graph
  - 看到所有已掌握的概念 + 关联
  - 节点颜色 / 大小 = MasteryScore
  - 点击节点 → 可：
      ① 重新进入 Teaching 强化
      ② 进入 Practice 做题
      ③ 编辑节点描述 / 关联
  - 拖拽节点 → 调整关联
  - 节点之间的边：Prerequisite / Parent / Related
```

---

## 4. 核心功能列表

### 4.1 MVP 必须有（P0）

| 编号 | 功能 | 描述 | 层级 |
|------|------|------|------|
| F-01 | 用户登录/服务器端注册* | username + password，JWT 认证 | 全局 |
| F-02 | Project CRUD | 创建、列表、重命名、删除 | 全局 |
| F-03 | i18n 框架 | babel + .po/.mo，zh-CN + en-US 切换 | 全局 |
| F-04 | Input Level：Directory CRUD | 在 Project 下建目录树 | Input |
| F-05 | Input Level：Note CRUD | 在 Directory 下建笔记，Markdown + KaTeX | Input |
| F-06 | Note 内容提取 | 从 Note 中 AI 抽取"可教的概念"列表（去重：跳过项目内已有概念） | Input → Teaching |
| F-07 | Teaching 会话 | 选 Concept → 开始会话（AI 启动 + 用户讲 + AI 追问） | Teaching |
| F-08 | Teaching 流式输出 | SSE 流式显示 AI 回应（thinking / text / concept / misconception / tool_call / task_complete / done） | Teaching |
| F-09 | Misconception 标记 | AI 自动识别用户答错 / 讲不清的点（mark_misconception 工具） | Teaching |
| F-10 | Concept 标记 | AI 自动识别用户已掌握的概念（mark_concepts_mastered 工具） | Teaching |
| F-11 | Teaching → Integration | 选 Concept → 写入 Integration 节点（挂载式合并沉淀） | Teaching → Integration |
| F-12 | Practice：批量出题 | 沉淀后不立即出题；Practice 会话创建时若题库不足，后台 job 批量生成 10 道（6 简单 + 4 拓展），可轮询进度 / 撤销 | Teaching → Practice |
| F-13 | Practice：做题界面 | 一次会话 10 道题（复习范围内优先，题库补足），作答即反馈 | Practice |
| F-14 | Practice：AI 判主观题 | 简答 / 编程题由 AI 对照参考答案赋分 0~100，score ≥ 60 判对 | Practice |
| F-15 | Practice：基础调度 | "今日待复习"列出到期题目；答对间隔翻倍 / 答错减半（≥1 天）；24 小时内不重复作答同一题 | Practice |
| F-16 | Practice → Teaching 触发 | 错题累积到阈值触发新一轮 Teaching（横幅提醒，不打断做题） | Practice → Teaching |
| F-17 | Practice → Integration 更新 | 答题结果更新概念关联的全部节点 MasteryScore（±0.05，同事务） | Practice → Integration |
| F-18 | Integration Graph 查看 | 节点 + 边的可视化（Cytoscape.js + dagre） | Integration |
| F-19 | 节点关系编辑 | 在 Graph 上加边、删边、改类型 | Integration |
| F-20 | MasteryScore 显示 | 节点颜色 / 大小 / 进度条反映掌握度 | Integration |
| F-32 | Practice 题库 | 项目内全部题目浏览（答案默认折叠），按题目内容 / 考点（概念名）搜索 | Practice |
| F-33 | Practice 后台出题 job | 独立线程运行，`GET /api/practice/generate-job/{id}` 轮询、可取消；撤销后已生成题目保留在题库 | Practice |
| F-34 | Integration 虚拟图 | 教学会话中 AI 产出"虚拟图"中间层：节点（含 properties / content / 掌握度）+ 内部边 + 与真实图关联，支持 RAG 语义检索 | Teaching → Integration |
| F-35 | 虚拟节点沉淀（挂载式合并） | 推送虚拟图节点到真实图谱：同名节点复用（mastery 取大）、子节点/边去重创建、新节点自动挂载最近邻（embedding 相似度）、内部边投影为真实边 | Integration |
| F-36 | 项目详情页 | 笔记组件 / 教 AI 复习组件 / 继续练习组件 / 学习连胜天数，四个 Widget 一页聚合 | 全局 |

* 处于安全性考虑，不开放用户自主注册，只允许用户联系管理员在服务器终端完成新用户注册：
  `python scripts/admin.py create_user <username> <password>`（另有 list_users / delete_user）。

### 4.2 第二版（P1）
- F-21 Note 内嵌图谱小窗
- F-22 概念间的自动关联建议（embedding 相似度）→ 已部分落地（F-35 挂载式最近邻推荐）
- F-23 Teaching 会话的"重听"模式（回放教学过程）
- F-24 全文搜索（SQLite FTS5）→ 当前为题库 LIKE 检索（F-32）
- F-25 数据导出 / 导入（JSON 备份）
- F-26 Practice 高级调度（FSRS 算法替代简单时间间隔）
- F-27 Practice 多题型支持（多选、匹配、代码题）

### 4.3 第三版（P2）
- F-28 多用户 + 简单分享
- F-29 PWA 离线支持
- F-30 Tauri 桌面打包
- F-31 教学模板市场（用户分享"教法"）

### 4.4 详细功能规格（F-16 ~ F-18）

> 功能表中的一行描述在此展开为：**功能概述 / 业务规则 / 交互流程 / 验收标准**。
> 规格与现有实现（`app/routers/practice.py`、`app/routers/integration.py`、`app/templates/integration/graph.html`）对齐。

#### F-16 Practice → Teaching 触发（错题累积触发新一轮 Teaching）

**功能概述**

当某个 Concept 关联的题目反复答错时，系统判定该概念"未掌握"，为该 Concept 生成新一轮 Teaching 会话的建议入口，把用户重新拉回"教 AI"环节，实现 §1.1 的闭环：**做练习（暴露薄弱点）→ 触发新一轮教 AI（巩固）**。

**业务规则**

| 规则 | 说明 |
|------|------|
| 触发阈值 | 同一 `concept_id` 的 ReviewRecord 满足任一条件即触发：<br>① 滚动窗口内**连续答错 3 次**；<br>② 最近 10 次作答中**答错 ≥ 6 次**（答错率 ≥ 60% 且答错次数 ≥ 3） |
| 判定口径 | 与 F-17 一致：客观题按 `is_correct`；主观题 AI 赋分 score ≥ 60 视为答对 |
| 幂等保护 | 若该 Concept 已存在一条**来源为 practice_trigger 且未归档**的 TeachingSession，则不重复创建；该触发会话归档后计数重新累积 |
| 创建动作 | 自动创建 `teaching_sessions` 新行（status=active），标题如"复习：{概念名}"，并把错题背景（题干 + 用户答案 + AI 反馈）写入首条 system 消息，作为 Teaching AI 的开局上下文 |
| 不打断流程 | 只创建会话与提示入口，**不自动开始对话**、不弹窗打断做题 |
| 展示位置 | ① Practice 首页（today）未完成触发会话横幅；② 作答结果 partial（result）提示"建议重新教一遍" |
| 阈值可配置 | 阈值（连续 3 次 / 窗口 10 次 / 答错率 60%）以常量集中在 `app/routers/practice.py`，P1 按 F-26 FSRS 预测动态调整 |

**交互流程**

```
ReviewRecord(答错) ──▶ 触发检查（同 concept 连续答错 / 近 10 次答错率）
  ├─ 未达阈值 ──▶ 不处理
  └─ 达到阈值 ──▶ 幂等检查（已有 practice_trigger 会话？）
        ├─ 已有 ──▶ 不重复创建
        └─ 无 ──▶ 创建 TeachingSession（标题=复习:{概念名}，错题背景入 system 消息）
                  ──▶ Practice 首页横幅 + 会话完成页提示："建议重新教一遍：{概念名}"
                  ──▶ 用户点击 ──▶ 跳转 /api/teaching/sessions/{id}（AI 开局即追问薄弱点）
```

**验收标准**

- [ ] 同一概念连续答错 3 次后，Practice 首页出现"建议重新教一遍"横幅
- [ ] 横幅含概念名，点击后进入可正常对话的 Teaching 会话
- [ ] 新会话的 AI 首条回复引用错题内容（错题背景上下文生效）
- [ ] 触发会话未归档前，再次答错不重复创建会话
- [ ] 未达阈值（如只错 1 次）时不出现任何提示
- [ ] 做题流程全程不被中断（无弹窗、无自动跳转）

#### F-17 Practice → Integration 更新（答题结果更新 MasteryScore）

**功能概述**

每次作答判定完成后，把结果沉淀到 Integration 层：更新该题目关联 Concept 所对应图谱节点的 `mastery_score`（0~1），让做题结果直接反映为图谱上的掌握度变化（配合 F-18 的进度条可视化与 F-20 的掌握度显示）。

**业务规则**

| 规则 | 说明 |
|------|------|
| 触发时机 | 每次 `POST /api/practice/answers` 判定完成后，与 ReviewRecord、ReviewSchedule 更新**同一事务**内执行 |
| 判定口径 | 客观题（choice/fill）规则判分得 `is_correct`；主观题（short/code）AI 赋分 score ≥ 60 视为答对 |
| 更新公式 | 答对：`mastery = min(mastery + 0.05, 1.0)`；答错：`mastery = max(mastery - 0.05, 0.0)` |
| 关联链路 | `practice_session_questions.question_id → questions.concept_id → nodes.concept_id` |
| 无节点保护 | 题目无 concept_id，或该 concept 尚未沉淀为节点时跳过更新（不报错、不建节点） |
| 多点一致性 | 同一 concept 关联多个节点时，**全部**节点按同一规则更新（当前实现即全量更新） |
| 兼容性 | 与 `app/services/graph_mount.py` 的"merge_or_create 取较大 mastery"策略兼容，沉淀逻辑不会把已增长的值覆盖回更小值 |
| P1 演进 | 固定步长 ±0.05 替换为按 FSRS 难度 / 间隔加权，或按错题累积强度衰减（如最近一次答对 +0.1、连续答对递减） |

**交互流程**

```
POST /api/practice/answers
  → grade_answer（客观规则 / 主观 AI 赋分 0~100）
  → 写 practice_session_questions（作答状态）
  → 写 ReviewRecord（score、is_correct、feedback）
  → 更新 ReviewSchedule（interval ×2 / ÷2，next_review_at）
  → 更新 nodes.mastery_score（F-17，同事务，该 concept 全部节点）
  → F-16 错题阈值检查（幂等，可能创建触发会话）
  → commit → 返回 result partial（HTMX）或 JSON
```

**验收标准**

- [ ] 答对后节点 mastery_score +0.05，答错后 -0.05
- [ ] 边界：mastery 到 1.0 后答对不再增长；到 0.0 后答错不再下降
- [ ] 题目无 concept_id 或 concept 未沉淀节点时，作答流程不受影响
- [ ] 更新与 ReviewRecord / ReviewSchedule 同事务：任一步失败整体回滚
- [ ] 刷新 Integration 图谱页后，节点进度条反映最新掌握度

#### F-18 Integration Graph 查看（节点 + 边的可视化）

**功能概述**

项目级知识图谱可视化页面（`/integration/{project_id}`）：节点 = 概念（`nodes` 表），边 = 关系（`edges` 表，Prerequisite / Parent / Related）。采用 Cytoscape.js + dagre 分层布局，节点以"深色底 + 灰色进度条填充"直观表达 MasteryScore，点击节点查看掌握度详情（配合 F-19 加边删边、F-20 掌握度显示）。

**业务规则**

| 规则 | 说明 |
|------|------|
| 技术选型 | Cytoscape.js 3.30 + dagre（TB 自顶向下）+ graphlib，CDN 引入、无构建步骤 |
| 图谱组织 | 一个项目可有多个图谱（`graphs.directory_id` 关联目录），页面右上角下拉切换（`?graph_id=` 参数） |
| 节点样式 | 圆角矩形；深色背景 + 灰色进度条填充（宽度 = mastery%）；文本自动换行、尺寸自适应标签长度；mastery ≥ 0.8 边框高亮 |
| 边样式 | 三类关系着色：prerequisite（橙）/ parent（紫）/ related（蓝），带箭头指向 target 与 label |
| 布局与导航 | dagre 自顶向下分层；缩放 0.2~3；滚轮缩放、拖拽平移、点击空白取消选中 |
| 工具栏 | `+` 新建节点；`⤢` 新建边（无节点时禁用）；`⊡` 适应视图 |
| 右侧面板 | Tab：详情（选中节点名称 + 掌握度进度条 + 编辑/删除）/ 全部关联（列表 + 删边）/ 待沉淀概念（勾选 → 一键 promote，见 F-11） |
| 空状态 | 无节点时展示引导 + "添加第一个节点"按钮；无图谱时提示先沉淀概念 |
| 数据来源 | `GET /api/integration/graphs/{project_id}`、`/nodes/{graph_id}`、`/edges/{graph_id}`；页面服务端渲染首屏，后续操作走 fetch |
| 规模约束 | 单图建议 ≤ 500 节点（MVP 学习场景足够），超过后按目录拆多个图谱 |

**交互流程**

```
GET /integration/{project_id}（服务端渲染）
  → 查询 graphs（当前 graph_id，默认第一个）
  → 查询 nodes（含 mastery_score、concept_status）+ edges（join 源/目标 label）
  → dagre 布局渲染节点与边
  → 点击节点 → 右侧面板显示掌握度详情（JS 更新，无请求）
  → 点 + / ⤢ → 模态框 → POST/PUT /api/integration/nodes|edges → 刷新
  → 下拉切换图谱 → 携带 ?graph_id= 重新加载
```

**验收标准**

- [ ] 打开图谱页能看到全部节点与边，布局为自顶向下分层
- [ ] 节点进度条宽度与 mastery_score 一致（0% ~ 100%）
- [ ] prerequisite / parent / related 三类边颜色可区分，带箭头与 label
- [ ] 点击节点在右侧面板显示名称与掌握度，可编辑 / 删除
- [ ] 工具栏可新建节点、新建边（source ≠ target 校验）、适应视图
- [ ] 多图谱项目可通过下拉切换，切换后 URL 带 `graph_id` 且可刷新直达
- [ ] 空图显示空状态引导，无报错
- [ ] 沉淀（F-11）后新节点实时出现在图谱并重新布局

---

## 5. 技术架构

### 5.1 整体架构

```
┌──────────────────────────────────────────────┐
│  Browser                                      │
│  - HTML（FastAPI 渲染）                        │
│  - Tailwind CSS（CDN / build）                 │
│  - HTMX（局部更新 / SSE）                      │
│  - Alpine.js（轻交互）                         │
│  - KaTeX（CDN，数学渲染）                       │
└──────────────────┬───────────────────────────┘
                   │ HTTP + SSE
┌──────────────────▼───────────────────────────┐
│  FastAPI (Python 3.11)                        │
│  ┌──────────────────────────────────────┐    │
│  │  Routers                             │    │
│  │  - pages      (页面路由 HTML)         │    │
│  │  - /auth      (注册 / 登录 / JWT)     │    │
│  │  - /api/projects    (项目 CRUD)      │    │
│  │  - /api/input       (Directory/Note) │    │
│  │  - /api/teaching    (教学会话 SSE)    │    │
│  │  - /api/practice    (做题 + 调度)     │    │
│  │  - /api/integration (Graph/Node/Edge)│    │
│  │  - /api/integration (promote 挂载)    │    │
│  └──────────────────────────────────────┘    │
│  ┌──────────────────────────────────────┐    │
│  │  Services                            │    │
│  │  - ai_service.py        (DeepSeek)   │    │
│  │  - teaching_agent.py    (工具调用)    │    │
│  │  - concept_extractor.py              │    │
│  │  - question_generator.py (出题+阅卷) │    │
│  │  - practice_jobs.py     (后台出题)   │    │
│  │  - graph_mount.py       (挂载式合并) │    │
│  │  - embedding_service.py (本地向量)   │    │
│  └──────────────────────────────────────┘    │
│  ┌──────────────────────────────────────┐    │
│  │  i18n (babel)                        │    │
│  │  - locales/zh_CN/LC_MESSAGES/        │    │
│  │  - locales/en_US/LC_MESSAGES/        │    │
│  └──────────────────────────────────────┘    │
│  ┌──────────────────────────────────────┐    │
│  │  Models (SQLAlchemy 2.0)            │    │
│  │  - base / user / input(Project/Dir/Note)│ │
│  │  - teaching / practice / integration │    │
│  └──────────────────────────────────────┘    │
│  ┌──────────────────────────────────────┐    │
│  │  Database                            │    │
│  │  - SQLite (./data/r6ax.db)          │    │
│  │  - 向量：sentence-transformers +    │    │
│  │    NumPy 余弦相似度（无 sqlite-vec） │    │
│  └──────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
```

### 5.2 关键技术选型

| 维度 | 选型 | 版本 | 理由 |
|------|------|------|------|
| **后端框架** | FastAPI | 0.115+ | async、SSE、自动 OpenAPI 文档 |
| **ASGI 服务器** | Uvicorn | 0.32+ | FastAPI 官方推荐 |
| **模板** | Jinja2 | 3.1+ | FastAPI 原生 |
| **i18n** | babel | 2.16+ | 标准方案，工具链齐全（pybabel extract / init / update / compile） |
| **数据库** | SQLite | 3.45+ | 零运维 |
| **ORM** | SQLAlchemy 2.0 | 2.0+ | 异步友好 |
| **向量检索** | sentence-transformers + NumPy | 2.2+ | 本地模型（all-MiniLM-L6-v2），向量存 JSON + 余弦相似度；无 sqlite-vec |
| **认证** | python-jose + passlib | 3.3+ / 1.7+ | JWT 签发；密码 PBKDF2-SHA256 哈希 |
| **AI SDK** | openai (兼容 DeepSeek) | 1.50+ | DeepSeek 兼容 OpenAI SDK（含工具调用） |
| **AI 编排** | 自定义 TeachingAgent（普通 async 函数） | — | OpenAI 工具调用 + SSE 流式；未引入 LangGraph |
| **数学渲染** | KaTeX | 0.16+ | CDN |
| **Markdown** | markdown-it-py | 3.0+ | 服务端渲染 |
| **前端样式** | Tailwind CSS | 3.4+ | 实用优先 |
| **前端交互** | HTMX | 2.0+ | 不编译 |
| **轻状态** | Alpine.js | 3.14+ | 折叠 / 弹窗等 |
| **容器** | Docker + Compose | 24+ | 一键启动 |

### 5.3 依赖清单（pyproject.toml，与代码一致）

> 实际以 `pyproject.toml` 为准；仓库不使用 `uv.lock` / `requirements.txt`。

```toml
[project]
name = "r6ax-learn"
version = "0.1.0-beta.2"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "jinja2>=3.1",
    "babel>=2.16",                       # i18n
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.20",
    "pydantic>=2.9",
    "pydantic-settings>=2.5",
    "python-multipart>=0.0.12",
    "python-jose[cryptography]>=3.3",    # JWT
    "passlib>=1.7",                      # 密码哈希 (PBKDF2-SHA256)
    "openai>=1.50",
    "markdown-it-py>=3.0",
    "mdit-py-plugins>=0.4",
    "httpx>=0.27",
    "sentence-transformers>=2.2",        # 本地 embedding（容器友好）
    "numpy>=1.24",                       # 向量计算
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "ruff>=0.6",
    "mypy>=1.11",
]
```

### 5.4 i18n 架构

**目录结构**：
```
app/
├── i18n/
│   ├── i18n.py                  # t() 函数 + ContextVar locale
│   ├── middleware.py            # locale 探测（Cookie / Accept-Language）
│   ├── locales/
│   │   ├── zh_CN/LC_MESSAGES/messages.po / .mo
│   │   └── en_US/LC_MESSAGES/messages.po / .mo
│   └── scripts/
│       ├── extract.sh           # pybabel extract
│       └── compile.sh           # pybabel compile
babel.cfg                        # 提取配置（根目录）
scripts/compile_i18n.py          # 一键编译脚本（Python 跨平台）
```

**i18n.py 接口**（实现见 `app/i18n/i18n.py`）：
```python
from babel.support import Translations
from contextvars import ContextVar

current_locale = ContextVar("current_locale", default="zh_CN")  # middleware 设置

def t(key: str, **kwargs) -> str:
    """按当前请求 locale 返回翻译；当前 locale 缺失 key 时回退 zh_CN"""
    text = _get_translations(current_locale.get()).gettext(key)
    return text % kwargs if kwargs else text
```

**模板使用**：
```html
<h1>{{ t('home.welcome') }}</h1>
<button>{{ t('common.save') }}</button>
```

**locale 切换**：`LocaleMiddleware` 按 Cookie `locale`（优先）→ `Accept-Language` 探测；
登录页支持 `?locale=` 参数并回写 Cookie。无 URL 前缀方式。

**关键规则（开发约束）**：
- ❌ 模板里不允许硬编码中文 / 英文文案
- ✅ 所有用户可见文案必须从 .po 文件取
- ✅ 新增文案后跑 `pybabel extract` / `update` / `compile`（或 `python scripts/compile_i18n.py`）
- ✅ 翻译 key 用点分命名空间（`home.welcome`, `teaching.session.start_btn`）

---

## 6. 数据模型

### 6.1 ER 概览

```
User (1) ──< (N) Project
Project (1) ──< (N) Directory
Directory (1) ──< (N) Note
Project (1) ──< (N) TeachingSession
TeachingSession (1) ──< (N) Message
TeachingSession (1) ──< (N) Concept
TeachingSession (1) ──< (N) Misconception
Concept (1) ──< (N) Question
User (1) ──< (N) ReviewSchedule
Question (1) ──< (N) ReviewRecord
Question (1) ──< (N) PracticeSessionQuestion (N) ──> (1) PracticeSession
ReviewRecord (N) ──> (1) Concept（关联，经 Question）
Project (1) ──< (N) Graph（一个项目可有多张图谱；Graph 可关联 Directory）
Graph (1) ──< (N) Node
Graph (1) ──< (N) Edge
Node (N) ──> (1) Concept（可选关联）
Node (1) ──< (N) NodeEmbedding
TeachingSession (1) ──< (N) VirtualGraph ──< (N) VirtualGraphNode / VirtualGraphEdge / VirtualGraphToNodeEdge
VirtualGraph (1) ──< (N) VirtualGraphEmbedding
```

### 6.2 表结构（核心字段，与 `app/models/` 对齐）

> 所有主键 / 外键均为 `VARCHAR`（uuid4 字符串），非自增整数。

```sql
-- users
id (PK, =username), username (UNIQUE), password_hash, preferred_locale, created_at

-- projects
id (PK), user_id (FK), name, description, created_at, updated_at

-- directories
id (PK), project_id (FK), parent_id (FK, nullable), name, description, order_index

-- notes
id (PK), directory_id (FK, nullable), title, content (TEXT, markdown), created_at, updated_at

-- teaching_sessions
id (PK), project_id (FK), source_note_id (FK, nullable), trigger_concept_id (FK, nullable),
        title, status (active/archived/completed), created_at, updated_at

-- messages（支持分支编辑）
id (PK), session_id (FK), parent_id (FK, nullable), branch_id (nullable),
        role (user/assistant/system), content (TEXT), extra_data (JSON), is_active, created_at

-- concepts
id (PK), session_id (FK), name, description, user_explanation, status (mastered/learning/promoted)

-- misconceptions
id (PK), session_id (FK), concept_name, user_claim, ai_correction, resolved

-- questions
id (PK), concept_id (FK, nullable), question_type (choice/fill/short/code),
        prompt, answer, explanation, difficulty (FLOAT, 默认 1.0),
        is_extension (BOOL), knowledge_points (TEXT JSON), rationale (TEXT), created_at

-- practice_sessions（一次 10 题的练习会话）
id (PK), user_id (FK), project_id (FK), status (active/completed), created_at, completed_at

-- practice_session_questions
id (PK), session_id (FK), question_id (FK), order_index,
        user_answer, score, feedback, answered_at

-- review_schedules
id (PK), user_id (FK), question_id (FK), next_review_at, interval_days (FLOAT), ease_factor

-- review_records
id (PK), schedule_id (FK), user_answer, is_correct, score (0~100), ai_feedback, reviewed_at

-- graphs（一项目多图谱，可关联目录）
id (PK), project_id (FK), directory_id (FK, nullable), name, created_at, updated_at

-- nodes
id (PK), graph_id (FK), concept_id (FK, nullable), label, mastery_score (0-1, DEFAULT 0)

-- edges
id (PK), graph_id (FK), source_node_id (FK), target_node_id (FK),
        relation (prerequisite/related/parent), label, weight

-- node_embeddings（向量以 JSON 文本存储，非虚表）
id (PK), node_id (FK), embedding (TEXT, JSON 数组)

-- virtual_graphs（虚拟图中间层）
id (PK), session_id (FK), graph_id (FK, nullable), name, description, created_at, updated_at

-- virtual_graph_nodes
id (PK), virtual_graph_id (FK), node_id (FK, nullable), label,
        properties (TEXT JSON 二元组), content, order_index, mastery_score

-- virtual_graph_edges
id (PK), virtual_graph_id (FK), source_vnode_id (FK), target_vnode_id (FK),
        relation (prerequisite/related/next/detail...), label

-- virtual_graph_to_node_edges（虚拟图 ↔ 真实节点关联）
id (PK), virtual_graph_id (FK), node_id (FK), relation_type (contains/references/expands)

-- virtual_graph_embeddings（RAG 检索用）
id (PK), virtual_graph_id (FK), embedding (TEXT JSON)
```

---

## 7. 项目结构

```
R6AX-Learn/                          # 项目根
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml                   # 依赖（无 uv.lock / requirements.txt）
├── babel.cfg                        # pybabel 提取配置
├── bootstrap.sh / install.sh / install.bat
├── .env.example
├── README.md
├── docs/                            # 文档
│   ├── PRD.md                       # 本文档
│   ├── install.md / bootstrap.md    # 安装 / 启动
│   ├── practice.md / widgets.md     # 功能说明
│   └── integration_guide.md         # 图谱集成指南
│
├── app/                             # FastAPI 应用
│   ├── main.py                      # 入口：中间件（CSRF / CORS / Locale）+ 挂载路由
│   ├── config.py                    # pydantic-settings（JWT_SECRET 必填校验）
│   │
│   ├── core/                        # 基础设施
│   │   ├── security.py              # python-jose + passlib (PBKDF2-SHA256)
│   │   ├── database.py              # SQLAlchemy 引擎 / session
│   │   └── deps.py                  # get_db / get_current_user / require_*
│   │
│   ├── i18n/                        # 国际化
│   │   ├── i18n.py                  # t() + ContextVar locale
│   │   ├── middleware.py            # Cookie / Accept-Language 探测
│   │   ├── locales/zh_CN,en_US/LC_MESSAGES/messages.{po,mo}
│   │   └── scripts/extract.sh, compile.sh
│   │
│   ├── models/                      # SQLAlchemy 模型
│   │   ├── base.py                  # Base / 公共列
│   │   ├── user.py
│   │   ├── input.py                 # Project / Directory / Note
│   │   ├── teaching.py              # TeachingSession / Message / Concept / Misconception
│   │   ├── practice.py              # Question / ReviewSchedule / ReviewRecord / PracticeSession / PSQuestion
│   │   └── integration.py           # Graph / Node / Edge / NodeEmbedding / VirtualGraph 系列
│   │
│   ├── schemas/                     # Pydantic schema（auth/project/input/teaching/practice/integration）
│   │
│   ├── routers/                     # FastAPI 路由
│   │   ├── pages.py                 # 页面路由（/login /projects /input /teaching /practice /integration）
│   │   ├── auth.py                  # /api/auth（register / login / me）
│   │   ├── projects.py              # /api/projects
│   │   ├── input.py                 # /api/input（Directory / Note / 提取概念）
│   │   ├── teaching.py              # /api/teaching（会话 + SSE stream + promote + 虚拟图工具）
│   │   ├── practice.py              # /api/practice（bank / sessions / answers / generate-job）
│   │   ├── integration.py           # /api/integration（Graph / Node / Edge / VirtualGraph）
│   │   └── integration_promote.py   # /api/integration/promote-virtual-node（挂载式沉淀）
│   │
│   ├── services/                    # 业务逻辑
│   │   ├── ai_service.py            # DeepSeek 封装（chat / stream / tools）
│   │   ├── teaching_agent.py        # 自定义 TeachingAgent（工具调用循环，无 LangGraph）
│   │   ├── concept_extractor.py     # 从 Note 提取概念
│   │   ├── question_generator.py    # 出题（6+4）+ AI 阅卷 grade_answer
│   │   ├── practice_jobs.py         # 后台出题 job（线程 + 可撤销）
│   │   ├── graph_mount.py           # 挂载式合并 / 挂载 / 边投影 / 去重
│   │   └── embedding_service.py     # sentence-transformers + NumPy 余弦
│   │
│   ├── templates/                   # Jinja2 模板
│   │   ├── base.html / index.html
│   │   ├── auth/                    # login.html / register.html
│   │   ├── pages/                   # home / project_list / project_detail
│   │   ├── input_level/note_editor.html
│   │   ├── teaching/                # session_list / session（SSE 会话页）
│   │   ├── practice/                # today / bank / session / question + partials/result,bank
│   │   ├── integration/graph.html   # Cytoscape + dagre 图谱页
│   │   └── components/markdown_editor.html
│   │
│   └── static/                      # 静态资源
│       └── js/                      # csrf.js / markdown-render.js（HTMX 等走 CDN）
│
├── scripts/                         # 运维 / 迁移脚本
│   ├── admin.py                     # create_user / list_users / delete_user
│   ├── compile_i18n.py              # 编译翻译
│   ├── download_embedding_model.py  # 预下载 embedding 模型（Docker 构建用）
│   ├── cleanup_graphs.py / cleanup_teaching.py
│   └── migrate_multi_graph.py / migrate_graphs_for_dirs.py
│
├── data/                            # 运行时数据（git ignore）
│   └── r6ax.db
│
└── tests/                           # 本地冒烟测试（不入库，见 README）
```

---

## 8. 关键交互流程

### 8.1 Teaching 会话（SSE 流式）

```
Browser                                  FastAPI                          DeepSeek
  │                                         │                                │
  │  POST /api/teaching/sessions           │                                │
  │  { project_id, title }                 │                                │
  │ ───────────────────────────────────────▶│                                │
  │  201 { session_id } + 首条 assistant 消息│                                │
  │ ◀───────────────────────────────────────│                                │
  │                                         │                                │
  │  POST /api/teaching/sessions/{id}/messages │                            │
  │  { content: "我来讲解..." }              │                                │
  │ ───────────────────────────────────────▶│                                │
  │  { status: ok, message_id }             │                                │
  │ ◀───────────────────────────────────────│                                │
  │                                         │                                │
  │  GET /api/teaching/stream/{id}?project_id=...（SSE）                      │
  │ ───────────────────────────────────────▶│                                │
  │                                         │ TeachingAgent.process_user_input │
  │                                         │ ── DeepSeek 流式工具调用 ──▶    │
  │  SSE: data: { type: "thinking" }        │                                │
  │ ◀───────────────────────────────────────│                                │
  │  SSE: data: { type: "text", content }   │                                │
  │ ◀───────────────────────────────────────│                                │
  │  SSE: data: { type: "concept", ... }    │  mark_concepts_mastered 结果    │
  │ ◀───────────────────────────────────────│                                │
  │  SSE: data: { type: "misconception" }   │  mark_misconception 结果        │
  │ ◀───────────────────────────────────────│                                │
  │  SSE: data: { type: "tool_call" }       │  虚拟图等工具执行结果            │
  │ ◀───────────────────────────────────────│                                │
  │  SSE: data: { type: "task_complete" }   │  task_complete 工具             │
  │ ◀───────────────────────────────────────│                                │
  │  SSE: data: { type: "done" }            │                                │
  │ ◀───────────────────────────────────────│                                │
```

- 服务端在流内循环执行工具调用（mark_concepts_mastered / mark_misconception /
  create_virtual_graph 等虚拟图工具 / task_complete），直到 task_complete；
- SSE 幂等：最后一条 user 消息已有 assistant 回复时直接 `done`（重连 / 重复触发不双写）；
- 消息支持分支编辑：`PUT /api/teaching/sessions/{id}/messages/{mid}` 改写后重新生成回复。

### 8.2 Teaching → Integration 沉淀（挂载式）

```
1. 用户在 Teaching 会话页（session.html）看到 AI 标记的所有 Concept 列表（带勾选框）
2. 用户勾选要沉淀的 Concept，点击"沉淀"
3. POST /api/teaching/sessions/{id}/promote
   body: { concept_ids: [...] }
4. 后端（graph_id 按 source_note → directory → graph 路径解析，缺省自动建图）：
   - 对每个 concept 在 Graph 中创建 / 合并 Node（merge_or_create：同名复用，mastery 取大）
   - 对每个 concept 创建初始 ReviewSchedule（next_review_at = now + 1 day）
   - 生成 embedding 写入 node_embeddings
   - 新节点挂载到最近邻已有节点（embedding 相似度，related 边，top_k=2）
5. 返回沉淀结果（节点 / 边 / 掌握度）
6. 另：虚拟图节点经 POST /api/integration/promote-virtual-node/{vnode_id}
   以挂载式合并沉淀（子节点 + 边去重 + 内部边投影到真实图谱）
```

> 出题不在此流程内：复习题由 Practice 会话创建时按需后台批量生成（见 8.3）。

### 8.3 Practice 做题闭环（10 题 / 会话）

```
1. 用户进 Practice 首页（/practice/{project_id}）：未完成 / 已完成会话 + F-16 触发横幅
2. POST /api/practice/sessions 开始会话：
   - 复习范围内到期题目优先（每用户 24h 内不重复作答同一题）
   - 不足 10 题时从题库补足；题库整体不足 → 启动后台出题 job（返回 job_id，可轮询 / 撤销）
3. 用户作答 → POST /api/practice/answers
4. 后端：
   - 客观题（choice/fill）：规则判对错；主观题（short/code）：AI 对照参考答案赋分 0~100，≥60 判对
   - 写 practice_session_questions 作答状态 + ReviewRecord（score）
   - 更新 ReviewSchedule：答对 interval ×2（封顶 100 天）、答错 ÷2（至少 1 天）
   - 更新该 Concept 关联的全部节点 MasteryScore（±0.05，同事务）
   - 错题累积到阈值 → 创建新一轮 Teaching 会话（幂等，标题"复习：{概念名}"，错题背景入 system 消息）
5. HTMX 返回 result partial（含评分、反馈、间隔、mastery 变化、触发提示）→ 切换下一题
6. 题库（/practice/{project_id}/bank）浏览全部题目，按题目 / 考点搜索，答案默认折叠
```

### 8.4 Teaching Agent（自定义工具调用循环，无 LangGraph）

```
┌─────────────────────────────────────────────────────────────┐
│  POST /api/teaching/stream/{session_id}（SSE）              │
│                                                             │
│  1. 组装上下文：会话消息历史 + 概念状态（mastered/learning）  │
│  2. DeepSeek 流式响应（text → SSE 逐块推送）                  │
│  3. 首轮工具调用批量执行：                                    │
│     ├─ mark_concepts_mastered   → concepts.status=mastered  │
│     ├─ mark_misconception       → misconceptions 表         │
│     ├─ 虚拟图工具（create/get/update/delete/search RAG）     │
│     └─ task_complete            → 结束标记（必须调用）        │
│  4. 未 task_complete → 携带工具结果进入多轮续跑循环           │
│     （agent.process_tool_results → 再次流式生成 → 再执行）    │
│  5. SSE 事件：thinking / text / concept / misconception /    │
│     tool_call / task_complete / done                        │
│  6. 全部概念 mastered → session 状态自动置为 completed        │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. AI Prompt 设计原则

PRD 不钉死具体 prompt。原则如下：

### 9.1 角色定位
- **Teaching AI**：聪明的学生 + 苏格拉底式提问者
  - 角色：用户讲解 → AI 追问 / 质疑 / 要求举例
  - 关键：**不主动给答案**（除非用户反复卡住）
- **Practice AI**：阅卷者
  - 角色：用户答题 → AI 判对错 + 给反馈
  - 关键：**评分 + 解释错因**（不止 yes/no）
- **Concept Extractor AI**：教学设计师
  - 角色：用户笔记 → AI 提取可教概念
- **Question Generator AI**：出题人
  - 角色：概念 → AI 批量生成一套题（6 简单 + 4 拓展，共 10 道），Practice 会话创建时后台触发

### 9.2 设计约束
- 每个 agent 的 prompt 作为**模块级常量**集中放在对应 service 文件顶部（`question_generator.py` 的 `GENERATE_SYSTEM_PROMPT`、`teaching_agent.py` 的 SYSTEM_PROMPT、`concept_extractor.py` 等）
- prompt 版本化（git 管理），方便 A/B 测试
- 关键决策：每个 agent 维护**示例 few-shot**（放 .py 或 .jsonl 文件）
- 输出格式：尽量让 LLM 返回**结构化 JSON**（便于后端解析）
- 失败兜底：JSON 解析失败时，fallback 到纯文本（如题目降级为简答题）

### 9.3 调优节奏
- 阶段 3（Teaching）实现时，先用最简单的 prompt 跑通流程
- 阶段 5（打磨）再做 prompt 调优，引入 few-shot
- 不在 PRD 阶段卡 prompt——具体效果跑起来看

### 9.4 提示词管理
- 禁止在模板 / 路由里内联散落大段 prompt
- 统一以模块级常量集中在 `app/services/` 对应文件顶部（`GENERATE_SYSTEM_PROMPT` 等）
- prompt 常量旁用注释说明：角色、输入输出格式、调优记录

---

## 10. 部署方案

### 10.1 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 系统依赖（编译 embedding 相关扩展）
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc g++ make libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY pyproject.toml .
RUN pip install --no-cache-dir hatchling \
    && pip install --no-cache-dir .

# 预下载 embedding 模型（避免运行时下载）
COPY scripts/download_embedding_model.py ./scripts/
RUN python scripts/download_embedding_model.py && rm -rf ~/.cache/huggingface

# 应用代码
COPY app/ ./app/
COPY scripts/ ./scripts/

# i18n 编译（构建时跑一次；失败不阻塞构建）
RUN pybabel compile -d app/i18n/locales 2>/dev/null || true

# 数据目录
RUN mkdir -p /app/data
VOLUME /app/data

# 环境变量
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 10.2 docker-compose.yml

```yaml
services:
  app:
    build: .
    container_name: r6ax-learn
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./.env:/app/.env:ro
    environment:
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - JWT_SECRET=${JWT_SECRET}
    restart: unless-stopped
```

### 10.3 启动命令

```bash
# 1. 准备环境
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY 和 JWT_SECRET（≥32 字符随机串，否则拒绝启动）

# 2. 一键启动
docker compose up -d

# 3. 创建用户（无默认账号；管理员工具，终端执行）
docker compose exec app python scripts/admin.py create_user <username> <password>

# 4. 访问
open http://localhost:8000
```

---

## 11. 关键风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 工具调用循环不收敛（AI 不调 task_complete） | 中 | 中 | 强约束 prompt + 多轮续跑上限；首轮工具调用批量执行 |
| SSE 在反向代理下断连 | 中 | 中 | 配置 proxy 的 `proxy_buffering off` + 合理 timeout；SSE 幂等防重复回复 |
| embedding 模型体积 / 首次加载慢 | 中 | 中 | 容器构建时预下载（download_embedding_model.py）；懒加载 + 内存缓存 |
| DeepSeek 限流 | 中 | 中 | 客户端重试 + 队列；后期考虑本地小模型兜底 |
| Jinja2 模板复杂度膨胀 | 低 | 中 | 严格分 partials / components；定期重构 |
| HTMX 调试困难 | 中 | 低 | 用 htmx:configRequest / htmx:beforeSwap 日志 |
| AI 输出格式不稳定 | 高 | 高 | 严 prompt + 输出 JSON 校验 + 失败重试 + 降级到非结构化输出 |
| 翻译 key 散乱 | 中 | 中 | 缺失 key 回退 zh_CN；CI 检查所有 .po 引用必须存在 |
| Practice 调度算法不够用 | 中 | 中 | MVP 用简单时间间隔，P1 升级 FSRS |

---

## 12. 实施路线图

### 阶段 0：基础设施
- [ ] 建仓库、初始化 pyproject.toml
- [ ] 写 Dockerfile + docker-compose.yml
- [ ] 写 .env.example
- [ ] 起 FastAPI 骨架，能访问 `/`
- [ ] 接入 Tailwind（CDN）+ HTMX + Alpine.js
- [ ] 写 base.html 模板
- [ ] 配 babel 工具链（extract.sh / compile.sh + scripts/compile_i18n.py）
- [ ] 写 `app/i18n/i18n.py`（t() 函数）
- [ ] 写 `app/i18n/middleware.py`（locale 探测）

### 阶段 1：认证 + Project + i18n
- [ ] User model + 注册 / 登录 API
- [ ] JWT 中间件
- [ ] Project CRUD（API + 页面）
- [ ] 首页 + 项目列表页（双语）
- [ ] 跑通 `pybabel extract → update → compile` 流程
- [ ] 验证 locale 切换

### 阶段 2：Input Level
- [ ] Directory / Note model
- [ ] Directory CRUD
- [ ] Note CRUD（Markdown + KaTeX 渲染）
- [ ] 笔记编辑器页面
- [ ] 目录树组件

### 阶段 3：Teaching Level 核心⭐
- [ ] TeachingSession / Message / Concept / Misconception model
- [ ] ai_service.py（DeepSeek 封装 + 流式）
- [ ] teaching_agent.py（自定义工具调用循环：mark 概念 / 误区 / 虚拟图 / task_complete）
- [ ] 教学会话页面（SSE 流式渲染 + 分支编辑）
- [ ] Concept / Misconception 标记的 UI

### 阶段 4：Practice Level 核心⭐
- [ ] Question / ReviewSchedule / ReviewRecord / PracticeSession model
- [ ] question_generator.py（出题 6+4 + AI 阅卷）
- [ ] practice_jobs.py（后台出题 job，可撤销）
- [ ] Practice 页面（today 会话列表 + 做题 + 结果 + 题库）
- [ ] 简单时间间隔调度
- [ ] 错题触发 Teaching 的提示机制（F-16）

### 阶段 5：Integration Level
- [ ] Graph / Node / Edge / Mastery model
- [ ] Graph 查看页面（Cytoscape + dagre）
- [ ] 节点 + 边的 CRUD
- [ ] 概念 → 节点的"沉淀"流程（挂载式合并，含虚拟图中间层）
- [ ] MasteryScore 显示
- [ ] Practice → MasteryScore 更新

### 阶段 6：闭环验证 + 打磨
- [ ] 端到端：Input → Teaching → Integration + Practice
- [ ] 错题触发 Teaching 闭环验证
- [ ] concept_extractor 调优
- [ ] 整体 UI 打磨
- [ ] 翻译 key 补齐（zh-CN / en-US 完整）

### 阶段 7：测试 + 文档
- [ ] 关键 API 单元测试
- [ ] i18n 测试（locale 切换、key 完整性）
- [ ] README 完整化
- [ ] 录一段端到端 demo 视频

---

## 13. 验收标准（MVP）

完成 MVP 后，系统应该能做到：

1. ✅ 管理员通过 `scripts/admin.py` 创建账号，用户能登录，看到自己的项目列表
2. ✅ 用户能在 zh-CN / en-US 间切换语言
3. ✅ 用户能在项目下建目录、写笔记
4. ✅ 用户能从笔记提取概念，进入 Teaching 会话
5. ✅ AI 能流式回应用户的讲解，进行苏格拉底式追问
6. ✅ AI 能正确标记 Misconception / Concept（≥ 80% 准确）
7. ✅ 用户能把 Concept 沉淀到 Integration 图谱（挂载式合并，同名节点复用）
8. ✅ 沉淀时创建 ReviewSchedule（1 天后到期），Practice 会话创建时按需批量出题（6 简单 + 4 拓展）
9. ✅ 用户能在 Practice 中做题（10 题/会话），AI 判主观题（0~100 赋分，≥60 判对）
10. ✅ Practice 错题能更新 MasteryScore（±0.05，全量节点），累积阈值触发 Teaching（幂等 + 横幅）
11. ✅ 用户能在 Graph 上看到节点和边、掌握度；题库可浏览 / 搜索
12. ✅ **四层闭环跑通**：Input → Teaching → Integration + Practice → 触发新 Teaching
13. ✅ 整个系统能通过 `docker compose up` 一键启动
14. ✅ 所有用户可见文案都从 .po 翻译文件取，无硬编码

---

## 14. 不在本文档范围

- 详细 UI 设计稿（用文字描述 + 简单 ASCII 图代替）
- 完整 API 文档（用 FastAPI 自动生成的 `/docs` 代替）
- 性能压测报告（v1.0 不追求性能）
- 安全审计（学习用，不联网暴露）
- **具体 prompt 内容**（阶段 3-5 实施时设计，本文档只给原则）
