"""RSS AI Reader - 主程序入口"""

import argparse
import asyncio
import signal
import sys
from datetime import datetime
from pathlib import Path
import structlog

# 配置日志
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)

from .config import get_config, reload_config, AppConfig
from .fetcher import RSSParser, ContentExtractor
from .ai import ArticleAnalyzer
from .storage import Database, AnalyzedArticle, DigestArticle, DailyDigest
from .notifier import EmailSender
from .scheduler import Scheduler

logger = structlog.get_logger()


class RSSReaderService:
    """RSS 阅读器服务"""
    
    def __init__(self, config: AppConfig):
        self.config = config
        
        # 初始化组件
        self.db = Database(config.storage.database_path)
        self.rss_parser = RSSParser()
        self.content_extractor = ContentExtractor()
        self.analyzer = ArticleAnalyzer(config.ai)
        self.email_sender = EmailSender(config.email)
        self.scheduler = Scheduler(config.schedule)
        
        # 运行状态
        self._running = False
    
    async def fetch_and_analyze(self):
        """抓取并分析文章"""
        logger.info("starting_fetch_cycle")
        
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
            
            # 4. AI 分析
            analyzed = await self.analyzer.analyze_batch(
                articles_with_content,
                top_pick_count=self.config.filter.top_pick_count,
            )
            
            # 5. 保存到数据库
            for article in analyzed:
                self.db.save_analyzed_article(article)
            
            logger.info("fetch_cycle_complete",
                       fetched=len(articles),
                       new=len(new_articles),
                       analyzed=len(analyzed))
        
        except Exception as e:
            logger.error("fetch_cycle_failed", error=str(e))
    
    async def send_daily_digest(self):
        """发送每日简报"""
        logger.info("preparing_daily_digest")
        
        try:
            # 获取未发送的文章
            articles = self.db.get_unsent_articles(
                limit=self.config.filter.max_articles_per_digest
            )
            
            if not articles:
                logger.info("no_articles_to_send")
                return
            
            # 构建简报
            top_picks = []
            other_articles = []
            
            for article in articles:
                digest_article = DigestArticle(
                    title=article.title,
                    url=article.url,
                    source=article.source,
                    category=article.category,
                    score=article.score,
                    summary=article.ai_summary or article.summary,
                    reasoning=article.reasoning,
                    is_top_pick=article.is_top_pick,
                    tags=article.tags,
                )
                
                if article.is_top_pick:
                    top_picks.append(digest_article)
                elif article.score >= self.config.filter.min_score:
                    other_articles.append(digest_article)
            
            # 限制精选数量
            top_picks = top_picks[:self.config.filter.top_pick_count]
            
            digest = DailyDigest(
                date=datetime.now(),
                top_picks=top_picks,
                other_articles=other_articles,
                total_fetched=len(articles),
                total_analyzed=len(articles),
                total_filtered=len(top_picks) + len(other_articles),
            )
            
            # 发送邮件
            success = await self.email_sender.send_digest(digest)
            
            if success:
                # 标记文章已发送
                sent_urls = [a.url for a in articles]
                self.db.mark_articles_sent(sent_urls)
                logger.info("digest_sent_successfully",
                           top_picks=len(top_picks),
                           other=len(other_articles))
            else:
                logger.error("digest_send_failed")
        
        except Exception as e:
            logger.error("digest_preparation_failed", error=str(e))
    
    async def run_once(self, dry_run: bool = False):
        """运行一次（用于测试）"""
        await self.fetch_and_analyze()
        
        if not dry_run:
            await self.send_daily_digest()
    
    async def run(self):
        """启动服务"""
        logger.info("starting_service")
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


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="RSS AI Reader - 智能 RSS 阅读器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m src.main                    # 启动服务
  python -m src.main --once             # 运行一次
  python -m src.main --once --dry-run   # 测试运行（不发送邮件）
  python -m src.main --test-email       # 发送测试邮件
        """
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
    service = RSSReaderService(config)
    
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
        await service.run_once(dry_run=args.dry_run)
        print("✅ 运行完成！")
    
    else:
        # 持续运行
        print("🚀 RSS AI Reader 服务已启动")
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
