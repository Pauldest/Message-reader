"""SQLite 向量存储 - 基于 SQLite 的简单向量搜索实现"""

import json
import sqlite3
import math
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional
import structlog

logger = structlog.get_logger()


class SQLiteVectorStore:
    """
    基于 SQLite 的向量存储
    
    使用简单的 TF-IDF 风格特征 + 余弦相似度实现文章检索
    适合中小规模数据（几千篇文章）
    """
    
    def __init__(self, db_path: str = "data/vector_store.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    content TEXT,
                    embedding TEXT,
                    metadata TEXT,
                    added_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_added_at ON articles(added_at)
            """)
            conn.commit()
        
        count = self._get_count()
        logger.info("sqlite_vector_store_initialized", path=str(self.db_path), article_count=count)
    
    @property
    def is_available(self) -> bool:
        """检查是否可用"""
        return self.db_path.exists()
    
    async def add_article(
        self,
        article_id: str,
        title: str,
        content: str,
        metadata: Optional[dict] = None,
    ):
        """
        添加文章到向量存储
        
        Args:
            article_id: 文章唯一标识
            title: 文章标题
            content: 文章内容
            metadata: 额外元数据
        """
        # 生成嵌入向量
        text = f"{title} {content[:2000]}"
        embedding = self._compute_embedding(text)
        
        # 准备元数据
        meta = {
            "title": title,
            **(metadata or {})
        }
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO articles (id, title, content, embedding, metadata, added_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                article_id,
                title,
                content[:2000],
                json.dumps(embedding),
                json.dumps(meta, ensure_ascii=False),
                datetime.now().isoformat(),
            ))
            conn.commit()
        
        logger.debug("article_added_to_sqlite_store", article_id=article_id)
    
    async def search(
        self,
        query: str,
        top_k: int = 5,
        filter_metadata: Optional[dict] = None,
    ) -> list[dict]:
        """
        搜索相似文章
        
        Args:
            query: 搜索查询
            top_k: 返回结果数量
            filter_metadata: 元数据过滤条件（暂不支持）
            
        Returns:
            相似文章列表
        """
        # 计算查询向量
        query_embedding = self._compute_embedding(query)
        
        # 获取所有文章并计算相似度
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT id, title, content, embedding, metadata FROM articles
                ORDER BY added_at DESC
                LIMIT 100
            """)
            rows = cursor.fetchall()
        
        if not rows:
            return []
        
        # 计算相似度并排序
        results = []
        for row in rows:
            article_id, title, content, embedding_json, metadata_json = row
            try:
                embedding = json.loads(embedding_json)
                similarity = self._cosine_similarity(query_embedding, embedding)
                results.append({
                    "id": article_id,
                    "title": title,
                    "content": content,
                    "score": similarity,
                    "metadata": json.loads(metadata_json) if metadata_json else {},
                })
            except (json.JSONDecodeError, TypeError):
                continue
        
        # 按相似度排序
        results.sort(key=lambda x: x["score"], reverse=True)
        
        return results[:top_k]
    
    async def get_recent_articles(self, limit: int = 20) -> list[dict]:
        """获取最近添加的文章"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT id, title, content, metadata, added_at FROM articles
                ORDER BY added_at DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
        
        return [
            {
                "id": row[0],
                "title": row[1],
                "content": row[2],
                "metadata": json.loads(row[3]) if row[3] else {},
                "added_at": row[4],
            }
            for row in rows
        ]
    
    def get_stats(self) -> dict:
        """获取存储统计信息"""
        return {
            "available": True,
            "type": "sqlite",
            "article_count": self._get_count(),
            "db_path": str(self.db_path),
        }
    
    async def clear(self):
        """清空存储"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM articles")
            conn.commit()
        logger.info("sqlite_vector_store_cleared")
    
    def _get_count(self) -> int:
        """获取文章数量"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM articles")
            return cursor.fetchone()[0]
    
    def _compute_embedding(self, text: str, dim: int = 256) -> list[float]:
        """
        计算文本的嵌入向量
        
        使用基于字符 n-gram 的哈希技巧生成稀疏向量
        这是一种简单但有效的特征提取方法
        """
        if not text:
            return [0.0] * dim
        
        # 分词（简单的空格分割 + 字符 n-gram）
        words = text.lower().split()
        features = []
        
        # 词级别特征
        for word in words[:200]:
            features.append(word)
        
        # 字符 2-gram 和 3-gram
        text_lower = text.lower()[:500]
        for i in range(len(text_lower) - 1):
            features.append(text_lower[i:i+2])
        for i in range(len(text_lower) - 2):
            features.append(text_lower[i:i+3])
        
        # 哈希到固定维度
        vector = [0.0] * dim
        for feature in features:
            hash_val = int(hashlib.md5(feature.encode()).hexdigest(), 16)
            idx = hash_val % dim
            # 使用另一个哈希决定符号（+1 或 -1）
            sign = 1 if (hash_val // dim) % 2 == 0 else -1
            vector[idx] += sign * 1.0
        
        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        
        return vector
    
    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """计算余弦相似度"""
        if len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        # 由于向量已归一化，直接返回点积
        return dot_product


# 为了兼容性，创建一个统一的 VectorStore 类
class VectorStore:
    """
    向量存储统一接口
    
    自动选择可用的后端：
    1. ChromaDB（如果可用）
    2. SQLite（作为后备）
    """
    
    def __init__(self, persist_dir: str = "data/vector_store"):
        self._backend = None
        self._backend_name = None
        
        # 尝试使用 ChromaDB
        try:
            import chromadb
            from chromadb.config import Settings
            
            persist_path = Path(persist_dir)
            persist_path.mkdir(parents=True, exist_ok=True)
            
            self._client = chromadb.PersistentClient(
                path=str(persist_path),
                settings=Settings(anonymized_telemetry=False)
            )
            self._collection = self._client.get_or_create_collection(
                name="articles",
                metadata={"description": "News articles for RAG"}
            )
            self._backend = "chromadb"
            self._backend_name = "ChromaDB"
            
            logger.info(
                "vector_store_initialized",
                backend="chromadb",
                path=str(persist_path),
                article_count=self._collection.count()
            )
        except Exception as e:
            logger.warning("chromadb_unavailable", error=str(e))
            
            # 回退到 SQLite
            db_path = str(persist_dir).rstrip("/") + ".db"
            self._sqlite_store = SQLiteVectorStore(db_path)
            self._backend = "sqlite"
            self._backend_name = "SQLite"
            
            logger.info(
                "vector_store_initialized",
                backend="sqlite",
                path=db_path
            )
    
    @property
    def is_available(self) -> bool:
        """检查是否可用"""
        return self._backend is not None
    
    async def add_article(
        self,
        article_id: str,
        title: str,
        content: str,
        metadata: Optional[dict] = None,
    ):
        """添加文章"""
        if self._backend == "chromadb":
            document = f"{title}\n\n{content[:2000]}"
            meta = {"title": title, "added_at": datetime.now().isoformat()}
            if metadata:
                meta.update(metadata)
            self._collection.upsert(
                ids=[article_id],
                documents=[document],
                metadatas=[meta],
            )
        elif self._backend == "sqlite":
            await self._sqlite_store.add_article(article_id, title, content, metadata)
    
    async def search(
        self,
        query: str,
        top_k: int = 5,
        filter_metadata: Optional[dict] = None,
    ) -> list[dict]:
        """搜索相似文章"""
        if self._backend == "chromadb":
            results = self._collection.query(
                query_texts=[query],
                n_results=top_k,
                where=filter_metadata,
            )
            
            articles = []
            if results and results["ids"] and results["ids"][0]:
                for i, article_id in enumerate(results["ids"][0]):
                    articles.append({
                        "id": article_id,
                        "title": results["metadatas"][0][i].get("title", ""),
                        "content": results["documents"][0][i] if results["documents"] else "",
                        "score": 1.0 - results["distances"][0][i] if results["distances"] else 0.0,
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    })
            return articles
        
        elif self._backend == "sqlite":
            return await self._sqlite_store.search(query, top_k, filter_metadata)
        
        return []
    
    async def get_recent_articles(self, limit: int = 20) -> list[dict]:
        """获取最近添加的文章"""
        if self._backend == "chromadb":
            results = self._collection.get(
                limit=limit,
                include=["metadatas", "documents"],
            )
            if not results or not results["ids"]:
                return []
            
            articles = []
            for i, article_id in enumerate(results["ids"]):
                meta = results["metadatas"][i] if results["metadatas"] else {}
                articles.append({
                    "id": article_id,
                    "title": meta.get("title", ""),
                    "content": results["documents"][i] if results["documents"] else "",
                    "added_at": meta.get("added_at", ""),
                    "metadata": meta,
                })
            return articles
        
        elif self._backend == "sqlite":
            return await self._sqlite_store.get_recent_articles(limit)
        
        return []
    
    def get_stats(self) -> dict:
        """获取存储统计信息"""
        if self._backend == "chromadb":
            return {
                "available": True,
                "type": "chromadb",
                "article_count": self._collection.count(),
            }
        elif self._backend == "sqlite":
            return self._sqlite_store.get_stats()
        
        return {"available": False}
    
    async def clear(self):
        """清空存储"""
        if self._backend == "chromadb":
            self._client.delete_collection("articles")
            self._collection = self._client.create_collection(
                name="articles",
                metadata={"description": "News articles for RAG"}
            )
        elif self._backend == "sqlite":
            await self._sqlite_store.clear()
