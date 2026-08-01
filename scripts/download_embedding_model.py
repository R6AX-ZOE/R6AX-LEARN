"""
容器构建时预下载embedding模型，避免运行时下载
"""

from pathlib import Path
from sentence_transformers import SentenceTransformer

# 模型配置
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_DIR = Path("models/embedding")

def download_model():
    """下载并保存embedding模型到本地"""

    print(f"Downloading embedding model: {MODEL_NAME}")

    # 创建目录
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # 下载模型
    model = SentenceTransformer(MODEL_NAME)

    # 保存到本地
    model.save(str(MODEL_DIR))

    print(f"Model saved to: {MODEL_DIR}")
    print(f"Model size: {sum(f.stat().st_size for f in MODEL_DIR.rglob('*') if f.is_file()) / 1024 / 1024:.2f} MB")

if __name__ == "__main__":
    download_model()