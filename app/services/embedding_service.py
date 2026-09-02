"""
本地Embedding服务 - 可选 sentence-transformers 语义向量；默认纯 Python 词法向量
存储友好：不再强制依赖 numpy / sentence-transformers / torch（~950MB）。
语义模式为可选增强：需另行安装 sentence-transformers 并预下载模型后才会启用，
否则一律使用确定性词法向量（哈希 n-gram），检索与挂载仍可用（语义效果略弱）。
"""

import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

# 使用轻量级模型（可选：安装 sentence-transformers 后预下载启用）
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_DIR = Path("models/embedding")
EMBED_DIM = 384  # all-MiniLM-L6-v2 的维度

class EmbeddingService:
    """本地embedding生成和检索服务（词法向量为内置降级，语义模型为可选）"""

    _model = None
    _model_loaded = False

    def __init__(self):
        # 懒加载模型（避免启动时加载）
        pass

    def _load_model(self):
        """可选语义模型：仅当 sentence-transformers 已安装且模型目录非空时加载。
        否则纯 Python 词法向量（无需 numpy）。"""
        if self._model_loaded:
            return

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            print("sentence-transformers not installed; using built-in lexical "
                  "fallback vectors (install it to enable semantic search)")
            self._model = None
            self._model_loaded = True
            return

        if not MODEL_DIR.exists() or not any(MODEL_DIR.iterdir()):
            print(f"Embedding model not found at {MODEL_DIR}; using built-in lexical "
                  f"fallback vectors (run scripts/download_embedding_model.py to enable "
                  f"semantic search)")
            self._model = None
            self._model_loaded = True
            return

        try:
            self._model = SentenceTransformer(str(MODEL_DIR))
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
                return _fallback_embedding(text)

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
        """基于向量相似度搜索（纯 Python 余弦相似度，无 numpy）"""

        if not candidate_embeddings:
            return []

        q_norm = _vec_norm(query_embedding)
        scored = []
        for idx, vec in enumerate(candidate_embeddings):
            if len(vec) != len(query_embedding):
                continue
            n = _vec_norm(vec)
            denom = n * q_norm
            if denom == 0:
                continue
            dot = sum(a * b for a, b in zip(vec, query_embedding))
            scored.append((dot / denom, idx))

        scored.sort(key=lambda x: -x[0])
        return [
            {
                "index": idx,
                "score": float(score)
            }
            for score, idx in scored[:top_k]
        ]

    def search_virtual_graphs(
        self,
        db_path: str,
        query: str,
        project_id: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """搜索相似虚拟图（sqlite3 读取 embedding + 余弦相似度）"""

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
                except Exception:
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


def _vec_norm(vec: List[float]) -> float:
    """L2 范数（纯 Python）"""
    return math.sqrt(sum(v * v for v in vec))


def _fallback_embedding(text: str) -> List[float]:
    """无本地模型时的确定性降级向量：英文词 + 中文单字/双字 n-gram 哈希。

    相同文本永远得到相同向量（随机向量会导致每次检索结果都不同），
    词法相似度检索仍可正常工作，仅语义效果弱于正式模型。
    纯 Python 实现，无 numpy 依赖。
    """
    tokens = re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]", (text or "").lower())
    counts = [0.0] * EMBED_DIM
    for t in tokens:
        if t.isascii():
            grams = [t]
        else:
            grams = []
            for n in (1, 2):
                if len(t) >= n:
                    grams.extend(t[i:i + n] for i in range(len(t) - n + 1))
        for g in grams:
            h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
            counts[h % EMBED_DIM] += 1.0 if (h >> 8) & 1 else -1.0
    norm = math.sqrt(sum(c * c for c in counts))
    if norm:
        return [c / norm for c in counts]
    return [0.0] * EMBED_DIM


# 全局实例（避免重复加载模型）
embedding_service = EmbeddingService()

def get_embedding_service() -> EmbeddingService:
    """获取embedding服务实例"""
    return embedding_service
