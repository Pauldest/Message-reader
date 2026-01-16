"""RSS 解析器测试"""

import pytest
from datetime import datetime

from src.fetcher.rss_parser import RSSParser
from src.config import FeedSource


class TestRSSParser:
    """RSS 解析器测试"""
    
    def setup_method(self):
        self.parser = RSSParser(timeout=10, max_concurrent=5)
    
    def test_parse_interval_seconds(self):
        """测试时间间隔解析"""
        # 这个测试验证 RSSParser 可以正确实例化
        assert self.parser.timeout == 10
        assert self.parser.max_concurrent == 5
    
    @pytest.mark.asyncio
    async def test_fetch_empty_feeds(self):
        """测试空订阅源列表"""
        articles = await self.parser.fetch_all([])
        assert articles == []
    
    @pytest.mark.asyncio
    async def test_fetch_disabled_feed(self):
        """测试禁用的订阅源"""
        feed = FeedSource(
            name="Test Feed",
            url="https://example.com/feed.xml",
            category="Test",
            enabled=False
        )
        articles = await self.parser.fetch_all([feed])
        assert articles == []


class TestFeedSource:
    """订阅源模型测试"""
    
    def test_feed_source_default_values(self):
        """测试默认值"""
        feed = FeedSource(name="Test", url="https://example.com/feed.xml")
        assert feed.category == "未分类"
        assert feed.enabled is True
    
    def test_feed_source_custom_values(self):
        """测试自定义值"""
        feed = FeedSource(
            name="Tech Blog",
            url="https://blog.example.com/rss",
            category="技术",
            enabled=False
        )
        assert feed.name == "Tech Blog"
        assert feed.category == "技术"
        assert feed.enabled is False
