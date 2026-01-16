"""向量存储服务 (基于 ChromaDB)"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional
import structlog

logger = structlog.get_logger()

# ChromaDB 是可选依赖
CHROMADB_AVAILABLE = False
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    logger.warning("chromadb_not_installed", message="pip install chromadb to enable vector search")
except Exception as e:
    # 捕获其他错误（如 Pydantic 版本不兼容）
    logger.warning("chromadb_init_error", message=f"ChromaDB unavailable: {e}")


class VectorStore:
    """
    向量存储服务
    
    使用 ChromaDB 存储文章向量，支持：
    - 文章存储和检索
    - 相似度搜索
    - 历史文章查询
    """
    
    def __init__(self, persist_dir: str = "data/vector_store"):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        
        self._client = None
        self._collection = None
        
        if CHROMADB_AVAILABLE:
            self._init_chromadb()
        else:
            logger.warning("vector_store_disabled", reason="ChromaDB not installed")
    
    def _init_chromadb(self):
        """初始化 ChromaDB"""
        try:
            self._client = chromadb.PersistentClient(
                path=str(self.persist_dir),
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                )
            )
            
            # 创建或获取文章集合
            self._collection = self._client.get_or_create_collection(
                name="articles",
                metadata={"description": "News articles for RAG"}
            )
            
            logger.info(
                "vector_store_initialized",
                path=str(self.persist_dir),
                article_count=self._collection.count()
            )
        except Exception as e:
            logger.error("chromadb_init_failed", error=str(e))
            self._client = None
            self._collection = None
    
    @property
    def is_available(self) -> bool:
        """检查向量存储是否可用"""
        return self._collection is not None
    
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
            article_id: 文章唯一标识（通常是 URL 的哈希）
            title: 文章标题
            content: 文章内容
            metadata: 额外元数据
        """
        if not self.is_available:
            return
        
        try:
            # 组合标题和内容作为文档
            document = f"{title}\n\n{content[:2000]}"  # 限制长度
            
            # 准备元数据
            meta = {
                "title": title,
                "added_at": datetime.now().isoformat(),
            }
            if metadata:
                meta.update(metadata)
            
            # 添加到集合
            self._collection.upsert(
                ids=[article_id],
                documents=[document],
                metadatas=[meta],
            )
            
            logger.debug("article_added_to_vector_store", article_id=article_id)
            
        except Exception as e:
            logger.warning("add_article_failed", error=str(e))
    
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
            filter_metadata: 元数据过滤条件
            
        Returns:
            相似文章列表，每个包含 id, title, content, score, metadata
        """
        if not self.is_available:
            return []
        
        try:
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
            
        except Exception as e:
            logger.warning("vector_search_failed", error=str(e))
            return []
    
    async def get_recent_articles(self, limit: int = 20) -> list[dict]:
        """获取最近添加的文章"""
        if not self.is_available:
            return []
        
        try:
            # ChromaDB 不直接支持按时间排序，获取所有并在内存排序
            results = self._collection.get(
                limit=limit * 2,  # 获取更多以便排序
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
            
            # 按添加时间排序
            articles.sort(key=lambda x: x.get("added_at", ""), reverse=True)
            
            return articles[:limit]
            
        except Exception as e:
            logger.warning("get_recent_articles_failed", error=str(e))
            return []
    
    def get_stats(self) -> dict:
        """获取存储统计信息"""
        if not self.is_available:
            return {"available": False}
        
        return {
            "available": True,
            "article_count": self._collection.count(),
            "persist_dir": str(self.persist_dir),
        }
    
    async def clear(self):
        """清空向量存储"""
        if not self.is_available:
            return
        
        try:
            self._client.delete_collection("articles")
            self._collection = self._client.create_collection(
                name="articles",
                metadata={"description": "News articles for RAG"}
            )
            logger.info("vector_store_cleared")
        except Exception as e:
            logger.error("clear_vector_store_failed", error=str(e))
