"""AI 分析器测试"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.ai.analyzer import ArticleAnalyzer
from src.storage.models import Article, AnalyzedArticle
from src.config import AIConfig


class TestArticleAnalyzer:
    """AI 分析器测试"""
    
    def setup_method(self):
        self.config = AIConfig(
            api_key="test_key",
            model="test-model",
            base_url="https://api.test.com/v1"
        )
    
    def test_format_articles_for_prompt(self):
        """测试文章格式化"""
        analyzer = ArticleAnalyzer(self.config)
        
        articles = [
            Article(
                url="https://example.com/1",
                title="测试文章1",
                content="这是测试内容",
                source="测试来源",
                category="测试"
            )
        ]
        
        formatted = analyzer._format_articles_for_prompt(articles)
        
        assert "[0]" in formatted
        assert "测试文章1" in formatted
        assert "测试来源" in formatted
    
    def test_parse_json_response_direct(self):
        """测试直接 JSON 解析"""
        analyzer = ArticleAnalyzer(self.config)
        
        response = '{"articles": [{"index": 0, "score": 8.5, "summary": "测试摘要"}]}'
        result = analyzer._parse_json_response(response)
        
        assert result is not None
        assert "articles" in result
        assert result["articles"][0]["score"] == 8.5
    
    def test_parse_json_response_with_markdown(self):
        """测试 Markdown 代码块中的 JSON"""
        analyzer = ArticleAnalyzer(self.config)
        
        response = '''这是一些文字
```json
{"articles": [{"index": 0, "score": 7.0, "summary": "测试"}]}
```
更多文字'''
        
        result = analyzer._parse_json_response(response)
        
        assert result is not None
        assert result["articles"][0]["score"] == 7.0
    
    def test_fallback_analyze(self):
        """测试降级分析"""
        analyzer = ArticleAnalyzer(self.config)
        
        articles = [
            Article(
                url="https://example.com/1",
                title="短内容文章",
                content="短",
                source="来源"
            ),
            Article(
                url="https://example.com/2",
                title="长内容文章",
                content="很长的内容" * 200,  # 超过 1000 字符
                source="来源",
                author="作者"
            )
        ]
        
        analyzed = analyzer._fallback_analyze(articles)
        
        assert len(analyzed) == 2
        # 长内容 + 有作者应该得分更高
        assert analyzed[1].score > analyzed[0].score


class TestArticleModels:
    """文章模型测试"""
    
    def test_article_hash_and_equality(self):
        """测试文章哈希和相等性"""
        a1 = Article(url="https://example.com/1", title="Title 1")
        a2 = Article(url="https://example.com/1", title="Different Title")
        a3 = Article(url="https://example.com/2", title="Title 1")
        
        # 相同 URL 应该相等
        assert a1 == a2
        assert hash(a1) == hash(a2)
        
        # 不同 URL 不相等
        assert a1 != a3
    
    def test_analyzed_article_inheritance(self):
        """测试分析文章继承"""
        article = AnalyzedArticle(
            url="https://example.com/1",
            title="测试",
            score=8.5,
            ai_summary="AI 摘要",
            is_top_pick=True
        )
        
        assert article.score == 8.5
        assert article.is_top_pick is True
        assert article.url == "https://example.com/1"
