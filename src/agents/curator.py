"""Curator Agent - 智能文章筛选器"""

import time
from typing import Any
import structlog

from .base import BaseAgent
from ..models.article import EnrichedArticle
from ..models.agent import AgentContext, AgentOutput
from ..services.llm import LLMService

logger = structlog.get_logger()


CURATOR_SYSTEM_PROMPT = """你是一位资深新闻编辑，负责从今日分析过的文章中筛选出最值得推荐的内容。

你的职责：
1. 评估每篇文章的价值和重要性
2. 决定哪些是"精选"（必读），哪些是"速览"（值得一看），哪些不推送
3. 确保推送的内容多样、有价值、不重复

筛选标准：
- **精选文章**：重大突破/事件、深度洞察、影响广泛、信息稀缺
- **速览文章**：有趣但非必读、补充性信息、特定领域读者关注
- **不推送**：低价值、重复内容、标题党、过时信息

你需要根据当天文章的整体质量灵活决定数量：
- 如果今天有很多高质量文章，可以多推荐
- 如果质量一般，宁缺毋滥
- 精选通常 3-10 篇，速览 10-30 篇"""

CURATOR_SELECTION_PROMPT = """请从以下 {total_count} 篇已分析的文章中，选出值得推送的内容：

【待筛选文章列表】
{articles_summary}

【筛选要求】
1. 选出"精选"文章（必读，值得深入阅读）
2. 选出"速览"文章（值得一看，快速浏览）
3. 剩余文章不推送

【今日特别关注】
- 是否有重大突发新闻？
- 是否有多篇报道同一事件？（去重）
- 是否有特别值得关注的趋势？

请按以下 JSON 格式返回：
```json
{{
  "top_picks": [
    {{"url": "文章URL", "reason": "推荐理由"}}
  ],
  "quick_reads": [
    {{"url": "文章URL", "reason": "推荐理由"}}
  ],
  "excluded": [
    {{"url": "文章URL", "reason": "排除原因"}}
  ],
  "daily_summary": "今日新闻一句话总结",
  "selection_reasoning": "整体筛选思路说明"
}}
```

注意：
- top_picks 通常 3-10 篇，质量优先
- quick_reads 通常 10-30 篇
- 如果文章质量普遍不高，宁少勿滥
- 同一事件的多篇报道只保留最有价值的一篇"""


class CuratorAgent(BaseAgent):
    """
    策展人 Agent
    
    职责：
    1. 从已分析的文章中智能筛选
    2. 决定精选和速览文章
    3. 去除重复和低价值内容
    4. 生成每日摘要
    """
    
    AGENT_NAME = "Curator"
    SYSTEM_PROMPT = CURATOR_SYSTEM_PROMPT
    
    async def curate(
        self, 
        articles: list[EnrichedArticle],
        max_articles: int = 50,
    ) -> dict:
        """
        智能筛选文章
        
        Args:
            articles: 已分析的文章列表
            max_articles: 最大推送数量（硬上限）
            
        Returns:
            {
                "top_picks": [EnrichedArticle, ...],
                "quick_reads": [EnrichedArticle, ...],
                "excluded": [EnrichedArticle, ...],
                "daily_summary": str,
            }
        """
        start_time = time.time()
        self.log_start(f"{len(articles)} articles")
        
        if not articles:
            return {
                "top_picks": [],
                "quick_reads": [],
                "excluded": [],
                "daily_summary": "今日暂无新文章",
            }
        
        # 如果文章太少，直接用评分排序
        if len(articles) <= 10:
            return self._simple_selection(articles)
        
        # 构建文章摘要供 AI 筛选
        articles_summary = self._format_articles_for_selection(articles)
        
        # 构建 prompt
        user_prompt = CURATOR_SELECTION_PROMPT.format(
            total_count=len(articles),
            articles_summary=articles_summary,
        )
        
        # 调用 LLM
        result, token_usage = await self.invoke_llm(
            user_prompt=user_prompt,
            max_tokens=3000,
            temperature=0.3,
            json_mode=True,
        )
        
        duration = time.time() - start_time
        
        if result:
            selection = self._parse_selection(result, articles, max_articles)
        else:
            selection = self._simple_selection(articles)
        
        self.log_complete(
            duration, 
            f"Top: {len(selection['top_picks'])}, Quick: {len(selection['quick_reads'])}"
        )
        
        return selection
    
    def _format_articles_for_selection(self, articles: list[EnrichedArticle]) -> str:
        """格式化文章列表供 AI 筛选"""
        lines = []
        for i, a in enumerate(articles[:50], 1):  # 限制数量
            score_info = f"评分:{a.overall_score:.1f}"
            source_info = f"来源:{a.source}" if a.source else ""
            tags_info = f"标签:{','.join(a.tags[:3])}" if a.tags else ""
            summary = a.ai_summary[:80] if a.ai_summary else a.what[:80] if a.what else ""
            
            lines.append(
                f"{i}. [{score_info}] {a.title}\n"
                f"   {source_info} {tags_info}\n"
                f"   摘要: {summary}\n"
                f"   URL: {a.url}"
            )
        
        return "\n\n".join(lines)
    
    def _parse_selection(
        self, 
        result: dict, 
        articles: list[EnrichedArticle],
        max_articles: int,
    ) -> dict:
        """解析 AI 筛选结果"""
        # 创建 URL -> Article 映射
        url_to_article = {a.url: a for a in articles}
        
        top_picks = []
        quick_reads = []
        selected_urls = set()
        
        # 解析精选
        for item in result.get("top_picks", []):
            url = item.get("url", "")
            if url in url_to_article and url not in selected_urls:
                article = url_to_article[url]
                article.is_top_pick = True
                top_picks.append(article)
                selected_urls.add(url)
        
        # 解析速览
        for item in result.get("quick_reads", []):
            url = item.get("url", "")
            if url in url_to_article and url not in selected_urls:
                article = url_to_article[url]
                article.is_top_pick = False
                quick_reads.append(article)
                selected_urls.add(url)
        
        # 应用硬上限
        if len(top_picks) + len(quick_reads) > max_articles:
            quick_reads = quick_reads[:max_articles - len(top_picks)]
        
        # 未选中的文章
        excluded = [a for a in articles if a.url not in selected_urls]
        
        return {
            "top_picks": top_picks,
            "quick_reads": quick_reads,
            "excluded": excluded,
            "daily_summary": result.get("daily_summary", ""),
            "selection_reasoning": result.get("selection_reasoning", ""),
        }
    
    def _simple_selection(self, articles: list[EnrichedArticle]) -> dict:
        """简单筛选（用于文章数量少或 AI 失败时）"""
        # 按评分排序
        sorted_articles = sorted(articles, key=lambda x: x.overall_score, reverse=True)
        
        top_picks = []
        quick_reads = []
        excluded = []
        
        for a in sorted_articles:
            if a.overall_score >= 8.0 and len(top_picks) < 5:
                a.is_top_pick = True
                top_picks.append(a)
            elif a.overall_score >= 5.0 and len(quick_reads) < 20:
                a.is_top_pick = False
                quick_reads.append(a)
            else:
                excluded.append(a)
        
        return {
            "top_picks": top_picks,
            "quick_reads": quick_reads,
            "excluded": excluded,
            "daily_summary": "",
        }
    
    async def process(self, input_data: Any, context: AgentContext) -> AgentOutput:
        """实现基类要求的 process 方法"""
        # 这个 Agent 主要通过 curate 方法使用
        pass
