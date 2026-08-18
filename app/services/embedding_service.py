"""
本地Embedding服务 - 使用sentence-transformers生成向量
容器友好：模型预下载，无需运行时下载

网络不可达 huggingface.co 时：
- 运行时下载自动改用镜像 hf-mirror.com（可通过 HF_ENDPOINT 覆盖）；
- 镜像也不可用时降级为确定性词法向量（哈希 n-gram），检索仍可用。
"""

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

# 使用轻量级模型（容器构建时预下载）
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_DIR = Path("models/embedding")
MIRROR_ENDPOINT = "https://hf-mirror.com"
EMBED_DIM = 384  # all-MiniLM-L6-v2 的维度

class EmbeddingService:
    """本地embedding生成和检索服务"""

    _model = None
    _model_loaded = False

    def __init__(self):
        # 懒加载模型（避免启动时加载）
        pass

    def _load_model(self):
        """加载本地模型（容器友好）"""
        if self._model_loaded:
            return

        try:
            # 本地无模型且未指定端点时，默认走镜像下载（网络不可达官方源时也能装）
            if not MODEL_DIR.exists() and not os.environ.get("HF_ENDPOINT"):
                os.environ["HF_ENDPOINT"] = MIRROR_ENDPOINT
                print(f"Embedding model not found locally; downloading via {MIRROR_ENDPOINT} ...")

            from sentence_transformers import SentenceTransformer

            # 优先使用预下载的模型目录
            if MODEL_DIR.exists():
                self._model = SentenceTransformer(str(MODEL_DIR))
            else:
                # 容器构建时会预下载，这里只是fallback
                self._model = SentenceTransformer(MODEL_NAME)
                # 保存到本地避免下次下载
                self._model.save(str(MODEL_DIR))

            self._model_loaded = True
            print(f"Embedding model loaded: {MODEL_NAME}")

        except Exception as e:
            print(f"Error loading embedding model: {e}")
            # Fallback: 使用确定性词法向量（哈希 n-gram），检索仍可用
            self._model = None
            self._model_loaded = True

    def generate_embedding(self, text: str) -> List[float]:
        """生成文本的embedding向量"""
        self._load_model()

        if self._model:
            try:
                embedding = self._model.encode(text, convert_to_numpy=True)
                return embedding.tolist()
            except Exception as e:
                print(f"Error generating embedding: {e}")
                # Fallback: 确定性词法向量
                return _fallback_embedding(text)

        # Fallback: 确定性词法向量
        return _fallback_embedding(text)

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """批量生成embedding（更高效）"""
        self._load_model()

        if self._model:
            try:
                embeddings = self._model.encode(texts, convert_to_numpy=True)
                return [emb.tolist() for emb in embeddings]
            except Exception as e:
                print(f"Error in batch embedding: {e}")
                return [_fallback_embedding(t) for t in texts]

        return [_fallback_embedding(t) for t in texts]

    def search_similar(
        self,
        query_embedding: List[float],
        candidate_embeddings: List[List[float]],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """基于向量相似度搜索（使用余弦相似度）"""

        if not candidate_embeddings:
            return []

        query_vec = np.array(query_embedding)
        candidate_vecs = np.array(candidate_embeddings)

        # 计算余弦相似度
        similarities = np.dot(candidate_vecs, query_vec) / (
            np.linalg.norm(candidate_vecs, axis=1) * np.linalg.norm(query_vec)
        )

        # 排序并返回top-k
        top_indices = np.argsort(similarities)[-top_k:][::-1]

        return [
            {
                "index": int(idx),
                "score": float(similarities[idx])
            }
            for idx in top_indices
        ]

    def search_virtual_graphs(
        self,
        db_path: str,
        query: str,
        project_id: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """搜索相似虚拟图（sqlite3 读取 embedding + NumPy 余弦相似度）"""

        # 生成query embedding
        query_embedding = self.generate_embedding(query)

        # 连接数据库
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        try:
            # 查询所有虚拟图的embedding
            cursor.execute("""
                SELECT vge.virtual_graph_id, vge.embedding, vg.name, vg.description
                FROM virtual_graph_embeddings vge
                JOIN virtual_graphs vg ON vge.virtual_graph_id = vg.id
                JOIN teaching_sessions ts ON vg.session_id = ts.id
                WHERE ts.project_id = ?
            """, (project_id,))

            rows = cursor.fetchall()

            if not rows:
                return []

            # 解析embedding并计算相似度
            candidates = []
            for row in rows:
                vg_id, embedding_json, name, description = row
                try:
                    embedding = json.loads(embedding_json)
                    candidates.append({
                        "id": vg_id,
                        "name": name,
                        "description": description,
                        "embedding": embedding
                    })
                except:
                    continue

            # 执行相似度搜索
            candidate_embeddings = [c["embedding"] for c in candidates]
            results = self.search_similar(query_embedding, candidate_embeddings, top_k)

            # 组合结果
            search_results = []
            for result in results:
                idx = result["index"]
                candidate = candidates[idx]
                search_results.append({
                    "id": candidate["id"],
                    "name": candidate["name"],
                    "description": candidate["description"],
                    "score": result["score"]
                })

            return search_results

        finally:
            conn.close()

def _fallback_embedding(text: str) -> List[float]:
    """无本地模型时的确定性降级向量：英文词 + 中文单字/双字 n-gram 哈希。

    相同文本永远得到相同向量（随机向量会导致每次检索结果都不同），
    词法相似度检索仍可正常工作，仅语义效果弱于正式模型。
    """
    tokens = re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]", (text or "").lower())
    grams = []
    for t in tokens:
        if t.isascii():
            grams.append(t)
        else:
            for n in (1, 2):
                if len(t) >= n:
                    grams.extend(t[i:i + n] for i in range(len(t) - n + 1))
    vec = np.zeros(EMBED_DIM)
    for g in grams:
        h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
        vec[h % EMBED_DIM] += 1 if (h >> 8) & 1 else -1
    norm = np.linalg.norm(vec)
    if norm:
        vec /= norm
    return vec.tolist()


# 全局实例（避免重复加载模型）
embedding_service = EmbeddingService()

def get_embedding_service() -> EmbeddingService:
    """获取embedding服务实例"""
    return embedding_service