"""定时任务调度模块"""

import asyncio
import re
from datetime import datetime
from typing import Callable, Awaitable
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import structlog

from .config import ScheduleConfig

logger = structlog.get_logger()


class Scheduler:
    """任务调度器"""
    
    def __init__(self, config: ScheduleConfig):
        self.config = config
        self.scheduler = AsyncIOScheduler(timezone=config.timezone)
        self._fetch_job_id = "rss_fetch"
        self._digest_job_prefix = "daily_digest"
    
    def add_fetch_job(self, func: Callable[[], Awaitable[None]]):
        """添加 RSS 抓取任务"""
        interval = self._parse_interval(self.config.fetch_interval)
        
        self.scheduler.add_job(
            func,
            IntervalTrigger(**interval),
            id=self._fetch_job_id,
            name="RSS 抓取任务",
            replace_existing=True,
        )
        
        logger.info("fetch_job_added", interval=self.config.fetch_interval)
    
    def add_digest_job(self, func: Callable[[], Awaitable[None]]):
        """添加每日简报任务（支持多个时间点）"""
        digest_times = self.config.digest_times
        
        for i, time_str in enumerate(digest_times):
            hour, minute = self._parse_time(time_str)
            job_id = f"{self._digest_job_prefix}_{i}"
            
            # 根据时间判断是早报还是晚报
            edition = "早报" if hour < 12 else ("午报" if hour < 18 else "晚报")
            
            self.scheduler.add_job(
                func,
                CronTrigger(hour=hour, minute=minute),
                id=job_id,
                name=f"每日简报 - {edition}",
                replace_existing=True,
            )
            
            logger.info("digest_job_added", time=time_str, edition=edition)
    
    def start(self):
        """启动调度器"""
        self.scheduler.start()
        logger.info("scheduler_started")
    
    def stop(self):
        """停止调度器"""
        self.scheduler.shutdown()
        logger.info("scheduler_stopped")
    
    def _parse_interval(self, interval_str: str) -> dict:
        """解析时间间隔字符串，如 '2h', '30m', '1d'"""
        match = re.match(r'^(\d+)([smhd])$', interval_str.lower())
        if not match:
            raise ValueError(f"无效的时间间隔格式: {interval_str}")
        
        value = int(match.group(1))
        unit = match.group(2)
        
        unit_map = {
            's': 'seconds',
            'm': 'minutes',
            'h': 'hours',
            'd': 'days',
        }
        
        return {unit_map[unit]: value}
    
    def _parse_time(self, time_str: str) -> tuple[int, int]:
        """解析时间字符串，如 '07:00'"""
        parts = time_str.split(":")
        if len(parts) != 2:
            raise ValueError(f"无效的时间格式: {time_str}")
        
        hour = int(parts[0])
        minute = int(parts[1])
        
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError(f"无效的时间值: {time_str}")
        
        return hour, minute
