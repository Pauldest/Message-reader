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

# 使用条件导入支持两种运行方式
try:
    # 作为模块运行: python -m src.main
    from .config import get_config, reload_config, AppConfig
    from .fetcher import RSSParser, ContentExtractor
    from .agents import AnalysisOrchestrator
    from .models.agent import AnalysisMode
    from .models.article import Article as NewArticle, EnrichedArticle
    from .storage import Database, DigestArticle, DailyDigest
    from .storage.models import Article as LegacyArticle, AnalyzedArticle
    from .notifier import EmailSender
    from .scheduler import Scheduler
except ImportError:
    # 直接运行: python src/main.py
    from src.config import get_config, reload_config, AppConfig
    from src.fetcher import RSSParser, ContentExtractor
    from src.agents import AnalysisOrchestrator
    from src.models.agent import AnalysisMode
    from src.models.article import Article as NewArticle, EnrichedArticle
    from src.storage import Database, DigestArticle, DailyDigest
    from src.storage.models import Article as LegacyArticle, AnalyzedArticle
    from src.notifier import EmailSender
    from src.scheduler import Scheduler

logger = structlog.get_logger()


class RSSReaderService:
    """RSS 阅读器服务 (Multi-Agent Version)"""
    
    def __init__(self, config: AppConfig, analysis_mode: str = "deep"):
        self.config = config
        
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
        
        # 运行状态
        self._running = False
        
        logger.info(
            "service_initialized",
            analysis_mode=self.analysis_mode.value,
            vector_store=self.orchestrator.get_stats().get("vector_store", {}),
        )
    
    async def fetch_and_analyze(self):
        """抓取并分析文章"""
        logger.info("starting_fetch_cycle", mode=self.analysis_mode.value)
        
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
            
            # 3. 提取正文
            articles_with_content = await self.content_extractor.extract_all(new_articles)
            
            # 4. 转换为新的 Article 模型
            new_format_articles = [
                self._convert_to_new_article(a) for a in articles_with_content
            ]
            
            # 5. 🆕 多智能体分析
            enriched_articles = await self.orchestrator.analyze_batch(
                new_format_articles,
                mode=self.analysis_mode,
                max_concurrent=3,
            )
            
            # 6. 保存到数据库
            for article in enriched_articles:
                legacy_article = self._convert_to_legacy_article(article)
                self.db.save_analyzed_article(legacy_article)
            
            logger.info("fetch_cycle_complete",
                       fetched=len(articles),
                       new=len(new_articles),
                       analyzed=len(enriched_articles),
                       top_picks=sum(1 for a in enriched_articles if a.is_top_pick))
        
        except Exception as e:
            logger.error("fetch_cycle_failed", error=str(e))
            import traceback
            traceback.print_exc()
    
    async def send_daily_digest(self):
        """发送每日简报（使用 AI 智能筛选）"""
        logger.info("preparing_daily_digest")
        
        try:
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
            
            # 🆕 使用 Curator AI 智能筛选
            from src.agents import CuratorAgent
            from src.services.llm import LLMService
            
            curator = CuratorAgent(LLMService(self.config.ai))
            curation_result = await curator.curate(
                enriched_articles,
                max_articles=self.config.filter.max_articles_per_digest,
            )
            
            # 构建简报
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
            
            logger.info(
                "curation_complete",
                top_picks=len(top_picks),
                quick_reads=len(other_articles),
                excluded=len(curation_result.get("excluded", [])),
                daily_summary=curation_result.get("daily_summary", "")[:100],
            )
            
            # 发送邮件
            success = await self.email_sender.send_digest(digest)
            
            if success:
                # 只标记被选中的文章为已发送
                sent_urls = [a.url for a in top_picks + other_articles]
                self.db.mark_articles_sent(sent_urls)
                logger.info("digest_sent_successfully",
                           top_picks=len(top_picks),
                           other=len(other_articles))
            else:
                logger.error("digest_send_failed")
        
        except Exception as e:
            logger.error("digest_preparation_failed", error=str(e))
            import traceback
            traceback.print_exc()
    
    async def run_once(self, dry_run: bool = False):
        """运行一次（用于测试）"""
        await self.fetch_and_analyze()
        
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
  python -m src.main --once                  # 运行一次
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
    
    return parser.parse_args()


async def async_main():
    """异步主函数"""
    args = parse_args()
    
    # 加载配置
    if args.config_dir:
        config = reload_config(Path(args.config_dir))
    else:
        config = get_config()
    
    # 创建服务
    service = RSSReaderService(config, analysis_mode=args.mode)
    
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
    
    elif args.once:
        # 运行一次
        mode_names = {"quick": "快速", "standard": "标准", "deep": "深度"}
        print(f"🔍 使用 {mode_names[args.mode]} 分析模式...")
        await service.run_once(dry_run=args.dry_run)
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
