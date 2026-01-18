"""Analysis Orchestrator - 协调所有 Agent 的工作流"""

import asyncio
import time
from typing import Optional
import structlog

from ..config import AppConfig
from ..models.article import Article, EnrichedArticle
from ..models.agent import AgentContext, AgentOutput, AgentTrace, AnalysisMode
from ..models.information import InformationUnit
from ..models.entity import ExtractedEntity, ExtractedRelation
from ..services.llm import LLMService
from ..storage.vector_store import VectorStore
from ..storage.information_store import InformationStore
from ..storage.entity_store import EntityStore

from .collector import CollectorAgent
from .librarian import LibrarianAgent
from .editor import EditorAgent
from .extractor import InformationExtractorAgent
from .merger import InformationMergerAgent
from .analysts import SkepticAnalyst, EconomistAnalyst, DetectiveAnalyst
from .trace_manager import TraceManager

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
    
    def __init__(self, config: AppConfig, enable_trace: bool = True, progress_tracker=None):
        self.config = config
        self.llm_service = LLMService(config.ai)
        self.enable_trace = enable_trace
        self.progress_tracker = progress_tracker  # 🆕 可选的进度追踪器
        
        # 初始化向量存储
        vector_store_path = str(config.storage.database_path).replace(".db", "_vectors")
        self.vector_store = VectorStore(vector_store_path)
        
        # 初始化追踪管理器
        trace_dir = str(config.storage.database_path).replace(".db", "_traces")
        self.trace_manager = TraceManager(trace_dir) if enable_trace else None
        
        # 初始化所有 Agent
        self.collector = CollectorAgent(self.llm_service)
        self.librarian = LibrarianAgent(self.llm_service, self.vector_store)
        self.editor = EditorAgent(self.llm_service)
        
        self.analysts = {
            "skeptic": SkepticAnalyst(self.llm_service),
            "economist": EconomistAnalyst(self.llm_service),
            "detective": DetectiveAnalyst(self.llm_service),
        }
        
        # 新架构组件
        self.info_store: Optional[InformationStore] = None
        self.entity_store: Optional[EntityStore] = None  # 🆕 知识图谱存储
        self.extractor = InformationExtractorAgent(self.llm_service)
        self.merger = InformationMergerAgent(self.llm_service)

    def set_information_store(self, store: InformationStore):
        """注入 InformationStore"""
        self.info_store = store
    
    def set_entity_store(self, store: EntityStore):
        """注入 EntityStore (知识图谱)"""
        self.entity_store = store
    
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
        
        # 开始追踪会话
        if self.trace_manager:
            self.trace_manager.start_session(article.url, article.title)
        
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
            
            # 保存最终结果
            if self.trace_manager:
                self.trace_manager.save_final_result(enriched)
                session_path = self.trace_manager.end_session()
                logger.info("trace_saved", path=str(session_path))
            
            return enriched
            
        except Exception as e:
            logger.error(
                "analysis_failed",
                title=article.title[:50],
                error=str(e),
            )
            if self.trace_manager:
                self.trace_manager.end_session()
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
        self._save_trace("Collector", article, collector_result)
        
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
        self._save_trace("Collector", article, collector_result)
        
        # Step 2: Librarian
        librarian_result = await self.librarian.safe_process(article, context)
        context.add_trace(librarian_result.trace)
        self._save_trace("Librarian", article, librarian_result)
        
        # Step 3: 简化的 Editor（没有分析师报告）
        editor_result = await self.editor.process(
            article=article,
            context=context,
            analyst_reports={},
        )
        context.add_trace(editor_result.trace)
        self._save_trace("Editor", article, editor_result)
        
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
        self._save_trace("Collector", article, collector_result)
        
        # Step 2: Librarian
        librarian_result = await self.librarian.safe_process(article, context)
        context.add_trace(librarian_result.trace)
        self._save_trace("Librarian", article, librarian_result)
        
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
            self._save_trace(f"Analyst_{name}", article, result)
        
        # Step 4: Editor
        editor_result = await self.editor.process(
            article=article,
            context=context,
            analyst_reports=analyst_results,
        )
        context.add_trace(editor_result.trace)
        self._save_trace("Editor", article, editor_result)
        
        enriched = editor_result.data
        enriched.analysis_mode = AnalysisMode.DEEP.value
        enriched.agent_traces = context.traces
        
        return enriched
    
    def _save_trace(self, agent_name: str, article: Article, result: AgentOutput):
        """保存 Agent 追踪数据"""
        if not self.trace_manager:
            return
        
        trace = result.trace
        if trace:
            self.trace_manager.save_agent_output(
                agent_name=agent_name,
                input_data={"title": article.title, "url": article.url},
                output_data=result.data,
                duration_seconds=trace.duration_seconds,
                token_usage=trace.token_usage,
                error=trace.error,
            )
    
    async def process_article_information_centric(self, article: Article) -> list[InformationUnit]:
        """
        以信息为中心的处理流程
        1. Extract: 文章 -> 信息单元列表
        2. Merge: 与库中现有单元去重/合并 (使用语义相似度)
        3. Save: 持久化
        """
        if not self.info_store:
            logger.warning("information_store_not_configured")
            return []
            
        logger.info("processing_info_centric", title=article.title)
        
        # Context
        context = AgentContext(
            original_article=article,
            analysis_mode=AnalysisMode.DEEP  # Default to DEEP for info centric to get best results
        )
        if self.trace_manager:
            self.trace_manager.start_session(article.url, article.title + " [INFO_FLOW]")

        try:
            # 🆕 0. OPTIONAL: Run Analysts First (Consultant Mode)
            # This provides high-quality perspective to the extractor
            if context.analysis_mode == AnalysisMode.DEEP:
                logger.info("running_consultant_analysts")
                
                # Define which analysts to run
                analyst_names = ["skeptic", "economist", "detective"]
                
                # Run them in parallel using asyncio.gather for true concurrency
                tasks = []
                names = []
                
                for name in analyst_names:
                    if name in self.analysts:
                        tasks.append(self.analysts[name].safe_process(article, context))
                        names.append(name)
                
                if tasks:
                    results = await asyncio.gather(*tasks)
                    
                    analyst_results = {}
                    for name, result in zip(names, results):
                        analyst_results[name] = result.data
                        context.add_trace(result.trace)
                        # Save trace
                        self._save_trace(f"Consultant_{name}", article, result)
                    
                    # Store reports in context for Extractor to see
                    context.analyst_reports = analyst_results
                    logger.info("consultant_phase_complete", reports=list(analyst_results.keys()))

            # 1. Extract (Augmented by Analyst Reports if available)
            units = await self.extractor.extract(article, context)
            logger.info("extracted_units", count=len(units))
            
            final_units = []
            
            for unit in units:
                # 2. Check & Merge using Semantic Similarity (Primary) + Fingerprint (Fallback)
                
                # 2.1 首先检查精确指纹匹配
                existing = self.info_store.get_unit_by_fingerprint(unit.fingerprint)
                
                if existing:
                    logger.info("merging_exact_fingerprint_match", fingerprint=unit.fingerprint)
                    merged = await self.merger.merge([existing, unit])
                    await self.info_store.save_unit(merged)
                    final_units.append(merged)
                    
                    if self.trace_manager:
                        self.trace_manager.save_agent_output(
                            agent_name="Merger",
                            input_data={"unit_new": unit.title, "unit_exist": existing.title, "match_type": "fingerprint"},
                            output_data={"merged": merged.title},
                            duration_seconds=0, token_usage={}
                        )
                    continue
                
                # 2.2 如果没有精确匹配，使用向量相似度搜索
                similar_units = await self.info_store.find_similar_units(unit, threshold=0.6, top_k=3)
                
                if similar_units:
                    # 找到语义相似的单元，进行合并
                    logger.info(
                        "merging_semantically_similar_units",
                        new_title=unit.title,
                        similar_count=len(similar_units),
                        similar_titles=[u.title for u in similar_units]
                    )
                    
                    # 合并所有相似单元 + 新单元
                    all_to_merge = similar_units + [unit]
                    merged = await self.merger.merge(all_to_merge)
                    
                    # 更新合并后的单元（使用第一个相似单元的 ID 作为主 ID）
                    merged.id = similar_units[0].id
                    merged.fingerprint = similar_units[0].fingerprint
                    
                    # 🆕 保留原有的分析内容（如果有价值）
                    # 如果新单元有分析师支持，可能比旧的更好，Merger 需要智能判断
                    # 这里假设 Merger 已经能够处理好
                    
                    await self.info_store.save_unit(merged)
                    final_units.append(merged)
                    
                    if self.trace_manager:
                        self.trace_manager.save_agent_output(
                            agent_name="Merger",
                            input_data={
                                "unit_new": unit.title, 
                                "similar_units": [u.title for u in similar_units],
                                "match_type": "semantic"
                            },
                            output_data={"merged": merged.title, "source_count": merged.source_count},
                            duration_seconds=0, token_usage={}
                        )
                else:
                    # 完全新的单元
                    await self.info_store.save_unit(unit)
                    final_units.append(unit)
                
                # 🆕 处理实体和关系 (构建知识图谱)
                if self.entity_store and (unit.extracted_entities or unit.extracted_relations):
                    try:
                        # 转换为 ExtractedEntity 对象
                        extracted_entities = [
                            ExtractedEntity(
                                name=e.get("name", ""),
                                aliases=e.get("aliases", []),
                                type=e.get("type", "COMPANY"),
                                role=e.get("role", "主角"),
                                state_change=e.get("state_change"),
                            ) for e in unit.extracted_entities if isinstance(e, dict) and e.get("name")
                        ]
                        
                        extracted_relations = [
                            ExtractedRelation(
                                source=r.get("source", ""),
                                target=r.get("target", ""),
                                relation=r.get("relation", "peer"),
                                evidence=r.get("evidence", ""),
                            ) for r in unit.extracted_relations if isinstance(r, dict) and r.get("source")
                        ]
                        
                        if extracted_entities:
                            entity_id_map = self.entity_store.process_extracted_entities(
                                unit_id=unit.id,
                                entities=extracted_entities,
                                relations=extracted_relations,
                                event_time=unit.event_time,
                            )
                            logger.debug("entities_processed", 
                                        unit_id=unit.id, 
                                        entity_count=len(entity_id_map))
                    except Exception as e:
                        logger.warning("entity_processing_failed", unit_id=unit.id, error=str(e))
            
            if self.trace_manager:
                self.trace_manager.end_session()
                
            return final_units
            
        except Exception as e:
            logger.error("info_flow_failed", error=str(e))
            if self.trace_manager:
                self.trace_manager.end_session()
            return []

    def get_stats(self) -> dict:
        """获取协调器统计信息"""
        return {
            "vector_store": self.vector_store.get_stats() if self.vector_store else {},
            "trace_enabled": self.trace_manager is not None,
            "info_store_enabled": self.info_store is not None,
            "agents": [
                self.collector.name,
                self.librarian.name,
                self.editor.name,
                self.extractor.name,
                self.merger.name,
            ] + list(self.analysts.keys()),
        }

