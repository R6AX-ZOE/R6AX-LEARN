FROM python:3.11-slim

WORKDIR /app

# 注意：原 PRD 在此安装 gcc/g++/make/libsqlite3-dev 用于编译扩展；
# 受限网络下 deb.debian.org 无法访问（http/https 均被拒），且本项目所有依赖
# 均提供 CPython 3.11 的预编译 wheel，故跳过 apt。

# Python 依赖（向量检索为纯 Python 词法降级，无需 torch）
COPY pyproject.toml .
RUN pip install --no-cache-dir hatchling \
    && pip install --no-cache-dir .

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
