"""Analysis Orchestrator - 协调所有 Agent 的工作流"""

import asyncio
import time
from typing import Optional
import structlog

from ..config import AppConfig
from ..models.article import Article, EnrichedArticle
from ..models.agent import AgentContext, AgentOutput, AgentTrace, AnalysisMode
from ..services.llm import LLMService
from ..storage.vector_store import VectorStore

from .collector import CollectorAgent
from .librarian import LibrarianAgent
from .editor import EditorAgent
from .analysts import SkepticAnalyst, EconomistAnalyst, DetectiveAnalyst

logger = structlog.get_logger()


class AnalysisOrchestrator:
    """
    分析协调器
    
    管理多智能体工作流：
    Article → Collector → Librarian → Analysts (并行) → Editor → EnrichedArticle
    
    支持三种分析模式：
    - QUICK: 仅 Collector (快速评分和摘要)
    - STANDARD: Collector + Librarian + Editor (基础分析)
    - DEEP: 完整流程 (所有 Agent)
    """
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.llm_service = LLMService(config.ai)
        
        # 初始化向量存储
        vector_store_path = str(config.storage.database_path).replace(".db", "_vectors")
        self.vector_store = VectorStore(vector_store_path)
        
        # 初始化所有 Agent
        self.collector = CollectorAgent(self.llm_service)
        self.librarian = LibrarianAgent(self.llm_service, self.vector_store)
        self.editor = EditorAgent(self.llm_service)
        
        self.analysts = {
            "skeptic": SkepticAnalyst(self.llm_service),
            "economist": EconomistAnalyst(self.llm_service),
            "detective": DetectiveAnalyst(self.llm_service),
        }
    
    async def analyze_article(
        self, 
        article: Article,
        mode: AnalysisMode = AnalysisMode.DEEP,
    ) -> EnrichedArticle:
        """
        分析单篇文章
        
        Args:
            article: 待分析的文章
            mode: 分析模式 (QUICK, STANDARD, DEEP)
            
        Returns:
            EnrichedArticle 包含完整分析结果
        """
        start_time = time.time()
        logger.info(
            "analysis_started",
            title=article.title[:50],
            mode=mode.value,
        )
        
        context = AgentContext(
            original_article=article,
            analysis_mode=mode,
        )
        
        try:
            if mode == AnalysisMode.QUICK:
                enriched = await self._quick_analysis(article, context)
            elif mode == AnalysisMode.STANDARD:
                enriched = await self._standard_analysis(article, context)
            else:  # DEEP
                enriched = await self._deep_analysis(article, context)
            
            duration = time.time() - start_time
            logger.info(
                "analysis_completed",
                title=article.title[:50],
                mode=mode.value,
                score=enriched.overall_score,
                is_top_pick=enriched.is_top_pick,
                duration=f"{duration:.2f}s",
                total_tokens=context.get_total_tokens(),
            )
            
            return enriched
            
        except Exception as e:
            logger.error(
                "analysis_failed",
                title=article.title[:50],
                error=str(e),
            )
            # 返回基础的 EnrichedArticle
            return EnrichedArticle.from_article(article)
    
    async def analyze_batch(
        self,
        articles: list[Article],
        mode: AnalysisMode = AnalysisMode.DEEP,
        max_concurrent: int = 3,
    ) -> list[EnrichedArticle]:
        """
        批量分析文章
        
        Args:
            articles: 待分析的文章列表
            mode: 分析模式
            max_concurrent: 最大并发数
            
        Returns:
            EnrichedArticle 列表
        """
        if not articles:
            return []
        
        logger.info(
            "batch_analysis_started",
            count=len(articles),
            mode=mode.value,
        )
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def analyze_with_semaphore(article: Article) -> EnrichedArticle:
            async with semaphore:
                return await self.analyze_article(article, mode)
        
        tasks = [analyze_with_semaphore(a) for a in articles]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        enriched_articles = []
        for article, result in zip(articles, results):
            if isinstance(result, Exception):
                logger.error(
                    "article_analysis_failed",
                    title=article.title[:50],
                    error=str(result),
                )
                enriched_articles.append(EnrichedArticle.from_article(article))
            else:
                enriched_articles.append(result)
        
        # 按评分排序
        enriched_articles.sort(key=lambda x: x.overall_score, reverse=True)
        
        logger.info(
            "batch_analysis_completed",
            count=len(enriched_articles),
            top_picks=sum(1 for a in enriched_articles if a.is_top_pick),
        )
        
        return enriched_articles
    
    async def _quick_analysis(
        self, 
        article: Article, 
        context: AgentContext
    ) -> EnrichedArticle:
        """快速分析模式：仅 Collector"""
        # Step 1: Collector
        collector_result = await self.collector.safe_process(article, context)
        context.add_trace(collector_result.trace)
        
        # 直接构建结果
        extracted = context.extracted_5w1h or {}
        
        return EnrichedArticle(
            url=article.url,
            title=article.title,
            content=article.content,
            summary=article.summary,
            source=article.source,
            category=article.category,
            author=article.author,
            published_at=article.published_at,
            fetched_at=article.fetched_at,
            who=extracted.get("who", []),
            what=extracted.get("what", ""),
            when=extracted.get("when", ""),
            where=extracted.get("where", ""),
            why=extracted.get("why", ""),
            how=extracted.get("how", ""),
            ai_summary=extracted.get("core_summary", ""),
            tags=extracted.get("tags", []),
            overall_score=5.0,  # 快速模式默认中等分数
            analysis_mode=AnalysisMode.QUICK.value,
            agent_traces=context.traces,
        )
    
    async def _standard_analysis(
        self, 
        article: Article, 
        context: AgentContext
    ) -> EnrichedArticle:
        """标准分析模式：Collector + Librarian + Editor"""
        # Step 1: Collector
        collector_result = await self.collector.safe_process(article, context)
        context.add_trace(collector_result.trace)
        
        # Step 2: Librarian
        librarian_result = await self.librarian.safe_process(article, context)
        context.add_trace(librarian_result.trace)
        
        # Step 3: 简化的 Editor（没有分析师报告）
        editor_result = await self.editor.process(
            article=article,
            context=context,
            analyst_reports={},
        )
        context.add_trace(editor_result.trace)
        
        enriched = editor_result.data
        enriched.analysis_mode = AnalysisMode.STANDARD.value
        enriched.agent_traces = context.traces
        
        return enriched
    
    async def _deep_analysis(
        self, 
        article: Article, 
        context: AgentContext
    ) -> EnrichedArticle:
        """深度分析模式：完整流程"""
        # Step 1: Collector
        collector_result = await self.collector.safe_process(article, context)
        context.add_trace(collector_result.trace)
        
        # Step 2: Librarian
        librarian_result = await self.librarian.safe_process(article, context)
        context.add_trace(librarian_result.trace)
        
        # Step 3: Analyst Team (并行执行)
        analyst_tasks = {
            name: analyst.safe_process(article, context)
            for name, analyst in self.analysts.items()
        }
        
        analyst_results = {}
        for name, task in analyst_tasks.items():
            result = await task
            analyst_results[name] = result.data
            context.add_trace(result.trace)
            context.analyst_reports[name] = result.data
        
        # Step 4: Editor
        editor_result = await self.editor.process(
            article=article,
            context=context,
            analyst_reports=analyst_results,
        )
        context.add_trace(editor_result.trace)
        
        enriched = editor_result.data
        enriched.analysis_mode = AnalysisMode.DEEP.value
        enriched.agent_traces = context.traces
        
        return enriched
    
    def get_stats(self) -> dict:
        """获取协调器统计信息"""
        return {
            "vector_store": self.vector_store.get_stats() if self.vector_store else {},
            "agents": [
                self.collector.name,
                self.librarian.name,
                self.editor.name,
            ] + list(self.analysts.keys()),
        }
