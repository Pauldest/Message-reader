"""嵌入向量服务"""

import time
from typing import Optional
from openai import AsyncOpenAI
import structlog

from ..config import AIConfig

logger = structlog.get_logger()

# 延迟导入避免循环依赖
_telemetry = None

def _get_telemetry():
    """延迟获取遥测服务"""
    global _telemetry
    if _telemetry is None:
        try:
            from .telemetry import get_telemetry
            _telemetry = get_telemetry()
        except:
            _telemetry = None
    return _telemetry


class EmbeddingService:
    """
    文本嵌入服务
    
    用于将文本转换为向量，支持 RAG 检索
    """
    
    def __init__(self, config: AIConfig):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        # DeepSeek 目前不支持 embeddings，使用简单的 TF-IDF 替代
        # 未来可以切换到支持 embeddings 的服务
        self._use_simple_embedding = True
        self._embedding_model = "text-embedding-3-small"
    
    async def embed_text(self, text: str) -> list[float]:
        """
        将文本转换为向量
        
        Args:
            text: 输入文本
            
        Returns:
            向量列表
        """
        start_time = time.time()
        
        if self._use_simple_embedding:
            result = self._simple_hash_embedding(text)
            # 记录遥测
            telemetry = _get_telemetry()
            if telemetry:
                duration_ms = int((time.time() - start_time) * 1000)
                telemetry.record_embedding(
                    model="simple_hash",
                    input_text=text,
                    dimensions=len(result),
                    duration_ms=duration_ms,
                    caller="EmbeddingService.embed_text",
                )
            return result
        
        try:
            response = await self.client.embeddings.create(
                model=self._embedding_model,
                input=text,
            )
            embedding = response.data[0].embedding
            
            # 记录遥测
            telemetry = _get_telemetry()
            if telemetry:
                duration_ms = int((time.time() - start_time) * 1000)
                telemetry.record_embedding(
                    model=self._embedding_model,
                    input_text=text,
                    dimensions=len(embedding),
                    duration_ms=duration_ms,
                    caller="EmbeddingService.embed_text",
                )
            
            return embedding
        except Exception as e:
            logger.warning("embedding_failed", error=str(e))
            # 记录失败的遥测
            telemetry = _get_telemetry()
            if telemetry:
                duration_ms = int((time.time() - start_time) * 1000)
                telemetry.record_embedding(
                    model=self._embedding_model,
                    input_text=text,
                    dimensions=0,
                    duration_ms=duration_ms,
                    error=str(e),
                    caller="EmbeddingService.embed_text",
                )
            return self._simple_hash_embedding(text)
    
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入"""
        return [await self.embed_text(text) for text in texts]
    
    def _simple_hash_embedding(self, text: str, dim: int = 384) -> list[float]:
        """
        简单的哈希嵌入（用于原型开发）
        
        基于字符 n-gram 的简单向量化
        """
        import hashlib
        import math
        
        # 生成 n-grams
        ngrams = []
        words = text.lower().split()
        for word in words[:100]:  # 限制处理的词数
            for i in range(len(word) - 2):
                ngrams.append(word[i:i+3])
        
        # 哈希到固定维度
        vector = [0.0] * dim
        for ngram in ngrams:
            hash_val = int(hashlib.md5(ngram.encode()).hexdigest(), 16)
            idx = hash_val % dim
            vector[idx] += 1.0
        
        # 归一化
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        
        return vector
    
    @staticmethod
    def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
        """计算余弦相似度"""
        import math
        
        if len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
