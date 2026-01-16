"""正文提取模块"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
import aiohttp
import trafilatura
import structlog

from ..storage.models import Article

logger = structlog.get_logger()


class ContentExtractor:
    """文章正文提取器"""
    
    def __init__(self, timeout: int = 15, max_concurrent: int = 5):
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
    
    async def extract_all(self, articles: list[Article]) -> list[Article]:
        """批量提取文章正文"""
        logger.info("extracting_content", count=len(articles))
        
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as session:
            tasks = [
                self._extract_article(session, article)
                for article in articles
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        extracted = []
        for article, result in zip(articles, results):
            if isinstance(result, Exception):
                logger.warning("extraction_failed",
                             url=article.url,
                             error=str(result))
                # 如果提取失败，使用原有的摘要内容
                extracted.append(article)
            else:
                extracted.append(result)
        
        logger.info("extraction_complete", count=len(extracted))
        return extracted
    
    async def _extract_article(self, session: aiohttp.ClientSession,
                               article: Article) -> Article:
        """提取单篇文章正文"""
        async with self._semaphore:
            # 如果已经有足够的内容，跳过提取
            if len(article.content) > 500:
                return article
            
            try:
                async with session.get(article.url) as response:
                    if response.status != 200:
                        return article
                    
                    html = await response.text()
                    
                    # 使用 trafilatura 提取正文（在线程池中运行）
                    loop = asyncio.get_event_loop()
                    content = await loop.run_in_executor(
                        self._executor,
                        self._extract_text,
                        html
                    )
                    
                    if content:
                        article.content = content
                    
                    return article
            
            except asyncio.TimeoutError:
                logger.debug("extraction_timeout", url=article.url)
                return article
            except Exception as e:
                logger.debug("extraction_error", url=article.url, error=str(e))
                return article
    
    def _extract_text(self, html: str) -> Optional[str]:
        """使用 trafilatura 提取正文"""
        try:
            text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=True,
                no_fallback=False,
            )
            return text
        except Exception:
            return None
    
    def close(self):
        """关闭资源"""
        self._executor.shutdown(wait=False)
