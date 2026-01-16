"""数据库测试"""

import pytest
import tempfile
import os
from datetime import datetime
from pathlib import Path

from src.storage.database import Database
from src.storage.models import Article, AnalyzedArticle


class TestDatabase:
    """数据库测试"""
    
    def setup_method(self):
        # 使用临时文件
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = Database(self.db_path)
    
    def teardown_method(self):
        # 清理临时文件
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        os.rmdir(self.temp_dir)
    
    def test_init_creates_tables(self):
        """测试初始化创建表"""
        # 数据库应该已经初始化
        assert os.path.exists(self.db_path)
    
    def test_article_exists_false(self):
        """测试不存在的文章"""
        exists = self.db.article_exists("https://nonexistent.com/article")
        assert exists is False
    
    def test_save_and_check_article(self):
        """测试保存和检查文章"""
        article = Article(
            url="https://example.com/test",
            title="测试文章",
            content="内容",
            source="测试来源"
        )
        
        # 保存
        article_id = self.db.save_article(article)
        assert article_id > 0
        
        # 检查存在
        exists = self.db.article_exists("https://example.com/test")
        assert exists is True
    
    def test_save_analyzed_article(self):
        """测试保存分析后的文章"""
        article = AnalyzedArticle(
            url="https://example.com/analyzed",
            title="分析文章",
            content="内容",
            source="来源",
            score=8.5,
            ai_summary="AI 摘要",
            is_top_pick=True,
            reasoning="推荐理由"
        )
        
        article_id = self.db.save_analyzed_article(article)
        assert article_id > 0
    
    def test_get_unsent_articles(self):
        """测试获取未发送文章"""
        # 保存一篇已分析的文章
        article = AnalyzedArticle(
            url="https://example.com/unsent",
            title="未发送文章",
            content="内容",
            source="来源",
            score=7.5,
            ai_summary="摘要"
        )
        self.db.save_analyzed_article(article)
        
        # 获取未发送文章
        unsent = self.db.get_unsent_articles()
        assert len(unsent) == 1
        assert unsent[0].url == "https://example.com/unsent"
    
    def test_mark_articles_sent(self):
        """测试标记文章已发送"""
        # 保存文章
        article = AnalyzedArticle(
            url="https://example.com/to-send",
            title="待发送",
            content="内容",
            source="来源",
            score=6.0,
            ai_summary="摘要"
        )
        self.db.save_analyzed_article(article)
        
        # 标记已发送
        self.db.mark_articles_sent(["https://example.com/to-send"])
        
        # 应该不再出现在未发送列表
        unsent = self.db.get_unsent_articles()
        assert len(unsent) == 0
    
    def test_get_stats(self):
        """测试获取统计信息"""
        stats = self.db.get_stats()
        
        assert "total" in stats
        assert "analyzed" in stats
        assert "sent" in stats
