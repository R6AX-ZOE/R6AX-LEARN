# 快速启动指南（Bootstrap）

本文档说明如何**最快**把 R6AX:/Learn 跑起来。

> 与 [install.md](install.md) 的关系：
> - `install.sh` / `install.bat` — 一次性安装环境（虚拟环境、依赖、.env、i18n）
> - `bootstrap.sh` — 每次启动前检查环境、缺失时自动补齐，然后直接拉起服务器
> - `bootstrap.md` — 本文档，聚焦"从零到启动"

---

## 1. 一键启动（Linux / macOS）

```bash
./bootstrap.sh
```

脚本自动完成：

1. 检查 `.env`，缺失时从 `.env.example` 生成并提示补填 `DEEPSEEK_API_KEY` / `JWT_SECRET`（`JWT_SECRET` 必填，无默认值）；
2. 检查虚拟环境 `.venv`，缺失时自动执行 `install.sh` 完成安装；
3. 尽力编译 i18n 翻译文件（失败不阻塞启动）；
4. 读取 `.env` 中的 `PORT`（默认 8000），启动服务器。

启动后访问 <http://localhost:8000>，首次使用请先创建账号：

```bash
python admin.py create_user <username> <password>
```

### 自定义端口 / 监听地址

```bash
PORT=9000 ./bootstrap.sh          # 指定端口
HOST=127.0.0.1 ./bootstrap.sh     # 仅本机访问
```

## 2. Windows 用户

bootstrap 脚本暂未提供 `.bat` 版本，请手动执行等价步骤：

```powershell
.\.venv\Scripts\activate          # 若未安装，先运行 .\install.bat
python compile_i18n.py
uvicorn app.main:app --reload --port 8000
```

## 3. Docker 方式（等价于一键启动）

```bash
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY / JWT_SECRET

docker compose up -d --build
```

## 4. 启动验证

| 检查项 | 方法 |
|--------|------|
| 服务已启动 | 浏览器打开 <http://localhost:8000> 应跳转到登录页 |
| 用户账号 | `python admin.py create_user <用户名> <密码>` 创建 |
| API 文档 | <http://localhost:8000/docs> |
| AI 功能正常 | 登录后任意页面试用一次"教 AI"会话 |
| 数据库初始化 | 首次启动自动建库并执行迁移（不再自动创建默认管理员） |

## 5. 常见问题

| 问题 | 处理 |
|------|------|
| `bootstrap.sh` 提示先配置 .env | 编辑 `.env` 后重新运行脚本 |
| 端口被占用 | 换端口：`PORT=9000 ./bootstrap.sh` |
| 需要后台运行 | `nohup ./bootstrap.sh > uvicorn.out.log 2>&1 &` |
| 重新安装依赖 | 删除 `.venv` 后重跑 `./install.sh` |