"""Feed Manager 单元测试

测试 src/feeds.py
"""

import pytest
import tempfile
import os
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from src.feeds import FeedManager
from src.config import FeedSource


class TestFeedManager:
    """FeedManager 测试"""
    
    def setup_method(self):
        """每个测试前创建临时配置目录"""
        self.temp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.temp_dir)
        
        # 创建初始的 feeds.yaml
        self.feeds_path = self.config_dir / "feeds.yaml"
        self._write_feeds([
            {"name": "测试源1", "url": "https://feed1.com/rss", "category": "科技", "enabled": True},
            {"name": "测试源2", "url": "https://feed2.com/rss", "category": "财经", "enabled": False},
        ])
        
        self.manager = FeedManager(config_dir=self.config_dir)
    
    def teardown_method(self):
        """每个测试后清理"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _write_feeds(self, feeds: list):
        """写入 feeds 配置"""
        with open(self.feeds_path, 'w', encoding='utf-8') as f:
            yaml.dump({"feeds": feeds}, f, allow_unicode=True)
    
    def _read_feeds(self) -> list:
        """读取 feeds 配置"""
        with open(self.feeds_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            return data.get("feeds", [])
    
    def test_list_feeds(self):
        """测试列出订阅源"""
        feeds = self.manager.list_feeds()
        
        assert len(feeds) == 2
        assert feeds[0].name == "测试源1"
        assert feeds[1].name == "测试源2"
    
    def test_list_feeds_returns_feed_source_objects(self):
        """测试返回 FeedSource 对象"""
        feeds = self.manager.list_feeds()
        
        assert all(isinstance(f, FeedSource) for f in feeds)
    
    def test_add_feed(self):
        """测试添加订阅源"""
        result = self.manager.add_feed(
            name="新订阅源",
            url="https://new-feed.com/rss",
            category="新分类"
        )
        
        assert result is True
        
        # 验证已保存
        feeds = self._read_feeds()
        assert len(feeds) == 3
        
        new_feed = next(f for f in feeds if f["name"] == "新订阅源")
        assert new_feed["url"] == "https://new-feed.com/rss"
        assert new_feed["category"] == "新分类"
    
    def test_add_feed_duplicate_url(self):
        """测试添加重复 URL"""
        result = self.manager.add_feed(
            name="重复源",
            url="https://feed1.com/rss",  # 已存在的 URL
            category="其他"
        )
        
        assert result is False
        
        # 数量不变
        feeds = self._read_feeds()
        assert len(feeds) == 2
    
    def test_add_feed_default_category(self):
        """测试默认分类"""
        self.manager.add_feed(
            name="无分类源",
            url="https://no-category.com/rss"
        )
        
        feeds = self._read_feeds()
        new_feed = next(f for f in feeds if f["name"] == "无分类源")
        assert new_feed["category"] == "未分类"
    
    def test_remove_feed_by_name(self):
        """测试按名称删除"""
        result = self.manager.remove_feed("测试源1")
        
        assert result is True
        
        feeds = self._read_feeds()
        assert len(feeds) == 1
        assert feeds[0]["name"] == "测试源2"
    
    def test_remove_feed_by_url(self):
        """测试按 URL 删除"""
        result = self.manager.remove_feed("https://feed2.com/rss")
        
        assert result is True
        
        feeds = self._read_feeds()
        assert len(feeds) == 1
        assert feeds[0]["name"] == "测试源1"
    
    def test_remove_nonexistent_feed(self):
        """测试删除不存在的订阅源"""
        result = self.manager.remove_feed("不存在的源")
        
        assert result is False
        
        # 数量不变
        feeds = self._read_feeds()
        assert len(feeds) == 2
    
    def test_toggle_feed_enable(self):
        """测试启用/禁用订阅源"""
        # 测试源2 初始是禁用的
        result = self.manager.toggle_feed("测试源2")
        
        assert result is True
        
        feeds = self._read_feeds()
        feed2 = next(f for f in feeds if f["name"] == "测试源2")
        assert feed2["enabled"] is True
    
    def test_toggle_feed_disable(self):
        """测试禁用已启用的订阅源"""
        # 测试源1 初始是启用的
        result = self.manager.toggle_feed("测试源1")
        
        assert result is True
        
        feeds = self._read_feeds()
        feed1 = next(f for f in feeds if f["name"] == "测试源1")
        assert feed1["enabled"] is False
    
    def test_toggle_nonexistent_feed(self):
        """测试切换不存在的订阅源"""
        result = self.manager.toggle_feed("不存在")
        
        assert result is False


class TestFeedManagerVerify:
    """FeedManager.verify_feed 测试"""
    
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.temp_dir)
        
        # 创建空的 feeds.yaml
        feeds_path = self.config_dir / "feeds.yaml"
        with open(feeds_path, 'w') as f:
            yaml.dump({"feeds": []}, f)
        
        self.manager = FeedManager(config_dir=self.config_dir)
    
    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_verify_feed_invalid_url(self):
        """测试验证无效 URL"""
        result = await self.manager.verify_feed("not-a-valid-url")
        
        assert result["valid"] is False
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_verify_feed_timeout(self):
        """测试验证超时（使用很短的超时时间）"""
        # 使用一个不太可能快速响应的地址
        result = await self.manager.verify_feed(
            "https://10.255.255.1/feed.xml",  # 不可路由的地址
            timeout=1
        )
        
        assert result["valid"] is False


class TestFeedSource:
    """FeedSource 模型测试（补充）"""
    
    def test_feed_source_from_dict(self):
        """测试从字典创建"""
        data = {
            "name": "Test Feed",
            "url": "https://example.com/rss",
            "category": "Tech",
            "enabled": True
        }
        
        feed = FeedSource(**data)
        
        assert feed.name == "Test Feed"
        assert feed.url == "https://example.com/rss"
        assert feed.category == "Tech"
        assert feed.enabled is True
    
    def test_feed_source_defaults(self):
        """测试默认值"""
        feed = FeedSource(name="Test", url="https://example.com")
        
        assert feed.category == "未分类"
        assert feed.enabled is True
