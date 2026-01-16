"""AI 文章分析器"""

import json
import re
from typing import Optional
from openai import AsyncOpenAI
import structlog

from ..config import AIConfig
from ..storage.models import Article, AnalyzedArticle
from .prompts import SYSTEM_PROMPT, FILTER_PROMPT, TOP_SELECTION_PROMPT

logger = structlog.get_logger()


class ArticleAnalyzer:
    """文章 AI 分析器"""
    
    def __init__(self, config: AIConfig):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self.model = config.model
        self.max_tokens = config.max_tokens
        self.temperature = config.temperature
    
    async def analyze_batch(
        self, 
        articles: list[Article],
        top_pick_count: int = 5,
        batch_size: int = 20
    ) -> list[AnalyzedArticle]:
        """
        批量分析文章
        
        1. 分批评分和摘要
        2. 选出 TOP 精选文章
        """
        if not articles:
            return []
        
        logger.info("analyzing_articles", count=len(articles))
        
        # 分批处理
        all_analyzed = []
        for i in range(0, len(articles), batch_size):
            batch = articles[i:i + batch_size]
            analyzed = await self._analyze_batch(batch)
            all_analyzed.extend(analyzed)
            logger.info("batch_analyzed", 
                       batch=i // batch_size + 1,
                       count=len(analyzed))
        
        # 按分数排序
        all_analyzed.sort(key=lambda x: x.score, reverse=True)
        
        # 选出 TOP 精选
        if len(all_analyzed) > top_pick_count:
            top_indices = await self._select_top_picks(
                all_analyzed, 
                top_pick_count
            )
            for idx in top_indices:
                if 0 <= idx < len(all_analyzed):
                    all_analyzed[idx].is_top_pick = True
        else:
            # 文章太少，全部作为精选
            for article in all_analyzed:
                article.is_top_pick = True
        
        logger.info("analysis_complete",
                   total=len(all_analyzed),
                   top_picks=sum(1 for a in all_analyzed if a.is_top_pick))
        
        return all_analyzed
    
    async def _analyze_batch(self, articles: list[Article]) -> list[AnalyzedArticle]:
        """分析一批文章"""
        # 构建文章文本
        articles_text = self._format_articles_for_prompt(articles)
        
        prompt = FILTER_PROMPT.format(articles_text=articles_text)
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            
            content = response.choices[0].message.content
            result = self._parse_json_response(content)
            
            if not result or "articles" not in result:
                logger.warning("invalid_ai_response", content=content[:200])
                return self._fallback_analyze(articles)
            
            analyzed = []
            for item in result["articles"]:
                idx = item.get("index", 0)
                if 0 <= idx < len(articles):
                    article = articles[idx]
                    # 获取标签，如果没有则使用来源分类作为默认
                    tags = item.get("tags", [])
                    if not tags and article.category:
                        tags = [article.category]
                    
                    analyzed.append(AnalyzedArticle(
                        **article.model_dump(),
                        score=item.get("score", 5.0),
                        ai_summary=item.get("summary", ""),
                        reasoning=item.get("reasoning", ""),
                        tags=tags,
                    ))
            
            return analyzed
        
        except Exception as e:
            logger.error("ai_analysis_failed", error=str(e))
            return self._fallback_analyze(articles)
    
    async def _select_top_picks(
        self, 
        articles: list[AnalyzedArticle],
        count: int
    ) -> list[int]:
        """选出最值得阅读的文章"""
        # 只考虑评分 >= 5 的文章
        candidates = [a for a in articles if a.score >= 5]
        if len(candidates) <= count:
            return list(range(len(candidates)))
        
        # 构建候选文章文本
        articles_text = self._format_analyzed_for_selection(candidates[:30])  # 最多30篇候选
        
        prompt = TOP_SELECTION_PROMPT.format(
            count=count,
            articles_text=articles_text
        )
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=500,
                temperature=0.2,
            )
            
            content = response.choices[0].message.content
            result = self._parse_json_response(content)
            
            if result and "top_picks" in result:
                return result["top_picks"][:count]
        
        except Exception as e:
            logger.error("top_selection_failed", error=str(e))
        
        # 降级：直接取分数最高的
        return list(range(min(count, len(candidates))))
    
    def _format_articles_for_prompt(self, articles: list[Article]) -> str:
        """格式化文章用于 prompt"""
        lines = []
        for i, article in enumerate(articles):
            # 截取内容摘要
            content_preview = article.content[:500] if article.content else article.summary[:300]
            content_preview = content_preview.replace("\n", " ").strip()
            
            lines.append(f"""
[{i}] 标题: {article.title}
来源: {article.source} | 分类: {article.category}
内容摘要: {content_preview}...
""")
        
        return "\n".join(lines)
    
    def _format_analyzed_for_selection(self, articles: list[AnalyzedArticle]) -> str:
        """格式化已分析文章用于精选"""
        lines = []
        for i, article in enumerate(articles):
            lines.append(f"""
[{i}] 标题: {article.title}
来源: {article.source} | 评分: {article.score}
摘要: {article.ai_summary}
评语: {article.reasoning}
""")
        
        return "\n".join(lines)
    
    def _parse_json_response(self, content: str) -> Optional[dict]:
        """解析 AI 返回的 JSON"""
        try:
            # 尝试直接解析
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # 尝试提取 JSON 代码块
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # 尝试提取花括号内容
        brace_match = re.search(r'\{[\s\S]*\}', content)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass
        
        return None
    
    def _fallback_analyze(self, articles: list[Article]) -> list[AnalyzedArticle]:
        """降级分析（不使用 AI）"""
        analyzed = []
        for article in articles:
            # 简单评分逻辑
            score = 5.0
            if len(article.content) > 1000:
                score += 1
            if article.author:
                score += 0.5
            
            # 使用来源分类作为默认标签
            tags = [article.category] if article.category else ["未分类"]
            
            analyzed.append(AnalyzedArticle(
                **article.model_dump(),
                score=min(score, 10),
                ai_summary=article.summary[:100] if article.summary else article.title,
                reasoning="AI 分析不可用，使用基础规则评分",
                tags=tags,
            ))
        
        return analyzed
