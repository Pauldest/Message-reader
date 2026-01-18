"""RSS 解析模块"""

import asyncio
from datetime import datetime
from typing import Optional
import aiohttp
import feedparser
from dateutil import parser as date_parser
import structlog

from ..config import FeedSource
from ..storage.models import Article

logger = structlog.get_logger()


class RSSParser:
    """RSS 解析器"""
    
    def __init__(self, timeout: int = 30, max_concurrent: int = 10):
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
    
    async def fetch_all(self, feeds: list[FeedSource]) -> list[Article]:
        """并发抓取所有订阅源"""
        enabled_feeds = [f for f in feeds if f.enabled]
        
        logger.info("fetching_feeds", count=len(enabled_feeds))
        
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as session:
            tasks = [
                self._fetch_feed(session, feed)
                for feed in enabled_feeds
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        articles = []
        for feed, result in zip(enabled_feeds, results):
            if isinstance(result, Exception):
                logger.error("feed_fetch_failed", 
                           feed=feed.name, 
                           error=str(result))
            else:
                articles.extend(result)
                logger.info("feed_fetched", 
                          feed=feed.name, 
                          count=len(result))
        
        # 去重
        unique_articles = list({a.url: a for a in articles}.values())
        
        logger.info("fetch_complete", 
                   total=len(unique_articles),
                   sources=len(enabled_feeds))
        
        return unique_articles
    
    async def _fetch_feed(self, session: aiohttp.ClientSession, 
                          feed: FeedSource) -> list[Article]:
        """抓取单个订阅源"""
        async with self._semaphore:
            try:
                async with session.get(feed.url) as response:
                    if response.status != 200:
                        logger.warning("feed_http_error",
                                      feed=feed.name,
                                      status=response.status)
                        return []
                    
                    content = await response.text()
                    return self._parse_feed(content, feed)
            
            except asyncio.TimeoutError:
                logger.warning("feed_timeout", feed=feed.name)
                return []
            except Exception as e:
                logger.error("feed_error", feed=feed.name, error=str(e))
                return []
    
    def _parse_feed(self, content: str, feed: FeedSource) -> list[Article]:
        """解析 RSS/Atom 内容"""
        from datetime import timedelta
        
        parsed = feedparser.parse(content)
        articles = []
        
        # 限制只抓取最近 6 个月的文章
        # Ensure cutoff_date is timezone-aware (UTC)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=180)
        
        for entry in parsed.entries:
            try:
                article = self._entry_to_article(entry, feed)
                if article:
                    # 过滤掉超过 6 个月的文章
                    # Both times should now be aware
                    if article.published_at and article.published_at < cutoff_date:
                        continue
                    articles.append(article)
            except Exception as e:
                logger.warning("entry_parse_error",
                             feed=feed.name,
                             error=str(e))
        
        return articles
    
    def _entry_to_article(self, entry, feed: FeedSource) -> Optional[Article]:
        """将 RSS entry 转换为 Article"""
        # 获取 URL
        url = entry.get("link", "")
        if not url:
            return None
        
        # 获取标题
        title = entry.get("title", "").strip()
        if not title:
            return None
        
        # 获取摘要/内容
        summary = ""
        if hasattr(entry, "summary"):
            summary = entry.summary
        elif hasattr(entry, "description"):
            summary = entry.description
        
        # 获取完整内容（如果有）
        content = ""
        if hasattr(entry, "content"):
            content = entry.content[0].get("value", "")
        
        # 获取发布时间
        published_at = None
        for date_field in ["published", "updated", "created"]:
            if hasattr(entry, date_field):
                try:
                    date_str = getattr(entry, date_field)
                    dt = date_parser.parse(date_str)
                    
                    # Normalize to UTC
                    if dt.tzinfo is None:
                        # If naive, assume UTC (standard for RSS) or Local? 
                        # Assuming UTC is safer for standardization, or use local machine time
                        dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = dt.astimezone(timezone.utc)
                        
                    published_at = dt
                    break
                except:
                    pass
        
        # 获取作者
        author = ""
        if hasattr(entry, "author"):
            author = entry.author
        elif hasattr(entry, "author_detail"):
            author = entry.author_detail.get("name", "")
        
        return Article(
            url=url,
            title=title,
            content=content or summary,
            summary=summary,
            source=feed.name,
            category=feed.category,
            author=author,
            published_at=published_at,
            fetched_at=datetime.now(timezone.utc),
        )
