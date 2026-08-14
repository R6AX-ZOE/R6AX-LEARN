FROM python:3.11-slim

WORKDIR /app

# 注意：原 PRD 在此安装 gcc/g++/make/libsqlite3-dev 用于编译扩展；
# 受限网络下 deb.debian.org 无法访问（http/https 均被拒），且本项目所有依赖
# 均提供 CPython 3.11 的预编译 wheel（torch 已单独装 CPU 版），故跳过 apt。

# Python 依赖
COPY pyproject.toml .
# 预装 CPU 版 torch：PyPI 默认 x86_64 Linux 为 CUDA 构建（~2.5GB），受限网络不可行
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir hatchling \
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
