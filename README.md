# R6AX:/Learn

基于"教中学（Learning by Teaching）"理念的 AI 辅助学习平台。用户通过向 AI 讲解知识来复习巩固，AI 扮演"聪明的学生"与"苏格拉底式提问者"，通过追问、质疑、要求举例，把模糊的知识磨成清晰、能讲出来的知识。

> 中文文档

## 四层学习闭环

```
教 AI（短期强化理解）
  → 沉淀到图谱（结构化）
    → 做练习（间隔重复抗遗忘）
      → 触发新一轮教 AI（巩固薄弱点）
```

- **Input**：原始笔记（Markdown + KaTeX）
- **Teaching**：主动向 AI 讲解，AI 流式追问、标记概念与误区
- **Practice**：AI 自动出题，间隔重复调度，错题自动触发再教
- **Integration**：知识图谱可视化节点关联与掌握度（MasteryScore）

## 技术栈

| 维度 | 选型 |
|------|------|
| 后端 | FastAPI + Uvicorn（Python 3.11+） |
| 前端 | Jinja2 + Tailwind CSS + HTMX + Alpine.js + KaTeX |
| 数据库 | SQLite + SQLAlchemy 2.0 (async)，向量相似度检索（NumPy 余弦相似度） |
| AI | DeepSeek API（OpenAI 兼容 SDK） |
| i18n | Babel（zh-CN / en-US） |

## 快速开始

### Docker（推荐）

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY 与 JWT_SECRET

docker compose up -d
# 访问 http://localhost:8000
```

### 本地开发

最快的启动方式（Linux/macOS）：

```bash
./bootstrap.sh          # 未安装时自动走 install.sh，然后直接启动
```

亦可分步进行（Windows 用户见 [install.md](docs/install.md)）：

```bash
# 安装（Windows 运行 install.bat，Linux/macOS 运行 install.sh）
./install.sh          # 或 install.bat

# 启动
./bootstrap.sh        # 或 uvicorn app.main:app --reload --port 8000
```

> `install` 负责安装环境，`bootstrap` 负责快速启动，详见 [install.md](docs/install.md) 与 [bootstrap.md](docs/bootstrap.md)。

## 配置

复制 `.env.example` 为 `.env` 并配置：

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥（必填，AI 功能依赖） |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址，默认 `https://api.deepseek.com` |
| `JWT_SECRET` | JWT 签发密钥（必填，无默认值；须为 ≥32 字符随机串，否则服务拒绝启动） |
| `PORT` | 服务端口，默认 8000 |
| `DEBUG` | 是否开启调试模式 |

首次启动不会再自动创建默认管理员。请用管理员工具手动创建：

```bash
python scripts/admin.py create_user <username> <password>
python scripts/admin.py list_users
python scripts/admin.py delete_user <username>
```

> 安全说明：登录 cookie 启用 `HttpOnly` + `SameSite=Lax`；`DEBUG=false`（生产）时自动启用 `Secure`。所有需要登录的状态变更请求（POST/PUT/PATCH/DELETE）由双提交 CSRF cookie 防护。

## 功能预览

- 用户认证（JWT）与项目管理
- Markdown + KaTeX 笔记编辑、目录树
- 笔记概念提取 → Teaching 会话（SSE 流式）
- AI 苏格拉底式追问、概念 / 误区标记
- 概念沉淀至知识图谱 + 自动生成复习题
- 间隔重复做题、主观题 AI 判分
- 错题累积触发新一轮 Teaching 闭环
- 图谱可视化（Cytoscape.js + dagre）、掌握度进度条

## 项目结构

```
app/
├── main.py            # FastAPI 入口
├── config.py          # 配置（pydantic-settings）
├── core/              # 数据库 / JWT / 依赖注入
├── models/            # SQLAlchemy 模型
├── schemas/           # Pydantic 模型
├── routers/           # 路由（pages/auth/projects/input/teaching/practice/integration）
├── services/          # AI 与业务逻辑（teaching_agent / question_generator / ...）
├── i18n/              # Babel 多语言（zh_CN / en_US）
├── templates/         # Jinja2 模板
└── static/            # 静态资源
data/                  # 运行时数据（SQLite，git-ignored）
docs/                  # 文档（安装指南 / 快速启动 / 功能规范）
scripts/               # 工具脚本（admin 用户管理 / 数据迁移 / 清理 / i18n 编译）
```

## 工具脚本

```bash
python scripts/admin.py create_user <username> <password>   # 创建用户
python scripts/admin.py list_users                          # 列出用户
python scripts/admin.py delete_user <username>              # 删除用户
python scripts/compile_i18n.py                              # 编译翻译文件
python scripts/cleanup_graphs.py                            # 清空图谱数据
python scripts/cleanup_teaching.py                          # 清空教学数据
python scripts/migrate_multi_graph.py                       # 多图谱迁移
python scripts/migrate_graphs_for_dirs.py                   # 为目录创建图谱
```

> 测试为本地冒烟脚本（不入库），运行方式：`pytest tests/ -v`。

## 文档

- [安装指南 install.md](docs/install.md)
- [快速启动 bootstrap.md](docs/bootstrap.md)

## License

见仓库 LICENSE 文件。