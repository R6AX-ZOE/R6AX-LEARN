FROM python:3.11-slim

WORKDIR /app

RUN apt-get update
RUN apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir hatchling \
    && pip install --no-cache-dir .

# 预下载embedding模型（避免运行时下载）
COPY scripts/download_embedding_model.py ./scripts/
RUN python scripts/download_embedding_model.py && rm -rf ~/.cache/huggingface

# Application code
COPY app/ ./app/
COPY scripts/ ./scripts/

# i18n: extract/update done during dev; compile at build time
RUN pybabel compile -d app/i18n/locales 2>/dev/null || true

# Data directory
RUN mkdir -p /app/data
VOLUME /app/data

# Environment
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
