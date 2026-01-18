"""Vector Store 单元测试

测试 src/storage/vector_store.py
"""

import pytest
import tempfile
import os
import math
from pathlib import Path

from src.storage.vector_store import SQLiteVectorStore, VectorStore


class TestSQLiteVectorStore:
    """SQLiteVectorStore 测试"""
    
    def setup_method(self):
        """每个测试前创建临时数据库"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_vector.db")
        self.store = SQLiteVectorStore(self.db_path)
    
    def teardown_method(self):
        """每个测试后清理临时文件"""
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self.temp_dir)
    
    def test_init_creates_database(self):
        """测试初始化创建数据库文件"""
        assert os.path.exists(self.db_path)
    
    def test_is_available(self):
        """测试可用性检查 - is_available 是属性"""
        assert self.store.is_available is True
    
    @pytest.mark.asyncio
    async def test_add_article(self):
        """测试添加文章"""
        await self.store.add_article(
            article_id="article-1",
            title="测试文章标题",
            content="这是测试文章的内容，包含一些关键词用于测试相似度搜索。"
        )
        
        # get_stats 是同步方法
        stats = self.store.get_stats()
        assert stats["article_count"] == 1
    
    @pytest.mark.asyncio
    async def test_add_article_with_metadata(self):
        """测试带元数据添加文章"""
        await self.store.add_article(
            article_id="article-2",
            title="带元数据的文章",
            content="内容",
            metadata={"source": "test", "category": "tech"}
        )
        
        stats = self.store.get_stats()
        assert stats["article_count"] == 1
    
    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        """测试搜索返回结果"""
        # 添加测试文章
        await self.store.add_article(
            article_id="ai-article",
            title="人工智能最新进展",
            content="OpenAI 发布了新版本的 GPT 模型，性能大幅提升。"
        )
        await self.store.add_article(
            article_id="finance-article",
            title="股市行情分析",
            content="今日A股市场震荡，科技板块领涨。"
        )
        
        # 搜索 AI 相关内容
        results = await self.store.search("GPT 人工智能模型", top_k=5)
        
        assert len(results) > 0
        # 检查结果包含 id 字段
        assert "id" in results[0]
    
    @pytest.mark.asyncio
    async def test_search_empty_database(self):
        """测试空数据库搜索"""
        results = await self.store.search("任意查询", top_k=5)
        assert results == []
    
    @pytest.mark.asyncio
    async def test_get_recent_articles(self):
        """测试获取最近文章"""
        # 添加多篇文章
        for i in range(5):
            await self.store.add_article(
                article_id=f"article-{i}",
                title=f"文章 {i}",
                content=f"内容 {i}"
            )
        
        recent = await self.store.get_recent_articles(limit=3)
        assert len(recent) == 3
    
    def test_get_stats(self):
        """测试获取统计信息 - 同步方法"""
        stats = self.store.get_stats()
        
        assert "article_count" in stats
        assert stats["article_count"] == 0
        assert stats["type"] == "sqlite"
    
    @pytest.mark.asyncio
    async def test_clear(self):
        """测试清空存储"""
        # 添加一些数据
        await self.store.add_article("id-1", "Title", "Content")
        assert self.store.get_stats()["article_count"] == 1
        
        # 清空
        await self.store.clear()
        assert self.store.get_stats()["article_count"] == 0
    
    def test_compute_embedding(self):
        """测试嵌入向量计算"""
        text = "测试文本用于生成嵌入向量"
        embedding = self.store._compute_embedding(text, dim=256)
        
        assert len(embedding) == 256
        # 验证是单位向量（归一化）
        norm = math.sqrt(sum(x * x for x in embedding))
        assert abs(norm - 1.0) < 0.001
    
    def test_compute_embedding_empty_text(self):
        """测试空文本嵌入"""
        embedding = self.store._compute_embedding("", dim=256)
        assert len(embedding) == 256
    
    def test_cosine_similarity(self):
        """测试余弦相似度计算"""
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [1.0, 0.0, 0.0]
        vec3 = [0.0, 1.0, 0.0]
        
        # 相同向量相似度为 1
        assert self.store._cosine_similarity(vec1, vec2) == 1.0
        
        # 正交向量相似度为 0
        assert self.store._cosine_similarity(vec1, vec3) == 0.0
    
    def test_cosine_similarity_zero_vector(self):
        """测试零向量的余弦相似度"""
        vec1 = [1.0, 2.0, 3.0]
        zero = [0.0, 0.0, 0.0]
        
        # 含零向量时返回 0
        assert self.store._cosine_similarity(vec1, zero) == 0.0


class TestVectorStore:
    """VectorStore 统一接口测试"""
    
    def setup_method(self):
        """每个测试前创建临时目录"""
        self.temp_dir = tempfile.mkdtemp()
        self.store = VectorStore(self.temp_dir)
    
    def teardown_method(self):
        """每个测试后清理"""
        # 清理可能创建的文件
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_is_available(self):
        """测试可用性 - is_available 是属性"""
        assert self.store.is_available is True
    
    @pytest.mark.asyncio
    async def test_add_and_search(self):
        """测试添加和搜索"""
        await self.store.add_article(
            article_id="test-1",
            title="Python 编程教程",
            content="学习 Python 编程语言的基础知识"
        )
        
        results = await self.store.search("Python 编程", top_k=3)
        assert len(results) > 0
    
    def test_get_stats(self):
        """测试统计信息 - 同步方法"""
        stats = self.store.get_stats()
        assert "article_count" in stats or "available" in stats
    
    @pytest.mark.asyncio
    async def test_clear(self):
        """测试清空"""
        await self.store.add_article("id", "Title", "Content")
        await self.store.clear()
        
        results = await self.store.search("Title", top_k=1)
        assert len(results) == 0
