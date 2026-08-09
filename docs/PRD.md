# R6AX:/LEARN 自学辅助软件 — 产品需求文档 (PRD)

> **版本**: R6AX:/Learn — PRD v0.2（重构版）

> 目标：彻底重写为 **Jinja2 + HTMX + FastAPI + SQLite + Docker** 架构。
> 旧代码（React/Express/JSON）不迁移、不兼容、删除即可。
> 旧数据（`users.json` / `projects.json` 等）作为产品对照参考，不导入。

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
| **Graph** | 知识图谱（一个项目对应一张图） | Integration |
| **Node** | 图谱中的节点（≈ 一个 Concept） | Integration |
| **Edge** | 节点之间的边（Prerequisite / Application / Related） | Integration |
| **MasteryScore** | 用户对节点的掌握度 0~1 | Integration |

---

## 3. 用户旅程

### 3.1 第一次使用（Onboarding）
```
1. 注册账号（用户名 + 密码）
2. 创建第一个 Project（例："高等代数"）
3. 引导：先去 Input Level 写一篇笔记
4. 引导：把笔记里的概念"提取"出来进入 Teaching Level
5. 引导：完成第一次"教 AI"会话
6. 引导：把掌握的概念"沉淀"到 Integration 图谱
7. 引导：基于概念生成第一道复习题
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
      - 同时：AI 自动为 Concept 生成 1~3 道复习题 → 进入 Practice
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
  - 节点之间的边：Prerequisite / Application / Related
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
| F-06 | Note 内容提取 | 从 Note 中 AI 抽取"可教的概念"列表 | Input → Teaching |
| F-07 | Teaching 会话 | 选 Concept → 开始会话（AI 启动 + 用户讲 + AI 追问） | Teaching |
| F-08 | Teaching 流式输出 | SSE 流式显示 AI 回应 | Teaching |
| F-09 | Misconception 标记 | AI 自动识别用户答错 / 讲不清的点 | Teaching |
| F-10 | Concept 标记 | AI 自动识别用户已掌握的概念 | Teaching |
| F-11 | Teaching → Integration | 选 Concept → 写入 Integration 节点 | Teaching → Integration |
| F-12 | Teaching → Practice | AI 为 Concept 自动生成 1~3 道复习题 | Teaching → Practice |
| F-13 | Practice：做题界面 | 显示题目 + 接收答案 + 反馈 | Practice |
| F-14 | Practice：AI 判主观题 | 简答 / 编程题由 AI 判断对错 | Practice |
| F-15 | Practice：基础调度 | 按"今日待复习"列出题目（简单时间间隔） | Practice |
| F-16 | Practice → Teaching 触发 | 错题累积到阈值触发新一轮 Teaching | Practice → Teaching |
| F-17 | Practice → Integration 更新 | 答题结果更新 MasteryScore | Practice → Integration |
| F-18 | Integration Graph 查看 | 节点 + 边的可视化 | Integration |
| F-19 | 节点关系编辑 | 在 Graph 上加边、删边、改类型 | Integration |
| F-20 | MasteryScore 显示 | 节点颜色 / 大小反映掌握度 | Integration |

* 处于安全性考虑，不开放用户自主注册，只允许用户联系管理员在服务器终端完成新用户注册

### 4.2 第二版（P1）
- F-21 Note 内嵌图谱小窗
- F-22 概念间的自动关联建议（用 embedding 相似度）
- F-23 Teaching 会话的"重听"模式（回放教学过程）
- F-24 全文搜索（SQLite FTS5）
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
| 展示位置 | ① Practice 首页"今日待复习"上方横幅；② 会话完成页（result partial） |
| 阈值可配置 | 阈值（连续 3 次 / 窗口 10 次 / 答错率 60%）作为配置项，P1 按 F-26 FSRS 预测动态调整 |

**交互流程**

```
ReviewRecord(答错) ──▶ 触发检查（同 concept 连续答错 / 近 10 次答错率）
  ├─ 未达阈值 ──▶ 不处理
  └─ 达到阈值 ──▶ 幂等检查（已有 practice_trigger 会话？）
        ├─ 已有 ──▶ 不重复创建
        └─ 无 ──▶ 创建 TeachingSession（标题=复习:{概念名}，错题背景入 system 消息）
                  ──▶ Practice 首页横幅 + 会话完成页提示："建议重新教一遍：{概念名}"
                  ──▶ 用户点击 ──▶ 跳转 /teaching/sessions/{id}（AI 开局即追问薄弱点）
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
| 触发时机 | 每次 `POST /practice/answers` 判定完成后，与 ReviewRecord、ReviewSchedule 更新**同一事务**内执行 |
| 判定口径 | 客观题（choice/fill）规则判分得 `is_correct`；主观题（short/code）AI 赋分 score ≥ 60 视为答对 |
| 更新公式 | 答对：`mastery = min(mastery + 0.05, 1.0)`；答错：`mastery = max(mastery - 0.05, 0.0)` |
| 关联链路 | `practice_session_questions.question_id → questions.concept_id → nodes.concept_id` |
| 无节点保护 | 题目无 concept_id，或该 concept 尚未沉淀为节点时跳过更新（不报错、不建节点） |
| 多点一致性 | 同一 concept 关联多个节点时，全部节点按同一规则更新（当前实现按首个匹配节点更新，P1 收敛为全量） |
| 兼容性 | 与 `app/services/graph_mount.py` 的"merge_or_create 取较大 mastery"策略兼容，沉淀逻辑不会把已增长的值覆盖回更小值 |
| P1 演进 | 固定步长 ±0.05 替换为按 FSRS 难度 / 间隔加权，或按错题累积强度衰减（如最近一次答对 +0.1、连续答对递减） |

**交互流程**

```
POST /practice/answers
  → grade_answer（客观规则 / 主观 AI 赋分）
  → 写 ReviewRecord（score、is_correct、feedback）
  → 更新 ReviewSchedule（interval、ease、next_review_at）
  → 更新 nodes.mastery_score（F-17，同事务）
  → commit → 返回 result partial
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
│  │  - /auth        (注册 / 登录 / JWT)   │    │
│  │  - /projects    (项目 CRUD)          │    │
│  │  - /input       (Directory / Note)   │    │
│  │  - /teaching    (教学会话 SSE)        │    │
│  │  - /practice    (做题 + 调度)         │    │
│  │  - /integration (Graph / Node / Edge) │    │
│  └──────────────────────────────────────┘    │
│  ┌──────────────────────────────────────┐    │
│  │  Services                            │    │
│  │  - ai_service.py    (DeepSeek 封装)  │    │
│  │  - teaching_agent.py (LangGraph)     │    │
│  │  - practice_agent.py (调度 + 判题)   │    │
│  │  - concept_extractor.py              │    │
│  │  - misconception_detector.py         │    │
│  │  - question_generator.py             │    │
│  │  - embedding_service.py (sqlite-vec) │    │
│  └──────────────────────────────────────┘    │
│  ┌──────────────────────────────────────┐    │
│  │  i18n (babel)                        │    │
│  │  - locales/zh_CN/LC_MESSAGES/        │    │
│  │  - locales/en_US/LC_MESSAGES/        │    │
│  └──────────────────────────────────────┘    │
│  ┌──────────────────────────────────────┐    │
│  │  Models (SQLAlchemy 2.0)            │    │
│  │  - User / Project / Directory / Note │    │
│  │  - TeachingSession / Concept / Misc. │    │
│  │  - Question / ReviewSched / Review   │    │
│  │  - Graph / Node / Edge / Mastery     │    │
│  └──────────────────────────────────────┘    │
│  ┌──────────────────────────────────────┐    │
│  │  Database                            │    │
│  │  - SQLite (./data/r6ax.db)          │    │
│  │  - sqlite-vec 扩展 (embedding)       │    │
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
| **向量库** | sqlite-vec | latest | 嵌入式，存 embedding |
| **认证** | PyJWT + bcrypt | latest | 学习用足够 |
| **AI SDK** | openai (兼容 DeepSeek) | 1.50+ | DeepSeek 兼容 OpenAI SDK |
| **AI 框架** | LangGraph | 0.2+ | 状态机适合 Teaching 流程 |
| **数学渲染** | KaTeX | 0.16+ | CDN |
| **Markdown** | markdown-it-py | 3.0+ | 服务端渲染 |
| **前端样式** | Tailwind CSS | 3.4+ | 实用优先 |
| **前端交互** | HTMX | 2.0+ | 不编译 |
| **轻状态** | Alpine.js | 3.14+ | 折叠 / 弹窗等 |
| **容器** | Docker + Compose | 24+ | 一键启动 |

### 5.3 依赖清单（pyproject.toml）

```toml
[project]
name = "r6ax-learn"
version = "1.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "jinja2>=3.1",
    "babel>=2.16",                       # i18n
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.20",
    "sqlite-vec>=0.1",
    "pydantic>=2.9",
    "pydantic-settings>=2.5",
    "python-multipart>=0.0.12",
    "pyjwt>=2.9",
    "bcrypt>=4.2",
    "openai>=1.50",
    "langgraph>=0.2",
    "langchain-core>=0.3",
    "markdown-it-py>=3.0",
    "mdit-py-plugins>=0.4",
    "httpx>=0.27",
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
├── i18n.py                  # t() 函数封装
└── locales/
    ├── messages.pot         # 模板提取的源文件
    ├── zh_CN/
    │   └── LC_MESSAGES/
    │       └── messages.po
    └── en_US/
        └── LC_MESSAGES/
            └── messages.mo
```

**i18n.py 接口**：
```python
from babel.support import Translations

def t(key: str, **kwargs) -> str:
    """根据当前请求 locale 返回翻译字符串"""
    return get_translations().gettext(key) % kwargs
```

**模板使用**：
```html
<h1>{{ t('home.welcome') }}</h1>
<button>{{ t('common.save') }}</button>
```

**locale 切换**：URL 前缀（`/zh/...` / `/en/...`）或 Cookie + 浏览器 Accept-Language 探测。

**关键规则（开发约束）**：
- ❌ 模板里不允许硬编码中文 / 英文文案
- ✅ 所有用户可见文案必须从 .po 文件取
- ✅ 新增文案后跑 `pybabel extract` / `update` / `compile`
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
Project (1) ──< (N) ReviewSchedule
Question (1) ──< (N) ReviewRecord
ReviewRecord (N) ──> (1) Concept（关联）
Project (1) ──< (1) Graph
Graph (1) ──< (N) Node
Graph (1) ──< (N) Edge
Node (N) ──> (1) Concept（可选关联）
Node (1) ──< (N) NodeEmbedding
```

### 6.2 表结构（核心字段）

```sql
-- users
id (PK), username (UNIQUE), password_hash, preferred_locale, created_at

-- projects
id (PK), user_id (FK), name, description, created_at, updated_at

-- directories
id (PK), project_id (FK), parent_id (FK, nullable), name, description, order_index

-- notes
id (PK), directory_id (FK), title, content (TEXT, markdown), created_at, updated_at

-- teaching_sessions
id (PK), project_id (FK), title, status (active/archived), created_at, updated_at

-- messages
id (PK), session_id (FK), role (user/assistant/system), content, metadata (JSON), created_at

-- concepts
id (PK), session_id (FK), name, description, user_explanation, status (mastered/learning)

-- misconceptions
id (PK), session_id (FK), concept_name, user_claim, ai_correction, resolved

-- questions
id (PK), concept_id (FK, nullable), question_type (choice/fill/short/code),
        prompt, answer, explanation, difficulty (1-5), created_at

-- review_schedules
id (PK), user_id (FK), question_id (FK), next_review_at, interval_days, ease_factor

-- review_records
id (PK), schedule_id (FK), user_answer, is_correct, ai_feedback, reviewed_at

-- graphs
id (PK), project_id (FK, UNIQUE), created_at, updated_at

-- nodes
id (PK), graph_id (FK), concept_id (FK, nullable), label, description, 
        mastery_score (0-1, DEFAULT 0)

-- edges
id (PK), graph_id (FK), source_node_id (FK), target_node_id (FK), 
        relation (prerequisite/application/related), label, weight

-- node_embeddings（sqlite-vec 虚表）
node_id, embedding (BLOB, 1024 维 for deepseek-embed)
```

---

## 7. 项目结构

```
R6AX-Learn/                          # 项目根
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── uv.lock  或  requirements.txt
├── README.md
├── docs/
│   └── PRD.md                        # 本文档
│
├── app/                              # FastAPI 应用
│   ├── __init__.py
│   ├── main.py                       # 入口，挂载路由 + 中间件
│   ├── config.py                     # pydantic-settings 配置
│   │
│   ├── core/                         # 基础设施
│   │   ├── __init__.py
│   │   ├── security.py               # JWT / 密码哈希
│   │   ├── database.py               # SQLAlchemy 引擎 / session
│   │   └── deps.py                   # FastAPI Depends
│   │
│   ├── i18n/                         # 国际化
│   │   ├── __init__.py
│   │   ├── i18n.py                   # t() 函数
│   │   ├── middleware.py             # locale 探测
│   │   ├── locales/
│   │   │   ├── messages.pot
│   │   │   ├── zh_CN/LC_MESSAGES/messages.po
│   │   │   └── en_US/LC_MESSAGES/messages.mo
│   │   └── scripts/
│   │       ├── extract.sh            # pybabel extract
│   │       ├── update.sh             # pybabel update
│   │       └── compile.sh            # pybabel compile
│   │
│   ├── models/                       # SQLAlchemy 模型
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── project.py
│   │   ├── directory.py
│   │   ├── note.py
│   │   ├── teaching.py
│   │   ├── practice.py
│   │   └── integration.py
│   │
│   ├── schemas/                      # Pydantic schema
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── project.py
│   │   ├── note.py
│   │   ├── teaching.py
│   │   ├── practice.py
│   │   └── integration.py
│   │
│   ├── routers/                      # FastAPI 路由
│   │   ├── __init__.py
│   │   ├── pages.py                  # 页面路由（返回 HTML）
│   │   ├── auth.py                   # 登录 / 注册 API
│   │   ├── projects.py
│   │   ├── input_level.py            # Directory / Note
│   │   ├── teaching.py               # Teaching 会话 + SSE
│   │   ├── practice.py               # 做题 + 调度
│   │   └── integration.py
│   │
│   ├── services/                     # 业务逻辑
│   │   ├── __init__.py
│   │   ├── ai_service.py             # DeepSeek 封装
│   │   ├── teaching_agent.py         # LangGraph 状态机
│   │   ├── practice_agent.py         # 调度 + 判题
│   │   ├── concept_extractor.py      # 从 Note 提取概念
│   │   ├── misconception_detector.py # 检测错答
│   │   ├── question_generator.py     # 从 Concept 出题
│   │   └── embedding_service.py      # sqlite-vec 封装
│   │
│   ├── templates/                    # Jinja2 模板
│   │   ├── base.html                 # 基础布局
│   │   ├── auth/
│   │   │   ├── login.html
│   │   │   └── register.html
│   │   ├── pages/
│   │   │   ├── home.html
│   │   │   ├── project_list.html
│   │   │   └── project_detail.html
│   │   ├── input_level/
│   │   │   ├── note_editor.html
│   │   │   └── partials/
│   │   │       ├── directory_tree.html
│   │   │       └── note_list.html
│   │   ├── teaching/
│   │   │   ├── session.html
│   │   │   ├── concept_list.html
│   │   │   └── partials/
│   │   │       ├── message.html
│   │   │       ├── message_stream.html
│   │   │       └── concept_card.html
│   │   ├── practice/
│   │   │   ├── today.html            # 今日待复习
│   │   │   ├── question.html         # 做题
│   │   │   ├── result.html           # 结果
│   │   │   └── partials/
│   │   │       ├── question_card.html
│   │   │       └── answer_form.html
│   │   ├── integration/
│   │   │   ├── graph.html
│   │   │   └── partials/
│   │   │       ├── node.html
│   │   │       └── edge_form.html
│   │   └── components/               # 可复用 HTML 片段
│   │       ├── sidebar.html
│   │       ├── nav.html
│   │       └── modal.html
│   │
│   └── static/                       # 静态资源
│       ├── css/
│       │   └── app.css
│       ├── js/
│       │   ├── htmx.min.js
│       │   ├── alpine.min.js
│       │   └── app.js
│       └── img/
│
├── data/                             # 运行时数据（git ignore）
│   ├── r6ax.db
│   └── uploads/
│
└── tests/                            # pytest
    ├── conftest.py
    ├── test_auth.py
    ├── test_projects.py
    ├── test_i18n.py
    ├── test_input_level.py
    ├── test_teaching.py
    ├── test_practice.py
    └── test_integration.py
```

---

## 8. 关键交互流程

### 8.1 Teaching 会话（SSE 流式）

```
Browser                                  FastAPI                          DeepSeek
  │                                         │                                │
  │  POST /teaching/sessions                │                                │
  │  { note_id }                            │                                │
  │ ───────────────────────────────────────▶│                                │
  │                                         │ concept_extractor(note)        │
  │                                         │ ── 提取概念列表 ──▶             │
  │  201 { session_id, concepts[] }         │                                │
  │ ◀───────────────────────────────────────│                                │
  │                                         │                                │
  │  POST /teaching/sessions/{id}/messages  │                                │
  │  { content: "我来讲解..." }              │                                │
  │ ───────────────────────────────────────▶│                                │
  │                                         │ teaching_agent.stream()        │
  │                                         │ ── LangGraph 状态机 ──▶          │
  │  SSE: data: { type: "thinking" }        │                                │
  │ ◀───────────────────────────────────────│  DeepSeek stream ◀───          │
  │  SSE: data: { type: "text" }            │                                │
  │ ◀───────────────────────────────────────│                                │
  │  SSE: data: { type: "tool_call" }       │                                │
  │ ◀───────────────────────────────────────│                                │
  │  SSE: data: { type: "misconception" }   │                                │
  │ ◀───────────────────────────────────────│                                │
  │  SSE: data: { type: "concept" }         │                                │
  │ ◀───────────────────────────────────────│                                │
  │  SSE: data: { type: "done" }            │                                │
  │ ◀───────────────────────────────────────│                                │
```

### 8.2 Teaching → Integration + Practice 沉淀

```
1. 用户在 Teaching 会话结束页（partial: session_summary.html）
2. 看到 AI 标记的所有 Concept 列表（带勾选框）
3. 用户勾选要沉淀的 Concept
4. 点击"沉淀"按钮
5. HTMX POST /teaching/sessions/{id}/promote
   body: { concept_ids: [...] }
6. 后端：
   - 对每个 concept 调 question_generator 生成 1~3 道题 → 写入 Question 表
   - 对每个 concept 创建初始 ReviewSchedule（next_review_at = now + 1 day）
   - 对每个 concept 在 Graph 中创建 Node
   - 自动算 embedding 存 sqlite-vec
   - 自动建议 Prerequisite 边（基于其他节点的相似度）
7. 返回 partial: promoted_confirmation.html
8. HTMX 替换页面片段，显示"已沉淀 N 个节点，生成 M 道题"
```

### 8.3 Practice 做题闭环

```
1. 用户进 Practice 首页
2. HTMX GET /practice/today → 返回今日待复习题目列表
3. 用户点开一题 → /practice/question/{id}
4. 用户作答 → POST /practice/answer
5. 后端：
   - 客观题：规则判对错
   - 主观题：practice_agent 调 AI 判对错
   - 写 ReviewRecord
   - 更新 ReviewSchedule（答对拉长间隔，答错缩短）
   - 更新对应 Concept 节点的 MasteryScore
   - 错题累积到阈值 → 触发新一轮 Teaching（写一条提示消息）
6. 返回 result partial
7. HTMX 替换为下一题
```

### 8.4 LangGraph Teaching Agent 状态机

```
                 ┌──────────────┐
                 │   START      │
                 └──────┬───────┘
                        ↓
                 ┌──────────────┐
            ┌───▶│  RECEIVE     │◀──┐
            │    │  USER_INPUT  │   │
            │    └──────┬───────┘   │
            │           ↓           │
            │    ┌──────────────┐   │
            │    │  ANALYZE     │   │
            │    │  (LLM 判断)   │   │
            │    └──────┬───────┘   │
            │           │           │
            │     ┌─────┴─────┐     │
            │     │           │     │
            │   错          讲清楚   │
            │     ↓           ↓     │
            │  ┌──────┐  ┌────────┐│
            │  │MARK_ │  │MARK_  ││
            │  │MISC. │  │CONCEPT││
            │  └──┬───┘  └───┬────┘│
            │     │          │     │
            │     └────┬─────┘     │
            │          ↓           │
            │   ┌──────────────┐   │
            │   │  GENERATE    │───┘
            │   │  FOLLOWUP    │
            │   │  QUESTION    │
            │   └──────┬───────┘
            │          ↓
            │   ┌──────────────┐
            └──┤    END        │
                │  (会话关闭)   │
                └──────────────┘
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
  - 角色：概念 → AI 生成 1~3 道题

### 9.2 设计约束
- 每个 agent 的 prompt 文件独立放在 `app/services/prompts/`
- prompt 版本化（git 管理），方便 A/B 测试
- 关键决策：每个 agent 维护**示例 few-shot**（放 .py 或 .jsonl 文件）
- 输出格式：尽量让 LLM 返回**结构化 JSON**（便于后端解析）
- 失败兜底：JSON 解析失败时，fallback 到纯文本

### 9.3 调优节奏
- 阶段 3（Teaching）实现时，先用最简单的 prompt 跑通流程
- 阶段 5（打磨）再做 prompt 调优，引入 few-shot
- 不在 PRD 阶段卡 prompt——具体效果跑起来看

### 9.4 提示词管理
- 禁止在代码里硬编码大段 prompt
- 统一从 `app/services/prompts/{agent_name}.py` 导入
- prompt 文件顶部用注释说明：角色、输入输出格式、调优记录

---

## 10. 部署方案

### 10.1 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 系统依赖（sqlite-vec 需要）
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY pyproject.toml uv.lock* ./
RUN pip install --no-cache-dir hatchling \
    && pip install --no-cache-dir .

# 应用代码
COPY app/ ./app/

# i18n 编译（构建时跑一次）
RUN pybabel compile -d app/i18n/locales

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
version: '3.8'

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
# 编辑 .env 填入 DEEPSEEK_API_KEY 和 JWT_SECRET

# 2. 一键启动
docker compose up -d

# 3. 访问
open http://localhost:8000
```

---

## 11. 关键风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| LangGraph 学习曲线陡 | 中 | 中 | 早期先用普通函数 + LangChain 跑通，后期再迁 LangGraph |
| SSE 在反向代理下断连 | 中 | 中 | 配置 proxy 的 `proxy_buffering off` + 合理 timeout |
| sqlite-vec 编译失败 | 中 | 高 | 提供 `sqlite-vec` 的预编译 wheel；备选方案：纯 numpy 算余弦相似度 |
| DeepSeek 限流 | 中 | 中 | 客户端重试 + 队列；后期考虑本地小模型兜底 |
| Jinja2 模板复杂度膨胀 | 低 | 中 | 严格分 partials / components；定期重构 |
| HTMX 调试困难 | 中 | 低 | 用 htmx:configRequest / htmx:beforeSwap 日志 |
| AI 输出格式不稳定 | 高 | 高 | 严 prompt + 输出 JSON 校验 + 失败重试 + 降级到非结构化输出 |
| 翻译 key 散乱 | 中 | 中 | CI 检查：所有 .po 引用必须存在；缺失即构建失败 |
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
- [ ] 配 babel 工具链（extract.sh / update.sh / compile.sh）
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
- [ ] teaching_agent.py（先用普通函数实现状态机）
- [ ] prompts/teaching.py（首版）
- [ ] /teaching/sessions/{id}/messages SSE 端点
- [ ] 教学会话页面（HTMX 流式渲染）
- [ ] Concept / Misconception 标记的 UI

### 阶段 4：Practice Level 核心⭐
- [ ] Question / ReviewSchedule / ReviewRecord model
- [ ] practice_agent.py（判题 + 调度）
- [ ] question_generator.py（基于 Concept 出题）
- [ ] Practice 页面（今日待复习 + 做题 + 结果）
- [ ] 简单时间间隔调度
- [ ] 错题触发 Teaching 的提示机制

### 阶段 5：Integration Level
- [ ] Graph / Node / Edge / Mastery model
- [ ] Graph 查看页面
- [ ] 节点 + 边的 CRUD
- [ ] 概念 → 节点的"沉淀"流程（含自动出题）
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

1. ✅ 用户能注册登录，看到自己的项目列表
2. ✅ 用户能在 zh-CN / en-US 间切换语言
3. ✅ 用户能在项目下建目录、写笔记
4. ✅ 用户能从笔记提取概念，进入 Teaching 会话
5. ✅ AI 能流式回应用户的讲解，进行苏格拉底式追问
6. ✅ AI 能正确标记 Misconception（≥ 80% 准确）
7. ✅ 用户能把 Concept 沉淀到 Integration 图谱
8. ✅ 沉淀时自动生成 1~3 道复习题进入 Practice
9. ✅ 用户能在 Practice 中做题，AI 判主观题
10. ✅ Practice 错题能更新 MasteryScore，累积阈值触发 Teaching
11. ✅ 用户能在 Graph 上看到节点和边、掌握度
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
