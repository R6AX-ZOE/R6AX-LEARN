"""
容器构建/本地预下载 embedding 模型，避免运行时下载。

网络无法访问 huggingface.co 时（如受限网络/国内网络）：
- 自动回退到镜像 hf-mirror.com 重试；
- 也可通过环境变量 HF_ENDPOINT 手动指定镜像源（此时不再自动切换）。

用法:
    python scripts/download_embedding_model.py
    HF_ENDPOINT=https://hf-mirror.com python scripts/download_embedding_model.py
"""

import os
import sys
from pathlib import Path

# 模型配置
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_DIR = Path("models/embedding")
MIRROR_ENDPOINT = "https://hf-mirror.com"


def _load_and_save(endpoint):
    """设置镜像端点后导入/下载模型并保存到本地（必须在导入 sentence_transformers 前设置端点）。"""
    if endpoint:
        os.environ["HF_ENDPOINT"] = endpoint
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME)
    model.save(str(MODEL_DIR))
    return model


def download_model():
    """下载并保存 embedding 模型到本地；失败时给出可操作的修复指引。"""
    print(f"Downloading embedding model: {MODEL_NAME}")

    # 创建目录
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # 用户显式指定了端点则只用它；否则先试官方源，失败后自动改用镜像
    if os.environ.get("HF_ENDPOINT"):
        attempts = [os.environ["HF_ENDPOINT"]]
    else:
        attempts = [None, MIRROR_ENDPOINT]

    last_error = None
    for idx, endpoint in enumerate(attempts, start=1):
        if endpoint:
            print(f"[download] attempt {idx}: using HF endpoint {endpoint}")
        try:
            _load_and_save(endpoint)
            size_mb = sum(f.stat().st_size for f in MODEL_DIR.rglob('*') if f.is_file()) / 1024 / 1024
            print(f"Model saved to: {MODEL_DIR}")
            print(f"Model size: {size_mb:.2f} MB")
            return
        except Exception as e:
            last_error = e
            print(f"[download] attempt {idx} failed: {e}", file=sys.stderr)

    sys.exit(
        "\n[error] 下载 embedding 模型失败：无法连接 Hugging Face（"
        + f"{os.environ.get('HF_ENDPOINT', 'https://huggingface.co')}）。\n"
        "可能原因：当前网络无法访问 Hugging Face 官方源。\n"
        "解决方法（任选其一）：\n"
        "  1. 指定镜像源后重试：\n"
        "     Windows:  set HF_ENDPOINT=https://hf-mirror.com\n"
        "     Linux/macOS: export HF_ENDPOINT=https://hf-mirror.com\n"
        "     Docker:   docker compose build --build-arg ... 或构建环境中 export 后重试\n"
        "  2. 在可联网的机器上运行本脚本，把生成的 models/embedding 目录拷贝到本项目；\n"
        "  3. 不下载模型也可运行：应用会自动降级为离线词法向量（检索效果略差）。\n"
        f"原始错误：{last_error}"
    )


if __name__ == "__main__":
    download_model()
