"""RSS AI Reader - 主程序入口 (Multi-Agent Version)"""

import argparse
import asyncio
import signal
import sys
from datetime import datetime
from pathlib import Path

# 确保可以找到 src 包（支持直接运行此文件）
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog

# 配置日志
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)

try:
    # 作为模块运行: python -m src.main
    from .config import get_config, reload_config, AppConfig
    from .fetcher import RSSParser, ContentExtractor
    from .agents import AnalysisOrchestrator
    from .models.agent import AnalysisMode
    from .models.article import Article as NewArticle, EnrichedArticle
    from .storage import Database, DigestArticle, DailyDigest, InformationStore
    from .storage.models import Article as LegacyArticle, AnalyzedArticle
    from .notifier import EmailSender
    from .scheduler import Scheduler
    from .services.telemetry import AITelemetry, get_telemetry
except ImportError:
    # 直接运行: python src/main.py
    from src.config import get_config, reload_config, AppConfig
    from src.fetcher import RSSParser, ContentExtractor
    from src.agents import AnalysisOrchestrator
    from src.models.agent import AnalysisMode
    from src.models.article import Article as NewArticle, EnrichedArticle
    from src.storage import Database, DigestArticle, DailyDigest, InformationStore
    from src.storage.models import Article as LegacyArticle, AnalyzedArticle
    from src.notifier import EmailSender
    from src.scheduler import Scheduler
    from src.services.telemetry import AITelemetry, get_telemetry

logger = structlog.get_logger()


class RSSReaderService:
    """RSS 阅读器服务 (Multi-Agent Version)"""
    
    def __init__(self, config: AppConfig, analysis_mode: str = "deep", concurrency: int = 5):
        self.config = config
        self.concurrency = concurrency  # 并发处理数量
        
        # 解析分析模式
        self.analysis_mode = AnalysisMode(analysis_mode)
        
        # 初始化组件
        self.db = Database(config.storage.database_path)
        self.rss_parser = RSSParser()
        self.content_extractor = ContentExtractor()
        
        # 🆕 多智能体分析器
        self.orchestrator = AnalysisOrchestrator(config)
        
        self.email_sender = EmailSender(config.email)
        self.scheduler = Scheduler(config.schedule)
        
        # 🆕 初始化遥测服务
        AITelemetry.initialize(
            enabled=config.telemetry.enabled,
            storage_path=config.telemetry.storage_path,
            retention_days=config.telemetry.retention_days,
            max_content_length=config.telemetry.max_content_length,
        )
        
        # 运行状态
        self._running = False
        
        logger.info(
            "service_initialized",
            analysis_mode=self.analysis_mode.value,
            vector_store=self.orchestrator.get_stats().get("vector_store", {}),
        )
        
        # 初始化信息存储并注入协调器（传入向量存储以启用语义去重）
        self.info_store = InformationStore(self.db, vector_store=self.orchestrator.vector_store)
        self.orchestrator.set_information_store(self.info_store)
        
        # 🆕 初始化实体存储（知识图谱）
        from .storage.entity_store import EntityStore
        self.entity_store = EntityStore(self.db)
        self.orchestrator.set_entity_store(self.entity_store)
    
    async def fetch_and_analyze(self, limit: int = None):
        """抓取并分析文章
        
        Args:
            limit: 限制分析的文章数量（用于测试）
        """
        logger.info("starting_fetch_cycle", mode=self.analysis_mode.value, limit=limit)
        
        try:
            # 1. 抓取 RSS
            articles = await self.rss_parser.fetch_all(self.config.feeds)
            
            if not articles:
                logger.info("no_new_articles")
                return
            
            # 2. 过滤已存在的文章
            new_articles = [
                a for a in articles 
                if not self.db.article_exists(a.url)
            ]
            
            if not new_articles:
                logger.info("all_articles_exist", total=len(articles))
                return
            
            logger.info("new_articles_found", count=len(new_articles))
            
            # 3. 应用数量限制（用于测试）
            if limit and limit > 0:
                new_articles = new_articles[:limit]
                logger.info("articles_limited", limit=limit, count=len(new_articles))
            
            # 4. 提取正文
            articles_with_content = await self.content_extractor.extract_all(new_articles)
            
            # 5. 转换为新的 Article 模型
            new_format_articles = [
                self._convert_to_new_article(a) for a in articles_with_content
            ]
            
            # 5. 🆕 多智能体分析 (Legacy Flow - DISABLED)
            # enriched_articles = await self.orchestrator.analyze_batch(
            #     new_format_articles,
            #     mode=self.analysis_mode,
            #     max_concurrent=3,
            # )
            enriched_articles = []
            
            # 6. 保存到数据库 (Legacy Flow - DISABLED)
            # for article in enriched_articles:
            #     legacy_article = self._convert_to_legacy_article(article)
            #     self.db.save_analyzed_article(legacy_article)
            
            # 7. 🆕 信息为中心的处理流程 (Beta) - 并发版本
            logger.info("starting_info_centric_processing")
            info_processing_count = 0
            
            # 并发控制：使用 Semaphore 限制同时处理的文章数量
            CONCURRENT_LIMIT = self.concurrency  # 使用实例配置的并发数
            semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
            logger.info("concurrent_processing_enabled", workers=CONCURRENT_LIMIT)
            
            async def process_single_article(article):
                """带信号量控制的单篇文章处理"""
                async with semaphore:
                    # 先保存文章到数据库（确保不丢失）
                    self.db.save_article(article)
                    # 深度分析并提取信息单元
                    units = await self.orchestrator.process_article_information_centric(article)
                    return len(units)
            
            # 创建所有任务并并发执行
            tasks = [process_single_article(article) for article in new_format_articles]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 统计成功处理的数量
            for result in results:
                if isinstance(result, int):
                    info_processing_count += result
                elif isinstance(result, Exception):
                    logger.error("concurrent_article_failed", error=str(result))
            
            logger.info("fetch_cycle_complete",
                       fetched=len(articles),
                       new=len(new_articles),
                       analyzed=len(enriched_articles),
                       info_units_created=info_processing_count,
                       top_picks=sum(1 for a in enriched_articles if a.is_top_pick))
        
        except Exception as e:
            logger.error("fetch_cycle_failed", error=str(e))
            import traceback
            traceback.print_exc()
    
    async def send_daily_digest(self):
        """发送每日简报（使用 AI 智能筛选）"""
        logger.info("preparing_daily_digest")
        
        try:
            # Check for unsent information units FIRST (New Architecture)
            # 🆕 使用 Curator AI 智能筛选
            # 优先尝试基于 Information Units 的简报
            from src.agents import CuratorAgent, InformationCuratorAgent
            from src.services.llm import LLMService

            unsent_units = self.info_store.get_unsent_units(limit=50)
            
            if len(unsent_units) >= 1: # Even 1 is enough for a digest if manual limit/once
                 # Use Information Centric Curation logic directly
                 pass # Logic continues below
            else:
                 # Check Legacy DB
                # 获取未发送的文章
                db_articles = self.db.get_unsent_articles(
                    limit=self.config.filter.max_articles_per_digest
                )
                
                if not db_articles:
                    logger.info("no_articles_to_send")
                    return
                
                logger.info("articles_for_curation", count=len(db_articles))
            
                # 转换为 EnrichedArticle 格式供 Curator 使用
                enriched_articles = []
                for a in db_articles:
                    enriched = EnrichedArticle(
                        url=a.url,
                        title=a.title,
                        content=a.content or "",
                        summary=a.summary or "",
                        source=a.source,
                        category=a.category,
                        overall_score=a.score or 5.0,
                        ai_summary=a.ai_summary or "",
                        is_top_pick=a.is_top_pick,
                        tags=a.tags or [],
                    )
                    enriched_articles.append(enriched)
            
            # Check for unsent information units
            # unsent_units variable is already set above
            
            if len(unsent_units) >= 1: # Lowered threshold from 5 to 1 for flexibility
                # Use Information Centric Curation
                logger.info("generating_info_centric_digest", units=len(unsent_units))
                info_curator = InformationCuratorAgent(LLMService(self.config.ai))
                curation_result = await info_curator.curate(
                    unsent_units,
                    max_top_picks=self.config.filter.max_articles_per_digest
                )
                
                # Build digest from Information Curation
                top_picks = []
                for item in curation_result["top_picks"]:
                    # Format as HTML for email
                    presentation = item.get("presentation", {})
                    summary_html = f"""
                    <div style="margin-bottom: 8px;"><strong>📝 事实摘要：</strong>{presentation.get('summary', '')}</div>
                    <div style="margin-bottom: 8px; color: #4b5563;"><strong>💡 深度分析：</strong>{presentation.get('analysis', '')}</div>
                    <div style="color: #ea580c;"><strong>🌊 潜在影响：</strong>{presentation.get('impact', '')}</div>
                    """
                    
                    top_picks.append(DigestArticle(
                        title=item.get("display_title", ""),
                        url=self._get_unit_url(item.get("id"), unsent_units), # Helper needed
                        source=" | ".join(self._get_unit_sources(item.get("id"), unsent_units)),
                        category="深度精选",
                        score=item.get("score", (item.get("reasoning", {}).get("score", 9.0) if isinstance(item.get("reasoning"), dict) else 9.0)),
                        summary=summary_html,
                        reasoning=item.get("reasoning", "") if isinstance(item.get("reasoning"), str) else "",
                        is_top_pick=True,
                        tags=[], # Tags not in output yet, maybe skip or fetch
                    ))
                    
                other_articles = []
                for item in curation_result["quick_reads"]:
                    other_articles.append(DigestArticle(
                        title=item.get("display_title", ""),
                        url=self._get_unit_url(item.get("id"), unsent_units),
                        source="快速浏览",
                        category="资讯",
                        score=7.0,
                        summary=item.get("one_line_summary", ""),
                        reasoning="",
                        is_top_pick=False,
                        tags=[],
                    ))
                    
                # Mark units as sent
                sent_ids = [item.get("id") for item in curation_result["top_picks"] + curation_result["quick_reads"]]
                self.info_store.mark_units_sent(sent_ids)
                
                # Create Digest Object
                digest = DailyDigest(
                    date=datetime.now(),
                    top_picks=top_picks,
                    other_articles=other_articles,
                    total_fetched=len(unsent_units), # Approx
                    total_analyzed=len(unsent_units),
                    total_filtered=len(top_picks) + len(other_articles),
                )
            
            else:
                # Fallback to Old Article-Centric Curation
                logger.info("fallback_to_article_curation", reason="not_enough_info_units")
                
                curator = CuratorAgent(LLMService(self.config.ai))
                curation_result = await curator.curate(
                    enriched_articles,
                    max_articles=self.config.filter.max_articles_per_digest,
                )
            
                # 构建简报 (Old Logic)
                top_picks = []
                for article in curation_result["top_picks"]:
                    top_picks.append(DigestArticle(
                        title=article.title,
                        url=article.url,
                        source=article.source,
                        category=article.category,
                        score=article.overall_score,
                        summary=article.ai_summary or article.summary,
                        reasoning="",
                        is_top_pick=True,
                        tags=article.tags,
                    ))
                
                other_articles = []
                for article in curation_result["quick_reads"]:
                    other_articles.append(DigestArticle(
                        title=article.title,
                        url=article.url,
                        source=article.source,
                        category=article.category,
                        score=article.overall_score,
                        summary=article.ai_summary or article.summary,
                        reasoning="",
                        is_top_pick=False,
                        tags=article.tags,
                    ))
                
                digest = DailyDigest(
                    date=datetime.now(),
                    top_picks=top_picks,
                    other_articles=other_articles,
                    total_fetched=len(db_articles),
                    total_analyzed=len(db_articles),
                    total_filtered=len(top_picks) + len(other_articles),
                )
                
                # Mark Articles Sent (Old Logic)
                if True: # Will be handled below
                    sent_urls = [a.url for a in top_picks + other_articles]
                    self.db.mark_articles_sent(sent_urls)
            
            logger.info(
                "curation_complete",
                top_picks=len(top_picks),
                quick_reads=len(other_articles),
                excluded=len(curation_result.get("excluded", [])),
                daily_summary=curation_result.get("daily_summary", "")[:100],
            )
            
            # 发送邮件
            # 发送邮件
            success = await self.email_sender.send_digest(digest)
            
            if success:
                logger.info("digest_sent_successfully",
                           top_picks=len(top_picks),
                           other=len(other_articles))
            else:
                logger.error("digest_send_failed")
                

        
        except Exception as e:
            logger.error("digest_preparation_failed", error=str(e))
            import traceback
            traceback.print_exc()
    
    async def run_once(self, dry_run: bool = False, limit: int = None):
        """运行一次（用于测试）
        
        Args:
            dry_run: 是否不发送邮件
            limit: 限制分析的文章数量
        """
        await self.fetch_and_analyze(limit=limit)
        
        if not dry_run:
            await self.send_daily_digest()
    
    async def run(self):
        """启动服务"""
        logger.info("starting_service", mode=self.analysis_mode.value)
        self._running = True
        
        # 添加定时任务
        self.scheduler.add_fetch_job(self.fetch_and_analyze)
        self.scheduler.add_digest_job(self.send_daily_digest)
        
        # 启动时执行一次抓取
        await self.fetch_and_analyze()
        
        # 启动调度器
        self.scheduler.start()
        
        # 保持运行
        try:
            while self._running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            self.scheduler.stop()
            self.content_extractor.close()
            logger.info("service_stopped")
    
    def stop(self):
        """停止服务"""
        self._running = False
    
    def _convert_to_new_article(self, legacy: LegacyArticle) -> NewArticle:
        """将旧版 Article 转换为新版"""
        return NewArticle(
            url=legacy.url,
            title=legacy.title,
            content=legacy.content,
            summary=legacy.summary,
            source=legacy.source,
            category=legacy.category,
            author=legacy.author,
            published_at=legacy.published_at,
            fetched_at=legacy.fetched_at,
        )
    
    def _convert_to_legacy_article(self, enriched: EnrichedArticle) -> AnalyzedArticle:
        """将 EnrichedArticle 转换为旧版 AnalyzedArticle（用于数据库存储）"""
        return AnalyzedArticle(
            url=enriched.url,
            title=enriched.title,
            content=enriched.content,
            summary=enriched.summary,
            source=enriched.source,
            category=enriched.category,
            author=enriched.author,
            published_at=enriched.published_at,
            fetched_at=enriched.fetched_at,
            score=enriched.overall_score,
            ai_summary=enriched.ai_summary,
            is_top_pick=enriched.is_top_pick,
            reasoning=self._build_reasoning(enriched),
            tags=enriched.tags,
        )
    
    def _build_reasoning(self, enriched: EnrichedArticle) -> str:
        """从 EnrichedArticle 构建推理摘要"""
        parts = []
        
        # 可信度
        if enriched.source_credibility:
            parts.append(f"信源: {enriched.source_credibility.tier}")
        
        # 影响
        if enriched.impact_analysis and enriched.impact_analysis.direct_impact:
            parts.append(f"直接影响: {len(enriched.impact_analysis.direct_impact)}项")
        
        # 市场情绪
        if enriched.market_sentiment:
            parts.append(f"市场: {enriched.market_sentiment.overall}")
        
        # 风险
        if enriched.risk_warnings:
            parts.append(f"风险警示: {len(enriched.risk_warnings)}项")
        
        return " | ".join(parts) if parts else ""

    def _get_unit_url(self, unit_id: str, units: list) -> str:
        """Helper to get primary URL from unit ID"""
        for u in units:
            if u.id == unit_id:
                return u.primary_source
        return "#"

    def _get_unit_sources(self, unit_id: str, units: list) -> list:
        """Helper to get source names"""
        for u in units:
            if u.id == unit_id:
                return list(set(s.source_name for s in u.sources))[:3]
        return []


    async def run_backfill(self, limit: int = 100):
        """运行实体回填"""
        from src.agents import EntityBackfillAgent
        from src.services.llm import LLMService
        
        logger.info("starting_entity_backfill", limit=limit)
        
        backfill_agent = EntityBackfillAgent(
            llm_service=LLMService(self.config.ai),
            info_store=self.info_store,
            entity_store=self.entity_store
        )
        
        await backfill_agent.run(limit=limit)

    def run_query(self, query: str):
        """查询实体信息"""
        print(f"🔍 正在查询: {query} ...")
        # 尝试精确匹配
        entity = self.entity_store.get_entity_by_name(query)
        
        if not entity:
            # 尝试模糊搜索
            candidates = self.entity_store.search_entities(query)
            if candidates:
                print(f"❓ 未找到精确匹配。您是指: {', '.join([e.canonical_name for e in candidates])} ?")
            else:
                print("❌ 未找到名为 '{}' 的实体".format(query))
            return
            
        print("\n" + "="*60)
        print(f"📍 {entity.canonical_name}  [{entity.type.value}]")
        print("-" * 60)
        print(f"📊 提及次数: {entity.mention_count}")
        print(f"📅 首次提及: {entity.first_mentioned}")
        print(f"📅 最近提及: {entity.last_mentioned}")
        
        # 别名
        aliases = self.entity_store.get_aliases(entity.id)
        if aliases:
            print(f"🏷️  别名: {', '.join(aliases)}")
        
        # 关系
        relations = self.entity_store.get_relations(entity.id)
        if relations:
            print(f"\n🔗 关系网络 ({len(relations)}):")
            for r in relations:
                other_id = r.target_id if r.source_id == entity.id else r.source_id
                other = self.entity_store.get_entity(other_id)
                other_name = other.canonical_name if other else "Unknown"
                
                direction = "➡️ " if r.source_id == entity.id else "⬅️ "
                rel_name = r.relation_type.value
                print(f"  {direction} {rel_name:<12} : {other_name} (置信度:{r.confidence})")
        
        # 最近提及
        mentions = self.entity_store.get_mentions_by_entity(entity.id, limit=5)
        if mentions:
            print(f"\n📝 最近提及:")
            for m in mentions:
                print(f"  • {m.event_time}: [{m.role}] {m.state_dimension or ''} {m.state_delta or ''}")
                
                print(f"  • {m.event_time}: [{m.role}] {m.state_dimension or ''} {m.state_delta or ''}")
                
        print("="*60 + "\n")

    def run_visualize(self, output: str = "data/knowledge_graph.html"):
        """生成知识图谱可视化"""
        from src.visualization import generate_knowledge_graph_html
        path = generate_knowledge_graph_html(self.entity_store, output)
        print(f"✅ 可视化图谱已生成: {path}")
        print(f"👉 请在浏览器中打开此文件查看交互式图谱")

    async def run_reprocess(self, limit: int = 100):
        """
        重新处理「已保存但未生成 units」的文章
        
        这些文章可能因为 LLM 超时、网络错误等原因导致分析失败
        """
        print(f"🔄 正在查找需要重新处理的文章...")
        
        # 查询 articles 表中存在但 information_units 表中没有对应记录的文章
        with self.db._get_conn() as conn:
            cursor = conn.execute("""
                SELECT a.url, a.title, a.content, a.source, a.published_at, a.fetched_at
                FROM articles a
                LEFT JOIN information_units u ON a.url = u.primary_source
                WHERE u.id IS NULL
                ORDER BY a.fetched_at DESC
                LIMIT ?
            """, (limit,))
            orphaned_articles = cursor.fetchall()
        
        if not orphaned_articles:
            print("✅ 没有需要重新处理的文章")
            return
            
        print(f"📋 找到 {len(orphaned_articles)} 篇待重新处理的文章")
        logger.info("reprocess_started", count=len(orphaned_articles))
        
        # 转换为 Article 对象
        from src.models.article import Article
        articles_to_process = []
        for row in orphaned_articles:
            article = Article(
                url=row['url'],
                title=row['title'],
                content=row['content'] or "",
                source=row['source'],
                published_at=row['published_at'],
                fetched_at=row['fetched_at'],
            )
            articles_to_process.append(article)
        
        # 使用并发处理
        import asyncio
        semaphore = asyncio.Semaphore(self.concurrency)
        success_count = 0
        
        async def process_one(article):
            nonlocal success_count
            async with semaphore:
                try:
                    units = await self.orchestrator.process_article_information_centric(article)
                    if units:
                        success_count += 1
                        print(f"  ✅ {article.title[:40]}... ({len(units)} units)")
                    else:
                        print(f"  ⚠️  {article.title[:40]}... (0 units)")
                    return len(units)
                except Exception as e:
                    print(f"  ❌ {article.title[:40]}... Error: {str(e)[:50]}")
                    logger.error("reprocess_failed", url=article.url, error=str(e))
                    return 0
        
        tasks = [process_one(article) for article in articles_to_process]
        await asyncio.gather(*tasks)
        
        print(f"\n🎉 重新处理完成: {success_count}/{len(orphaned_articles)} 篇成功")
        logger.info("reprocess_completed", success=success_count, total=len(orphaned_articles))


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="RSS AI Reader - 多智能体智能 RSS 阅读器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m src.main                         # 启动服务（深度分析模式）
  python -m src.main --mode quick            # 快速分析模式
  python -m src.main --mode standard         # 标准分析模式
  python -m src.main --once                  # 运行一次（分析所有新文章）
  python -m src.main --once --limit 1        # 只分析 1 篇（快速测试）
  python -m src.main --once --limit 5        # 只分析前 5 篇
  python -m src.main --once --dry-run        # 测试运行（不发送邮件）
  python -m src.main --test-email            # 发送测试邮件
        """
    )
    
    parser.add_argument(
        "--mode", "-m",
        type=str,
        choices=["quick", "standard", "deep"],
        default="deep",
        help="分析模式: quick(快速), standard(标准), deep(深度)"
    )
    
    parser.add_argument(
        "--once", "-1",
        action="store_true",
        help="只运行一次，然后退出"
    )
    
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="测试模式，不发送邮件"
    )
    
    parser.add_argument(
        "--test-email", "-t",
        action="store_true",
        help="发送测试邮件"
    )
    
    parser.add_argument(
        "--config-dir", "-c",
        type=str,
        default=None,
        help="配置文件目录"
    )
    
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        help="限制分析的文章数量（用于测试）"
    )
    
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="运行实体回填任务"
    )
    
    parser.add_argument(
        "--concurrency", "-j",
        type=int,
        default=5,
        help="并发处理文章数量 (默认: 5)"
    )
    
    
    parser.add_argument(
        "--query", "-q",
        type=str,
        help="查询实体知识图谱 (输入实体名称)"
    )
    
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="生成知识图谱可视化 HTML"
    )
    
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="重新处理「已保存但未生成 units」的文章"
    )
    
    parser.add_argument(
        "--digest",
        action="store_true",
        help="直接发送每日摘要邮件（不抓取新文章）"
    )
    
    # 添加 telemetry 子命令
    subparsers = parser.add_subparsers(dest="command", help="子命令")
    
    # telemetry 命令
    tele_parser = subparsers.add_parser("telemetry", help="AI 遥测管理")
    tele_subparsers = tele_parser.add_subparsers(dest="tele_action", help="遥测操作")
    
    # telemetry stats
    stats_parser = tele_subparsers.add_parser("stats", help="显示遥测统计")
    stats_parser.add_argument("--days", "-d", type=int, default=7, help="统计天数")
    
    # telemetry list
    list_parser = tele_subparsers.add_parser("list", help="列出最近的 AI 调用")
    list_parser.add_argument("--limit", "-l", type=int, default=20, help="显示数量")
    list_parser.add_argument("--session", "-s", type=str, help="按 session 过滤")
    list_parser.add_argument("--agent", "-a", type=str, help="按 agent 过滤")
    
    # telemetry export
    export_parser = tele_subparsers.add_parser("export", help="导出遥测数据")
    export_parser.add_argument("--output", "-o", type=str, default="telemetry_export.jsonl", help="输出文件")
    export_parser.add_argument("--days", "-d", type=int, default=7, help="导出天数")
    
    # telemetry cleanup
    cleanup_parser = tele_subparsers.add_parser("cleanup", help="清理过期遥测数据")
    
    # telemetry sessions
    sessions_parser = tele_subparsers.add_parser("sessions", help="列出追踪会话")
    sessions_parser.add_argument("--limit", "-l", type=int, default=20, help="显示数量")
    
    return parser.parse_args()


def handle_telemetry_command(args, config):
    """处理遥测相关命令"""
    from datetime import datetime, timedelta
    from src.services.telemetry import AITelemetry
    import json
    
    # 初始化遥测
    telemetry = AITelemetry.initialize(
        enabled=config.telemetry.enabled,
        storage_path=config.telemetry.storage_path,
        retention_days=config.telemetry.retention_days,
    )
    
    if args.tele_action == "stats":
        # 统计信息
        days = args.days
        start_time = datetime.now() - timedelta(days=days)
        stats = telemetry.get_stats(start_time=start_time)
        
        print(f"\n📊 AI 遥测统计 (最近 {days} 天)")
        print("=" * 40)
        print(f"总调用次数: {stats.total_calls}")
        print(f"总 Token 使用: {stats.total_tokens:,}")
        print(f"  - Prompt: {stats.total_prompt_tokens:,}")
        print(f"  - Completion: {stats.total_completion_tokens:,}")
        print(f"总耗时: {stats.total_duration_ms / 1000:.1f} 秒")
        print(f"平均耗时: {stats.avg_duration_ms:.0f} 毫秒/次")
        print(f"错误次数: {stats.error_count} ({stats.error_rate:.1f}%)")
        
        if stats.calls_by_type:
            print(f"\n按类型分布:")
            for call_type, count in stats.calls_by_type.items():
                print(f"  {call_type}: {count}")
        
        if stats.calls_by_agent:
            print(f"\n按 Agent 分布:")
            for agent, count in sorted(stats.calls_by_agent.items(), key=lambda x: -x[1])[:10]:
                print(f"  {agent or 'N/A'}: {count}")
    
    elif args.tele_action == "list":
        # 列出调用
        records = telemetry.query(
            limit=args.limit,
            session_id=getattr(args, 'session', None),
            agent_name=getattr(args, 'agent', None),
        )
        
        print(f"\n📋 最近 {len(records)} 条 AI 调用记录")
        print("=" * 80)
        for r in records:
            ts = r['timestamp'][:19] if r.get('timestamp') else 'N/A'
            agent = r.get('agent_name') or 'N/A'
            print(f"{ts} | {r['call_type']:<10} | {agent:<20} | {r['total_tokens']:>6} tokens | {r['duration_ms']:>5}ms")
    
    elif args.tele_action == "export":
        # 导出数据
        days = args.days
        start_time = datetime.now() - timedelta(days=days)
        output = args.output
        
        count = telemetry.export(output, start_time=start_time)
        print(f"\n✅ 已导出 {count} 条记录到 {output}")
    
    elif args.tele_action == "cleanup":
        # 清理数据
        deleted = telemetry.cleanup()
        print(f"\n✅ 已清理 {deleted} 条过期记录")
    
    elif args.tele_action == "sessions":
        # 列出 session
        sessions = telemetry.list_sessions(limit=args.limit)
        
        print(f"\n📁 最近 {len(sessions)} 个追踪会话")
        print("=" * 80)
        for s in sessions:
            print(f"{s['session_id']} | {s['call_count']:>3} calls | {s['total_tokens'] or 0:>6} tokens | {s['start_time'][:19]}")
    
    else:
        print("请指定操作: stats, list, export, cleanup, sessions")
        print("使用 --help 查看帮助")


async def async_main():
    """异步主函数"""
    args = parse_args()
    
    # 加载配置
    if args.config_dir:
        config = reload_config(Path(args.config_dir))
    else:
        config = get_config()
    
    # 处理 telemetry 子命令
    if args.command == "telemetry":
        handle_telemetry_command(args, config)
        return
    
    # 创建服务
    service = RSSReaderService(config, analysis_mode=args.mode, concurrency=args.concurrency)
    
    # 处理信号
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("received_shutdown_signal")
        service.stop()
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    # 运行模式
    if args.test_email:
        # 测试邮件
        email_sender = EmailSender(config.email)
        success = await email_sender.send_test_email()
        if success:
            print("✅ 测试邮件发送成功！")
        else:
            print("❌ 测试邮件发送失败，请检查配置")
            sys.exit(1)
    
            
    elif args.backfill:
        # 实体回填
        print(f"🔄 开始实体回填 (Limit: {args.limit or 100})...")
        await service.run_backfill(limit=args.limit or 100)
        print("✅ 回填完成！")
        
    elif args.query:
        # 查询实体
        service.run_query(args.query)
        
    elif args.visualize:
        # 可视化
        service.run_visualize()
    
    elif args.reprocess:
        # 重新处理失败的文章
        print(f"🔄 开始重新处理失败的文章 (Limit: {args.limit or 100})...")
        await service.run_reprocess(limit=args.limit or 100)
    
    elif args.digest:
        # 直接发送每日摘要
        print("📧 正在发送每日摘要...")
        await service.send_daily_digest()
        print("✅ 摘要发送完成！")
    
    elif args.once:
        # 运行一次
        mode_names = {"quick": "快速", "standard": "标准", "deep": "深度"}
        print(f"🔍 使用 {mode_names[args.mode]} 分析模式...")
        if args.limit:
            print(f"📊 限制分析数量: {args.limit} 篇")
        await service.run_once(dry_run=args.dry_run, limit=args.limit)
        print("✅ 运行完成！")
    
    else:
        # 持续运行
        mode_names = {"quick": "快速", "standard": "标准", "deep": "深度"}
        print("🚀 RSS AI Reader 服务已启动（多智能体版本）")
        print(f"🧠 分析模式: {mode_names[args.mode]}")
        print(f"📥 抓取间隔: {config.schedule.fetch_interval}")
        digest_times_str = "、".join(config.schedule.digest_times)
        print(f"📧 简报时间: 每天 {digest_times_str}")
        print("按 Ctrl+C 停止服务...")
        await service.run()


def main():
    """主入口"""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\n👋 服务已停止")


if __name__ == "__main__":
    main()
