# 安装指南

本文档覆盖 **R6AX:/Learn** 的三种安装方式：

1. [Docker Compose（推荐）](#docker-compose)
2. [Linux / macOS 本地安装](#linux--macos-本地安装)
3. [Windows 本地安装（Python 源码）](#windows-本地安装python-源码)

> 通用前置条件：**Python 3.11+**（本地安装时）与可访问的 **DeepSeek API Key**。

---

## 前置准备

### 1. 获取 DeepSeek API Key

1. 前往 [DeepSeek 开放平台](https://platform.deepseek.com) 注册并创建 API Key。
2. 记下 Key 值，形如 `sk-xxxxxxxxxxxxxxxx`。

### 2. 获取代码

```bash
git clone <仓库地址> r6ax-learn
cd r6ax-learn
```

### 3. 准备环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少配置：

```dotenv
DEEPSEEK_API_KEY=sk-your-deepseek-api-key-here
JWT_SECRET=some-long-random-secret
```

> `JWT_SECRET` 用于签发登录令牌，请务必改成一个「足够长的随机字符串」。
> 生产环境请设置 `DEBUG=false`。

---

## Docker Compose

### 1. 安装 Docker

- 参考 [Docker 官方文档](https://docs.docker.com/get-docker/) 安装 Docker Engine + Compose 插件。

### 2. 构建并启动

```bash
docker compose up -d --build
```

首次构建会：
- 安装 Python 依赖；
- **预下载 embedding 模型**（`all-MiniLM-L6-v2`，约 90 MB，仅首次）；
- 编译 i18n 翻译文件。

### 3. 验证

```bash
docker compose ps          # 状态应为 running
docker compose logs -f     # 查看日志
```

打开 <http://localhost:8000>，使用默认账号 **admin / admin** 登录。

### 4. 常用命令

```bash
docker compose up -d       # 后台启动
docker compose restart     # 重启
docker compose down        # 停止（保留数据）
docker compose down -v     # 停止并删除数据卷（慎用）
```

### 5. 持久化说明

- 数据库与其他运行数据存放在 `./data/` 目录（已挂载到容器 `/app/data`），删除容器不会丢失。
- `.env` 以只读方式挂载，修改后需 `docker compose restart` 生效。

---

## Linux / macOS 本地安装

### 1. 检查 Python

```bash
python3 --version   # 需要 3.11+
```

### 2. 一键安装

```bash
./install.sh
```

脚本会自动：
- 创建虚拟环境 `.venv`；
- 安装依赖（含 dev / 测试依赖）；
- 生成 `.env`（若不存在，从 `.env.example` 复制）；
- 编译 i18n 翻译文件。

### 3. 手动安装（不选一键脚本时）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"

# 准备环境变量
cp .env.example .env        # 若尚未创建
# 编辑 .env 填入 DEEPSEEK_API_KEY / JWT_SECRET

# 编译翻译文件（若 .po 有更新）
python compile_i18n.py

# 启动开发服务器
uvicorn app.main:app --reload --port 8000
```

### 4. 访问

打开 <http://localhost:8000>，默认账号 **admin / admin**。

---

## Windows 本地安装

### 1. 检查 Python

在 PowerShell / CMD 中：

```powershell
python --version   # 需要 3.11+
```

### 2. 一键安装

```powershell
.\install.bat
```

### 3. 手动安装（不选一键脚本时）

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

copy .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY / JWT_SECRET

python compile_i18n.py

uvicorn app.main:app --reload --port 8000
```

### 4. 启动

打开 <http://localhost:8000>，默认账号 **admin / admin**。

---

## 常见问题（FAQ）

| 问题 | 解决方案 |
|------|----------|
| 登录后 AI 无回复 | 检查 `.env` 中的 `DEEPSEEK_API_KEY` 是否正确；查看启动时的日志输出 |
| 页面显示乱码 | 应用已强制 UTF-8；确认终端编码为 UTF-8 |
| 默认端口被占用 | 修改 `.env` 中的 `PORT`，并以 `uvicorn app.main:app --port <端口>` 启动 |

---

## 测试

```bash
# Linux / macOS
source .venv/bin/activate && pytest tests/ -v

# Windows
.\.venv\Scripts\activate && pytest tests/ -v
```